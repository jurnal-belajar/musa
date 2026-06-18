"""
Resolves a given date to the correct batch/week folder path within the Activity-Log structure.
"""

import re
from datetime import date
from pathlib import Path

MONTHS_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
}

MONTHS_ID_REVERSE = {v: k for k, v in MONTHS_ID.items()}


def indonesian_month(month_num: int) -> str:
    return MONTHS_ID_REVERSE[month_num]


def parse_indonesian_date(s: str) -> date:
    """Parse '14 Juli 2025' -> date(2025, 7, 14)"""
    parts = s.strip().split()
    day = int(parts[0])
    month = MONTHS_ID[parts[1].lower()]
    year = int(parts[2])
    return date(year, month, day)


def daily_filename(d: date) -> str:
    """Return the daily log filename, e.g. '28november2025.md'"""
    return f"{d.day:02d}{indonesian_month(d.month)}{d.year}.md"


def daily_date_header(d: date) -> str:
    """Return header date string, e.g. '28 November 2025'"""
    return f"{d.day} {indonesian_month(d.month).capitalize()} {d.year}"


def find_week_folder(activity_log_root: str, target_date: date):
    """
    Given a date, find the (batch_dir, week_dir) Path tuple it belongs to.
    Scans all week readme.md files to find the matching date range.
    Returns (batch_dir, week_dir) or (None, None) if not found.
    """
    base = Path(activity_log_root)

    # Find year folders like '2025-2026'
    year_dirs = sorted(
        d for d in base.iterdir()
        if d.is_dir() and re.match(r"\d{4}-\d{4}", d.name)
    )

    for year_dir in year_dirs:
        for batch_dir in sorted(year_dir.iterdir()):
            if not batch_dir.is_dir():
                continue
            if batch_dir.name in ("__pycache__",) or batch_dir.name.startswith("."):
                continue

            for week_dir in sorted(batch_dir.iterdir()):
                if not week_dir.is_dir() or not week_dir.name.startswith("week"):
                    continue

                readme = week_dir / "readme.md"
                if not readme.exists():
                    continue

                with open(readme, encoding="utf-8") as f:
                    first_line = f.readline()

                # Match date range in header: "(14 Juli 2025 - 20 Juli 2025)" or "(14 Juli 2025 – 20 Juli 2025)"
                m = re.search(
                    r"\((\d+\s+\w+\s+\d+)\s*[-–]\s*(\d+\s+\w+\s+\d+)\)",
                    first_line,
                    re.IGNORECASE,
                )
                if not m:
                    continue

                try:
                    start = parse_indonesian_date(m.group(1))
                    end = parse_indonesian_date(m.group(2))
                except (KeyError, ValueError):
                    continue

                if start <= target_date <= end:
                    return batch_dir, week_dir

    return None, None
