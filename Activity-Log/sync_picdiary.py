#!/usr/bin/env python3
"""
sync_picdiary.py

Sinkronisasi konten picdiary.html ke struktur Activity-Log harian Musa.

Untuk setiap entri di picdiary.html:
- Cari file harian terkait di Activity-Log/2025-2026/<BATCH>/weekXX/DDbulanYYYY.md
- Isi bagian Kegiatan / Capaian / Kendala dari teks picdiary
- Update bagian Dokumentasi Kegiatan dengan jumlah foto yang sesuai
- Salin file gambar dari picdiary/images/ ke weekXX/img/
- Update readme.md mingguan dengan ringkasan Fokus/Capaian per hari

Format yang dipertahankan mengikuti placeholder_generator.sh.

Usage:
  python3 sync_picdiary.py \
      --picdiary /path/to/picdiary \
      --batch    /path/to/Activity-Log/2025-2026/genap-batch01

Tambahkan --dry-run untuk melihat perubahan tanpa menulis ke disk.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

ID_MONTHS = [
    "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember",
]
EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

RECAP_RE = re.compile(r'<div class="recap">(.*?)</div>\s*(?=<div class="recap">|</body>)', re.DOTALL)
HEADLINE_RE = re.compile(r'<div class="headline">(.*?)</div>', re.DOTALL)
TEXT_RE = re.compile(r'<div class="text">(.*?)</div>', re.DOTALL)
IMG_RE = re.compile(r'<img src="([^"]+)"\s*/?>')
DATE_HEADLINE_RE = re.compile(
    r'^[A-Za-z]+,\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:\s*[:\-]\s*(.*))?$'
)


@dataclass
class Entry:
    date: date
    subtitle: str = ""        # bagian setelah tanggal di headline (jika ada)
    kegiatan: str = ""
    capaian: str = ""
    kendala: str = ""
    images: list[str] = field(default_factory=list)


# ----------------------------- parsing helpers ----------------------------- #

def clean_html_text(raw: str) -> str:
    """Konversi fragmen HTML sederhana (p, br) ke teks polos multiline."""
    s = raw
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
    s = re.sub(r'</p>\s*<p[^>]*>', '\n\n', s, flags=re.IGNORECASE)
    s = re.sub(r'</?p[^>]*>', '', s, flags=re.IGNORECASE)
    s = html.unescape(s)
    # collapse > 2 blank lines
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def parse_headline(headline_html: str) -> tuple[date | None, str]:
    text = clean_html_text(headline_html)
    text = text.replace('\n', ' ').strip()
    m = DATE_HEADLINE_RE.match(text)
    if not m:
        return None, ""
    day = int(m.group(1))
    month_name = m.group(2).lower()
    year = int(m.group(3))
    subtitle = (m.group(4) or "").strip()
    month = EN_MONTHS.get(month_name)
    if not month:
        return None, ""
    try:
        return date(year, month, day), subtitle
    except ValueError:
        return None, ""


def split_kegiatan_blocks(text: str) -> tuple[str, str, str]:
    """Pecah teks ke (Kegiatan, Capaian, Kendala). Robust thd label berbeda casing/spasi."""
    # normalisasi label
    pattern = re.compile(r'(?im)^\s*(kegiatan|capaian|kendala)\s*:\s*', re.MULTILINE)
    parts: dict[str, str] = {"kegiatan": "", "capaian": "", "kendala": ""}
    matches = list(pattern.finditer(text))
    if not matches:
        # tidak ada label sama sekali — taruh semua di kegiatan
        return text.strip(), "", ""
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts[key] = text[start:end].strip()
    return parts["kegiatan"], parts["capaian"], parts["kendala"]


def parse_picdiary(html_path: Path) -> list[Entry]:
    raw = html_path.read_text(encoding="utf-8")
    entries: list[Entry] = []
    for m in RECAP_RE.finditer(raw):
        block = m.group(1)
        hm = HEADLINE_RE.search(block)
        if not hm:
            continue
        d, subtitle = parse_headline(hm.group(1))
        if not d:
            continue
        entry = Entry(date=d, subtitle=subtitle)
        tm = TEXT_RE.search(block)
        if tm:
            cleaned = clean_html_text(tm.group(1))
            kg, cp, kd = split_kegiatan_blocks(cleaned)
            entry.kegiatan = kg
            entry.capaian = cp
            entry.kendala = kd
        for im in IMG_RE.finditer(block):
            entry.images.append(im.group(1))
        entries.append(entry)
    return entries


# ----------------------------- musa-focus filter ----------------------------- #

_KAKAK_RE = re.compile(r'\b(kakak|aasiyah)\b', re.IGNORECASE)
_ABANG_RE = re.compile(r'\b(abang|musa)\b', re.IGNORECASE)
_LIST_PREFIX_RE = re.compile(r'^\s*(?:[A-Za-z]\.\s+|\d+\.\s+|-\s+)')


def _is_kakak_only(text: str) -> bool:
    """True jika baris menyebut Kakak/Aasiyah tapi tidak menyebut Abang/Musa."""
    if not text.strip():
        return False
    return bool(_KAKAK_RE.search(text)) and not bool(_ABANG_RE.search(text))


def musa_focus(text: str) -> str:
    """Saring teks agar fokus ke Musa (Abang). Baris yang hanya tentang Kakak dibuang.
    Baris yang menyebut keduanya, atau yang netral, dipertahankan."""
    if not text:
        return text
    kept: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            kept.append(raw)
            continue
        if _is_kakak_only(stripped):
            continue
        # buang penanda list ("A. ", "B. ", "1. ") agar narasi mengalir setelah filtering
        cleaned = _LIST_PREFIX_RE.sub('', raw, count=1)
        kept.append(cleaned)
    result = "\n".join(kept)
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    return result


def musa_focus_subtitle(text: str) -> str:
    """Untuk subtitle headline: jika hanya tentang Kakak, kosongkan."""
    if not text:
        return text
    if _is_kakak_only(text):
        return ""
    return text


# ----------------------------- writer helpers ----------------------------- #

def daily_filename(d: date) -> str:
    return f"{d.day:02d}{ID_MONTHS[d.month - 1]}{d.year}.md"


def display_date(d: date) -> str:
    return f"{d.day} {ID_MONTHS[d.month - 1].capitalize()} {d.year}"


def week_dirs(batch_dir: Path) -> list[Path]:
    return sorted(p for p in batch_dir.iterdir() if p.is_dir() and p.name.startswith("week"))


def find_day_file(batch_dir: Path, d: date) -> Path | None:
    target = daily_filename(d)
    for wd in week_dirs(batch_dir):
        candidate = wd / target
        if candidate.exists():
            return candidate
    return None


def indent_block(text: str, indent: str = "     ") -> str:
    """Indent multiline value so bullet wrap tetap rapi di markdown."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() or True]
    if not lines:
        return ""
    return ("\n" + indent).join(lines)


def render_bullet(text: str) -> str:
    text = text.strip()
    if not text:
        return "- "
    lines = [ln.rstrip() for ln in text.splitlines()]
    out = [f"- {lines[0]}"]
    for ln in lines[1:]:
        out.append(f"  {ln}" if ln else "")
    return "\n".join(out)


def render_kegiatan_value(text: str) -> str:
    """Render nilai 'Kegiatan:' yang multibaris dengan indentasi konsisten."""
    text = text.strip()
    if not text:
        return ""
    lines = text.splitlines()
    out = [lines[0]]
    for ln in lines[1:]:
        if ln.strip():
            out.append("     " + ln.strip())
        else:
            out.append("")
    return "\n".join(out)


def write_daily(path: Path, entry: Entry, batch_relative_imgs: list[str]) -> str:
    """Susun isi file harian. Return string isi."""
    d = entry.date
    lines: list[str] = []
    lines.append(f"# {display_date(d)} - Log Kegiatan Harian")
    lines.append("[Kembali](readme.md)")
    lines.append("")
    lines.append("## 📌 Kegiatan")

    kegiatan_value = render_kegiatan_value(entry.kegiatan) if entry.kegiatan else ""
    if not kegiatan_value and entry.subtitle:
        kegiatan_value = entry.subtitle

    lines.append("1. Kegiatan Utama:")
    lines.append(f"   - Kegiatan: {kegiatan_value}" if kegiatan_value else "   - Kegiatan: -")
    lines.append("   - Alat/bahan: -")
    lines.append("   - Durasi: -")
    lines.append("")

    lines.append("## 🎯 Capaian Kegiatan")
    lines.append(render_bullet(entry.capaian))
    lines.append("")

    lines.append("## 🚧 Kendala")
    lines.append(render_bullet(entry.kendala))
    lines.append("")

    if batch_relative_imgs:
        lines.append("## 🖼️ Dokumentasi Kegiatan")
        for i, name in enumerate(batch_relative_imgs, start=1):
            lines.append(f"![Foto {i}](img/{name})")
        lines.append("")
    lines.append("[Kembali](readme.md)")
    lines.append("")
    return "\n".join(lines)


def summarize_for_readme(entry: Entry) -> tuple[str, str]:
    """Kembalikan (Fokus, Capaian) ringkas untuk weekly readme."""
    fokus = entry.subtitle.strip()
    if not fokus:
        # ambil baris pertama dari kegiatan
        kg = entry.kegiatan.strip()
        fokus = kg.splitlines()[0] if kg else ""
    capaian = entry.capaian.strip()
    if capaian:
        capaian = capaian.splitlines()[0]
    return fokus, capaian


def short_date_label(d: date) -> str:
    return f"{d.day} {ID_MONTHS[d.month - 1].capitalize()}"


def aggregate_bullets(entries_sorted: list[Entry], field_name: str) -> list[str]:
    """Bangun daftar bullet '- (D Mmm) <isi>' dari field daily entry tertentu."""
    bullets: list[str] = []
    for entry in entries_sorted:
        raw = getattr(entry, field_name, "").strip()
        if not raw:
            continue
        # buang baris-baris kosong di tengah, gabungkan dengan break sederhana
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            continue
        label = short_date_label(entry.date)
        first = lines[0]
        bullets.append(f"- ({label}) {first}")
        for extra in lines[1:]:
            bullets.append(f"  {extra}")
    return bullets


def rewrite_week_readme(week_dir: Path, entries_by_date: dict[date, Entry]) -> str | None:
    readme = week_dir / "readme.md"
    if not readme.exists():
        return None
    original = readme.read_text(encoding="utf-8")
    lines = original.splitlines()
    out: list[str] = []

    sorted_entries = [entries_by_date[d] for d in sorted(entries_by_date)]
    capaian_bullets = aggregate_bullets(sorted_entries, "capaian") or ["- "]
    kendala_bullets = aggregate_bullets(sorted_entries, "kendala") or ["- "]

    i = 0
    while i < len(lines):
        line = lines[i]

        # ===== ringkasan harian =====
        m = re.match(r'^- \*\*(\d{1,2}) ([A-Za-z]+) (\d{4})\*\*\s*$', line)
        if m:
            out.append(line)
            day = int(m.group(1))
            month_name = m.group(2).lower()
            year = int(m.group(3))
            month = ID_MONTHS.index(month_name) + 1 if month_name in ID_MONTHS else None
            if month:
                d = date(year, month, day)
                entry = entries_by_date.get(d)
                if entry and i + 3 < len(lines):
                    fokus_line = lines[i + 1]
                    capaian_line = lines[i + 2]
                    link_line = lines[i + 3]
                    fokus, capaian = summarize_for_readme(entry)
                    if re.match(r'^\s*Fokus:', fokus_line):
                        out.append(f"  Fokus: {fokus}  " if fokus else "  Fokus:   ")
                    else:
                        out.append(fokus_line)
                    if re.match(r'^\s*Capaian:', capaian_line):
                        out.append(f"  Capaian: {capaian}  " if capaian else "  Capaian:   ")
                    else:
                        out.append(capaian_line)
                    out.append(link_line)
                    i += 4
                    continue
            i += 1
            continue

        # ===== section Capaian Mingguan / Tantangan / Evaluasi =====
        if line.strip().startswith("## 📈 Capaian Mingguan") or line.strip().startswith("## ⚠️ Tantangan"):
            out.append(line)
            i += 1
            # skip baris kosong segera setelah heading
            while i < len(lines) and not lines[i].strip():
                out.append(lines[i])
                i += 1
            # skip semua baris isi lama (bullet/teks) sampai ketemu heading lain atau EOF
            while i < len(lines) and not lines[i].lstrip().startswith("## "):
                i += 1
            # tulis bullet baru
            bullets = capaian_bullets if "Capaian Mingguan" in line else kendala_bullets
            out.extend(bullets)
            out.append("")
            continue

        out.append(line)
        i += 1

    new_content = "\n".join(out)
    if not new_content.endswith("\n"):
        new_content += "\n"
    return new_content


# ----------------------------- main ----------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--picdiary", required=True, help="path ke folder picdiary (berisi picdiary.html + images/)")
    ap.add_argument("--batch", required=True, help="path ke folder batch (mis. Activity-Log/2025-2026/genap-batch01)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    picdiary_dir = Path(args.picdiary).resolve()
    batch_dir = Path(args.batch).resolve()
    html_path = picdiary_dir / "picdiary.html"
    img_src_dir = picdiary_dir / "images"

    if not html_path.exists():
        print(f"ERROR: tidak menemukan {html_path}", file=sys.stderr)
        sys.exit(1)
    if not batch_dir.exists():
        print(f"ERROR: tidak menemukan {batch_dir}", file=sys.stderr)
        sys.exit(1)

    entries = parse_picdiary(html_path)
    print(f"Parsed {len(entries)} entri dari {html_path.name}")

    # Fokuskan narasi ke Musa (Abang). Baris yang hanya tentang Kakak/Aasiyah dihapus,
    # sedangkan baris bersama (mis. "Abang dan Kakak ...") dipertahankan.
    for entry in entries:
        entry.kegiatan = musa_focus(entry.kegiatan)
        entry.capaian = musa_focus(entry.capaian)
        entry.kendala = musa_focus(entry.kendala)
        entry.subtitle = musa_focus_subtitle(entry.subtitle)

    touched_days = 0
    skipped_days = 0
    missing_imgs: list[str] = []
    copied_imgs = 0
    week_entries_map: dict[Path, dict[date, Entry]] = {}

    for entry in entries:
        day_file = find_day_file(batch_dir, entry.date)
        if not day_file:
            skipped_days += 1
            print(f"  - SKIP {entry.date.isoformat()}: tidak ada file harian di {batch_dir.name}")
            continue

        week_dir = day_file.parent
        img_dir = week_dir / "img"

        # tentukan nama file image yang akan direferensikan (pertahankan ekstensi asli .jpg)
        copied_names: list[str] = []
        for src_rel in entry.images:
            src_name = Path(src_rel).name
            src_path = img_src_dir / src_name
            if not src_path.exists():
                missing_imgs.append(str(src_path))
                continue
            dst_path = img_dir / src_name
            if not args.dry_run:
                img_dir.mkdir(parents=True, exist_ok=True)
                if not dst_path.exists() or dst_path.stat().st_size != src_path.stat().st_size:
                    shutil.copy2(src_path, dst_path)
                    copied_imgs += 1
            copied_names.append(src_name)

        new_content = write_daily(day_file, entry, copied_names)
        if not args.dry_run:
            day_file.write_text(new_content, encoding="utf-8")
        touched_days += 1
        week_entries_map.setdefault(week_dir, {})[entry.date] = entry

    # update weekly readme.md
    weeks_updated = 0
    for week_dir, by_date in week_entries_map.items():
        new_readme = rewrite_week_readme(week_dir, by_date)
        if new_readme is None:
            continue
        if not args.dry_run:
            (week_dir / "readme.md").write_text(new_readme, encoding="utf-8")
        weeks_updated += 1

    print(f"\nSelesai.")
    print(f"  hari diupdate     : {touched_days}")
    print(f"  hari di-skip      : {skipped_days}")
    print(f"  gambar disalin    : {copied_imgs}")
    print(f"  readme mingguan   : {weeks_updated}")
    if missing_imgs:
        print(f"  gambar tidak ada  : {len(missing_imgs)}")
        for p in missing_imgs[:5]:
            print(f"      - {p}")
    if args.dry_run:
        print("  (dry-run: tidak ada file ditulis)")


if __name__ == "__main__":
    main()
