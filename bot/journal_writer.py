"""
Handles reading and writing daily journal log files.
Supports creating a new daily file from a template or appending a new activity
to an existing one. Also handles photo saving and documentation section updates.
"""

import re
from datetime import date
from pathlib import Path

from date_resolver import daily_filename, daily_date_header, find_week_folder


# ── Daily file helpers ────────────────────────────────────────────────────────

def _default_daily_template(d: date, activities: list[dict]) -> str:
    header = daily_date_header(d)
    lines = [
        f"# {header} - Log Kegiatan Harian",
        "[Kembali](readme.md)",
        "",
        "## 📌 Kegiatan",
    ]

    for i, act in enumerate(activities, 1):
        lines.append(f"{i}. {act['name']}")
        if act.get("description"):
            for desc_line in act["description"].splitlines():
                lines.append(f"   - {desc_line}")

    lines += ["", "## 🎯 Capaian Kegiatan"]
    for act in activities:
        for cap in act.get("capaian", []):
            lines.append(f"- {cap}")
    if not any(act.get("capaian") for act in activities):
        lines.append("- ")

    lines += ["", "## 🚧 Kendala"]
    kendala_items = [k for act in activities for k in act.get("kendala", [])]
    if kendala_items:
        for k in kendala_items:
            lines.append(f"- {k}")
    else:
        lines.append("- ")

    lines += [
        "",
        "## 🖼️ Dokumentasi Kegiatan",
        "",
        "[Kembali](readme.md)",
        "",
    ]
    return "\n".join(lines)


def _append_activities_to_existing(content: str, activities: list[dict]) -> str:
    lines = content.splitlines()

    last_num = 0
    for line in lines:
        m = re.match(r"^(\d+)\.", line.strip())
        if m:
            last_num = max(last_num, int(m.group(1)))

    insert_before_capaian = -1
    insert_before_kendala = -1
    for i, line in enumerate(lines):
        if "## 🎯 Capaian Kegiatan" in line:
            insert_before_capaian = i
        if "## 🚧 Kendala" in line:
            insert_before_kendala = i

    new_activity_lines = []
    for act in activities:
        last_num += 1
        new_activity_lines.append(f"{last_num}. {act['name']}")
        if act.get("description"):
            for desc_line in act["description"].splitlines():
                new_activity_lines.append(f"   - {desc_line}")
        new_activity_lines.append("")

    if insert_before_capaian >= 0:
        lines[insert_before_capaian:insert_before_capaian] = new_activity_lines
        insert_before_kendala = -1
        for i, line in enumerate(lines):
            if "## 🚧 Kendala" in line:
                insert_before_kendala = i

    all_capaian = [c for act in activities for c in act.get("capaian", [])]
    if all_capaian and insert_before_kendala >= 0:
        insert_pos = insert_before_kendala
        while insert_pos > 0 and lines[insert_pos - 1].strip() == "":
            insert_pos -= 1
        lines[insert_pos:insert_pos] = [f"- {c}" for c in all_capaian]

    return "\n".join(lines) + "\n"


def _is_empty_placeholder(content: str) -> bool:
    kegiatan_pattern = re.search(
        r"##\s*📌\s*Kegiatan\n(.*?)(?=##|\Z)", content, re.DOTALL
    )
    if not kegiatan_pattern:
        return True
    section = kegiatan_pattern.group(1).strip()
    lines = [l.strip() for l in section.splitlines() if l.strip()]
    meaningful = [
        l for l in lines
        if l not in ("-", "- ")
        and not l.startswith("- Kegiatan:")
        and not l.startswith("- Alat")
        and not l.startswith("- Durasi")
        and l not in ("1. Kegiatan Utama:",)
    ]
    return len(meaningful) == 0


# ── Photo helpers ─────────────────────────────────────────────────────────────

def next_photo_index(week_dir: Path, d: date) -> int:
    """Return the next available photo index for the given date."""
    img_dir = week_dir / "img"
    date_prefix = d.strftime("%Y-%m-%d")
    existing = list(img_dir.glob(f"{date_prefix}_*.jp*g")) + \
               list(img_dir.glob(f"{date_prefix}_*.png"))
    if not existing:
        return 1
    indices = []
    for f in existing:
        m = re.search(r"_(\d+)\.", f.name)
        if m:
            indices.append(int(m.group(1)))
    return max(indices, default=0) + 1


def save_photo(week_dir: Path, d: date, photo_bytes: bytes, ext: str = "jpg") -> str:
    """
    Save photo bytes to the week's img/ folder.
    Returns the relative path string, e.g. 'img/2026-03-30_1.jpg'.
    """
    img_dir = week_dir / "img"
    img_dir.mkdir(exist_ok=True)

    idx = next_photo_index(week_dir, d)
    filename = f"{d.strftime('%Y-%m-%d')}_{idx}.{ext.lstrip('.')}"
    dest = img_dir / filename
    dest.write_bytes(photo_bytes)
    return f"img/{filename}"


def update_photo_section(daily_file: Path, photo_rel_paths: list[str]) -> None:
    """
    Replace or update the 🖼️ Dokumentasi Kegiatan section with the given photo paths.
    If the section has placeholder text, replaces it. Otherwise appends new entries.
    """
    if not daily_file.exists() or not photo_rel_paths:
        return

    content = daily_file.read_text(encoding="utf-8")
    photo_lines = "\n".join(f"![Foto]({{p}})" for p in photo_rel_paths)

    # Pattern: section header followed by existing content until next section or EOF
    section_pattern = re.compile(
        r"(## 🖼️ Dokumentasi Kegiatan\n)(.*?)(\n\[Kembali\]|$)",
        re.DOTALL,
    )

    def replacer(m):
        existing_body = m.group(2).strip()
        # Filter out placeholder entries like img/YYYY-MM-DD_1.jpeg
        placeholder_lines = [
            l for l in existing_body.splitlines()
            if re.search(r"img/\d{4}-\d{2}-\d{2}_\d+\.(jpeg|jpg|png)", l)
            and not any(p in l for p in photo_rel_paths)
        ]

        # Build new body: keep non-placeholder lines, add new photos
        kept = [l for l in existing_body.splitlines() if l not in placeholder_lines]
        new_photos = [f"![Foto]({p})" for p in photo_rel_paths]
        body_lines = kept + new_photos
        new_body = "\n".join(body_lines)
        sep = "\n" if new_body else ""
        return f"{m.group(1)}{new_body}{sep}{m.group(3)}"

    new_content = section_pattern.sub(replacer, content)

    # Fallback: if section not found, append before last [Kembali]
    if new_content == content and photo_rel_paths:
        photo_block = "\n".join(f"![Foto]({p})" for p in photo_rel_paths)
        new_content = content.rstrip() + f"\n\n## 🖼️ Dokumentasi Kegiatan\n{photo_block}\n\n[Kembali](readme.md)\n"

    daily_file.write_text(new_content, encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────

def write_journal_entry(
    activity_log_root: str,
    target_date: date,
    activities: list[dict],
) -> tuple[str, bool]:
    """
    Write or update a daily journal entry.
    Returns (file_path, created_new).
    """
    batch_dir, week_dir = find_week_folder(activity_log_root, target_date)
    if week_dir is None:
        raise ValueError(
            f"Tidak ditemukan folder week untuk tanggal {target_date}. "
            "Pastikan batch sudah dibuat dengan placeholder_generator.sh."
        )

    filename   = daily_filename(target_date)
    daily_file = week_dir / filename

    if daily_file.exists():
        existing = daily_file.read_text(encoding="utf-8")
        if _is_empty_placeholder(existing):
            new_content = _default_daily_template(target_date, activities)
            daily_file.write_text(new_content, encoding="utf-8")
            return str(daily_file), True
        else:
            new_content = _append_activities_to_existing(existing, activities)
            daily_file.write_text(new_content, encoding="utf-8")
            return str(daily_file), False
    else:
        new_content = _default_daily_template(target_date, activities)
        daily_file.write_text(new_content, encoding="utf-8")
        return str(daily_file), True


def update_weekly_readme(
    week_dir: Path,
    target_date: date,
    summary: str,
    focus: str = "",
) -> None:
    """Update the weekly readme.md with the day's Fokus and Capaian."""
    readme_path = week_dir / "readme.md"
    if not readme_path.exists():
        return

    content     = readme_path.read_text(encoding="utf-8")
    date_header = daily_date_header(target_date)

    pattern = re.compile(
        r"(- \*\*" + re.escape(date_header) + r"\*\*\s*\n"
        r"\s*Fokus:\s*)(.*?)(\n\s*Capaian:\s*)(.*?)(\n)",
        re.DOTALL,
    )

    def replacer(m):
        fokus_val   = focus   if focus   else m.group(2).strip()
        capaian_val = summary if summary else m.group(4).strip()
        return f"{m.group(1)}{fokus_val}{m.group(3)}{capaian_val}{m.group(5)}"

    new_content = pattern.sub(replacer, content)
    if new_content != content:
        readme_path.write_text(new_content, encoding="utf-8")
