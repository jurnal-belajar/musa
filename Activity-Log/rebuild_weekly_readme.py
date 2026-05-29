#!/usr/bin/env python3
"""
rebuild_weekly_readme.py

Membangun ulang readme.md mingguan dari isi file harian (DDbulanYYYY.md).

Tujuan: setelah edit narasi langsung di file harian (mis. untuk hari yang
tidak ter-cover picdiary.html), rangkuman pekanan tetap sinkron tanpa
harus diketik manual.

Usage:
  python3 rebuild_weekly_readme.py --batch /path/to/Activity-Log/2025-2026/genap-batch01

Bisa diberi --week week04 untuk satu pekan saja.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ID_MONTHS = [
    "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember",
]

DAILY_FILE_RE = re.compile(r'^(\d{1,2})([a-z]+)(\d{4})\.md$', re.IGNORECASE)


@dataclass
class DailyContent:
    date: date
    filename: str
    kegiatan_first: str = ""  # kalimat pertama dari Kegiatan (untuk Fokus)
    capaian: list[str] = field(default_factory=list)  # tiap bullet
    kendala: list[str] = field(default_factory=list)


def parse_date_from_filename(fn: str) -> date | None:
    m = DAILY_FILE_RE.match(fn)
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2).lower()
    year = int(m.group(3))
    if month_name not in ID_MONTHS:
        return None
    return date(year, ID_MONTHS.index(month_name) + 1, day)


def short_date_label(d: date) -> str:
    return f"{d.day} {ID_MONTHS[d.month - 1].capitalize()}"


def display_date(d: date) -> str:
    return f"{d.day} {ID_MONTHS[d.month - 1].capitalize()} {d.year}"


def extract_section(lines: list[str], heading_marker: str) -> list[str]:
    """Ambil baris-baris di bawah heading sampai heading lain / EOF.
    heading_marker contoh: 'Capaian Kegiatan' atau 'Kendala'.
    """
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("## ") and heading_marker in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            out.append(line)
    return out


def normalize_bullets(section_lines: list[str]) -> list[str]:
    """Ekstrak isi dari blok bullet '- ...'. Bullet kosong / placeholder '-' di-skip."""
    bullets: list[str] = []
    current: list[str] = []
    for raw in section_lines:
        if raw.startswith("- "):
            if current:
                bullets.append("\n".join(current).strip())
                current = []
            content = raw[2:].rstrip()
            if content and content != "-":
                current.append(content)
        elif raw.startswith("  ") and current:
            current.append(raw[2:].rstrip())
        # else: blank or unrelated, ignore
    if current:
        bullets.append("\n".join(current).strip())
    # buang bullet yang kosong/placeholder
    return [b for b in bullets if b and b != "-"]


def parse_kegiatan_first_sentence(content: str) -> str:
    """Cari baris 'Kegiatan: ...' pertama di section 📌 Kegiatan, ambil kalimat pertama."""
    lines = content.splitlines()
    in_kegiatan_section = False
    for line in lines:
        if line.startswith("## ") and "Kegiatan" in line and "📌" in line:
            in_kegiatan_section = True
            continue
        if in_kegiatan_section and line.startswith("## "):
            break
        if in_kegiatan_section:
            m = re.match(r'\s*-\s*Kegiatan:\s*(.*)', line)
            if m:
                text = m.group(1).strip()
                if not text or text == "-":
                    return ""
                # ambil kalimat pertama (sampai titik, em-dash, atau end-of-line)
                first = re.split(r'\.\s|\s—\s|—\s|\n', text)[0].strip().rstrip('.').strip()
                return first
    return ""


def parse_daily(path: Path) -> DailyContent | None:
    d = parse_date_from_filename(path.name)
    if not d:
        return None
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    capaian_section = extract_section(lines, "Capaian Kegiatan")
    kendala_section = extract_section(lines, "Kendala")
    return DailyContent(
        date=d,
        filename=path.name,
        kegiatan_first=parse_kegiatan_first_sentence(content),
        capaian=normalize_bullets(capaian_section),
        kendala=normalize_bullets(kendala_section),
    )


def week_range_from_dir(week_dir: Path, dailies: list[DailyContent]) -> tuple[date, date]:
    """Tentukan rentang tanggal pekan. Cari dari existing readme atau dari daily files."""
    readme = week_dir / "readme.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        m = re.search(
            r'\(\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*\)',
            text,
        )
        if m:
            try:
                start = date(int(m.group(3)), ID_MONTHS.index(m.group(2).lower()) + 1, int(m.group(1)))
                end = date(int(m.group(6)), ID_MONTHS.index(m.group(5).lower()) + 1, int(m.group(4)))
                return start, end
            except (ValueError, KeyError):
                pass
    # fallback: dari daily files
    if dailies:
        return min(d.date for d in dailies), max(d.date for d in dailies)
    return date(1970, 1, 1), date(1970, 1, 1)


def build_readme(week_dir: Path, week_name: str, dailies: list[DailyContent]) -> str:
    dailies_sorted = sorted(dailies, key=lambda x: x.date)
    start, end = week_range_from_dir(week_dir, dailies_sorted)

    out: list[str] = []
    out.append(
        f"# Rangkuman Kegiatan Pekanan: {week_name.capitalize()} "
        f"({start.day:02d} {ID_MONTHS[start.month - 1].capitalize()} {start.year} "
        f"- {end.day:02d} {ID_MONTHS[end.month - 1].capitalize()} {end.year})"
    )
    out.append("")
    out.append("[Kembali](../../readme.md)")
    out.append("")
    out.append("## 🔍 Ringkasan Kegiatan per Hari")
    out.append("")

    for dc in dailies_sorted:
        out.append(f"- **{display_date(dc.date)}**  ")
        fokus = dc.kegiatan_first
        capaian_short = dc.capaian[0].split("\n")[0] if dc.capaian else ""
        out.append(f"  Fokus: {fokus}  " if fokus else "  Fokus:   ")
        out.append(f"  Capaian: {capaian_short}  " if capaian_short else "  Capaian:   ")
        out.append(f"  [Lihat log harian](./{dc.filename})")
        out.append("")

    out.append("")
    out.append("## 📈 Capaian Mingguan")
    out.append("")
    any_cap = False
    for dc in dailies_sorted:
        for bullet in dc.capaian:
            lines = [l for l in bullet.splitlines() if l.strip()]
            if not lines:
                continue
            any_cap = True
            label = short_date_label(dc.date)
            out.append(f"- ({label}) {lines[0]}")
            for extra in lines[1:]:
                out.append(f"  {extra}")
    if not any_cap:
        out.append("- ")

    out.append("")
    out.append("## ⚠️ Tantangan / Evaluasi")
    out.append("")
    any_kd = False
    for dc in dailies_sorted:
        for bullet in dc.kendala:
            lines = [l for l in bullet.splitlines() if l.strip()]
            if not lines:
                continue
            any_kd = True
            label = short_date_label(dc.date)
            out.append(f"- ({label}) {lines[0]}")
            for extra in lines[1:]:
                out.append(f"  {extra}")
    if not any_kd:
        out.append("- ")
    out.append("")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="path ke folder batch (mis. Activity-Log/2025-2026/genap-batch01)")
    ap.add_argument("--week", default=None, help="(opsional) hanya satu week, mis. week04")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    batch_dir = Path(args.batch).resolve()
    if not batch_dir.is_dir():
        print(f"ERROR: {batch_dir} bukan direktori", file=sys.stderr)
        sys.exit(1)

    week_dirs = sorted(p for p in batch_dir.iterdir() if p.is_dir() and p.name.startswith("week"))
    if args.week:
        week_dirs = [p for p in week_dirs if p.name == args.week]
        if not week_dirs:
            print(f"ERROR: week '{args.week}' tidak ditemukan", file=sys.stderr)
            sys.exit(1)

    updated = 0
    for wd in week_dirs:
        dailies: list[DailyContent] = []
        for f in sorted(wd.iterdir()):
            if not f.is_file() or not f.name.endswith(".md") or f.name == "readme.md":
                continue
            dc = parse_daily(f)
            if dc:
                dailies.append(dc)
        if not dailies:
            print(f"  - {wd.name}: tidak ada daily file, di-skip")
            continue
        new_text = build_readme(wd, wd.name, dailies)
        readme = wd / "readme.md"
        if args.dry_run:
            print(f"=== {wd.name}/readme.md (preview) ===")
            print(new_text)
            print()
        else:
            readme.write_text(new_text, encoding="utf-8")
        updated += 1

    print(f"\nSelesai. {updated} readme {'di-preview' if args.dry_run else 'diupdate'}.")


if __name__ == "__main__":
    main()
