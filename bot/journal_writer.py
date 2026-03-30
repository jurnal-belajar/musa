"""
Handles reading and writing daily journal log files.
Supports creating a new daily file from a template or appending a new activity
to an existing one.
"""

from datetime import date
from pathlib import Path

from date_resolver import daily_filename, daily_date_header, find_week_folder


def _default_daily_template(d: date, activities: list[dict]) -> str:
    """
    Build the full content for a new daily log file.
    activities: list of dicts with keys: 'name', 'description' (optional)
    """
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

    lines += [
        "",
        "## 🎯 Capaian Kegiatan",
    ]
    for act in activities:
        for cap in act.get("capaian", []):
            lines.append(f"- {cap}")
    if not any(act.get("capaian") for act in activities):
        lines.append("- ")

    lines += [
        "",
        "## 🚧 Kendala",
    ]
    kendala_items = []
    for act in activities:
        kendala_items.extend(act.get("kendala", []))
    if kendala_items:
        for k in kendala_items:
            lines.append(f"- {k}")
    else:
        lines.append("- ")

    lines += [
        "",
        "## 🖼️ Dokumentasi Kegiatan",
        f"![Foto 1](img/{d.strftime('%Y-%m-%d')}_1.jpeg)",
        "",
        "[Kembali](readme.md)",
        "",
    ]
    return "\n".join(lines)


def _append_activities_to_existing(content: str, activities: list[dict]) -> str:
    """
    Append new activities to the Kegiatan section of an existing daily log.
    Finds the last numbered activity and continues numbering.
    Also updates Capaian and Kendala sections.
    """
    lines = content.splitlines()

    # Find highest existing activity number
    last_num = 0
    for line in lines:
        m = __import__("re").match(r"^(\d+)\.", line.strip())
        if m:
            last_num = max(last_num, int(m.group(1)))

    # Find insertion point: before the first blank line after "## 📌 Kegiatan"
    # Strategy: insert before "## 🎯 Capaian Kegiatan" line
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
        # Recalculate kendala index after insertion
        insert_before_kendala = -1
        for i, line in enumerate(lines):
            if "## 🚧 Kendala" in line:
                insert_before_kendala = i

    # Add capaian items
    all_capaian = []
    for act in activities:
        all_capaian.extend(act.get("capaian", []))
    if all_capaian and insert_before_kendala >= 0:
        capaian_lines = [f"- {c}" for c in all_capaian]
        # Insert before kendala section (after existing capaian items)
        # Find last non-empty line before kendala
        insert_pos = insert_before_kendala
        while insert_pos > 0 and lines[insert_pos - 1].strip() == "":
            insert_pos -= 1
        lines[insert_pos:insert_pos] = capaian_lines

    return "\n".join(lines) + "\n"


def write_journal_entry(
    activity_log_root: str,
    target_date: date,
    activities: list[dict],
) -> tuple[str, bool]:
    """
    Write or update a daily journal entry.
    Returns (file_path, created_new) where created_new=True if a new file was made.

    activities format:
    [
        {
            "name": "Cooking Class",
            "description": "Membuat yakitori",   # optional, multiline ok
            "capaian": ["Berhasil memasak yakitori"],  # optional
            "kendala": [],  # optional
        },
        ...
    ]
    """
    batch_dir, week_dir = find_week_folder(activity_log_root, target_date)
    if week_dir is None:
        raise ValueError(
            f"Tidak ditemukan folder week untuk tanggal {target_date}. "
            "Pastikan batch sudah dibuat dengan placeholder_generator.sh."
        )

    filename = daily_filename(target_date)
    daily_file = week_dir / filename

    if daily_file.exists():
        existing = daily_file.read_text(encoding="utf-8")
        # Check if it's just a placeholder (has empty Kegiatan section)
        is_placeholder = "Kegiatan Utama:" in existing or all(
            line.strip() in ("", "-", "- ") or line.startswith("#") or line.startswith("[")
            for line in existing.splitlines()
            if "Kegiatan" not in line and "Capaian" not in line
            and "Kendala" not in line and "Dokumentasi" not in line
        )
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


def _is_empty_placeholder(content: str) -> bool:
    """Return True if the daily file is still an unfilled placeholder."""
    import re
    # Check if all kegiatan/capaian/kendala fields are empty or just have "Kegiatan Utama:"
    kegiatan_pattern = re.search(r"##\s*📌\s*Kegiatan\n(.*?)(?=##|\Z)", content, re.DOTALL)
    if not kegiatan_pattern:
        return True
    section = kegiatan_pattern.group(1).strip()
    # Placeholder has lines like "1. Kegiatan Utama:" with empty sub-items
    lines = [l.strip() for l in section.splitlines() if l.strip()]
    meaningful = [l for l in lines if l not in ("-", "- ") and not l.startswith("- Kegiatan:") and not l.startswith("- Alat") and not l.startswith("- Durasi") and l not in ("1. Kegiatan Utama:",)]
    return len(meaningful) == 0


def update_weekly_readme(
    week_dir: Path,
    target_date: date,
    summary: str,
    focus: str = "",
) -> None:
    """
    Update the weekly readme.md to fill in the day's Fokus and Capaian fields.
    summary: one-line summary of the day's activities
    focus: short focus keyword (optional)
    """
    readme_path = week_dir / "readme.md"
    if not readme_path.exists():
        return

    content = readme_path.read_text(encoding="utf-8")
    date_header = daily_date_header(target_date)

    import re
    # Find the day entry and update Fokus/Capaian
    # Pattern: "- **28 November 2025**\n  Fokus: \n  Capaian: "
    pattern = re.compile(
        r"(- \*\*" + re.escape(date_header) + r"\*\*\s*\n"
        r"\s*Fokus:\s*)(.*?)(\n\s*Capaian:\s*)(.*?)(\n)",
        re.DOTALL,
    )

    def replacer(m):
        fokus_val = focus if focus else m.group(2).strip()
        capaian_val = summary if summary else m.group(4).strip()
        return f"{m.group(1)}{fokus_val}{m.group(3)}{capaian_val}{m.group(5)}"

    new_content = pattern.sub(replacer, content)
    if new_content != content:
        readme_path.write_text(new_content, encoding="utf-8")
