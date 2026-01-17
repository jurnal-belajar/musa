#!/usr/bin/env bash
# placeholder_generator.sh
# Usage:
#   ./placeholder_generator.sh /full/path/to/Activity-Log/2025-2026 batch02 2025-10-13 2025-11-30
# Arguments:
#   1) BASE_DIR       - path to Activity-Log/2025-2026 (required)
#   2) BATCH_NAME     - folder name for the batch, e.g. batch02 (required)
#   3) START_DATE     - start date for the batch in ISO format YYYY-MM-DD (required, will be treated as inclusive)
#   4) END_DATE       - end date for the batch in ISO format YYYY-MM-DD (required, inclusive)
#
# The script will automatically split the date range into consecutive weeks that start on Monday and end on Sunday.
# For partial head/tail weeks the script will still create week folders (week01, week02, ...).
# Each week folder will contain:
#   - readme.md (weekly index with daily placeholders)
#   - img/ (empty folder)
#   - daily markdown files for each date in that week (DDbulanYYYY.md) using Indonesian month names

set -euo pipefail

if [[ "$#" -lt 4 ]]; then
  echo "Usage: $0 BASE_DIR BATCH_NAME START_DATE END_DATE"
  echo "Example: $0 /Users/you/Activity-Log/2025-2026 batch02 2025-10-13 2025-11-30"
  exit 1
fi
BASE_DIR=${1:-./2025-2026}
BATCH_NAME=${2:-batchxx}
START_DATE_STR=$3
END_DATE_STR=$4
UPDATE_README="${5:-}"

BATCH_DIR="${BASE_DIR%/}/${BATCH_NAME}"

echo "Base dir : $BASE_DIR"
echo "Batch dir: $BATCH_DIR"

# If batch folder already exists, abort to avoid accidental overwrite
if [[ -d "$BATCH_DIR" ]]; then
  echo "Batch dir $BATCH_DIR already exists. Aborting to avoid overwriting."
  exit 1
fi

mkdir -p "$BATCH_DIR"

python3 - <<PY
import os
from datetime import datetime, timedelta
import sys

BASE_DIR = os.environ.get('BASE_DIR_ARG') or "$BASE_DIR"
BATCH_NAME = os.environ.get('BATCH_NAME_ARG') or "$BATCH_NAME"
START = os.environ.get('START_DATE_ARG') or "$START_DATE_STR"
END = os.environ.get('END_DATE_ARG') or "$END_DATE_STR"

# Indonesian month names
months = [
    "januari","februari","maret","april","mei","juni",
    "juli","agustus","september","oktober","november","desember"
]

# parse dates
try:
    start_date = datetime.strptime(START, "%Y-%m-%d").date()
    end_date = datetime.strptime(END, "%Y-%m-%d").date()
except Exception as e:
    print("Error parsing dates:", e, file=sys.stderr)
    sys.exit(2)

if end_date < start_date:
    print("END_DATE must be >= START_DATE", file=sys.stderr)
    sys.exit(2)

BATCH_DIR = os.path.join(BASE_DIR, BATCH_NAME)
os.makedirs(BATCH_DIR, exist_ok=True)

# adjust start to previous Monday (to align week boundaries) but keep original start for filenames
# We'll create consecutive Monday--Sunday ranges covering the full [start_date, end_date]

# find the Monday on or before start_date
start_monday = start_date - timedelta(days=(start_date.weekday()))
# find the Sunday on or after end_date
end_sunday = end_date + timedelta(days=(6 - end_date.weekday()))

# generate week ranges
weeks = []
current_start = start_monday
week_index = 1
while current_start <= end_sunday:
    current_end = current_start + timedelta(days=6)
    weeks.append((week_index, current_start, current_end))
    week_index += 1
    current_start = current_end + timedelta(days=1)

# helper to format filename and display date

def fname_for(d):
    return f"{d.day:02d}{months[d.month-1]}{d.year}.md"

def display_date(d):
    return f"{d.day} {months[d.month-1].capitalize()} {d.year}"

# create week folders and files
for idx, wstart, wend in weeks:
    wname = f"week{idx:02d}"
    wf = os.path.join(BATCH_DIR, wname)
    imgf = os.path.join(wf, "img")
    os.makedirs(imgf, exist_ok=True)

    # create readme.md summarizing days that actually fall within the requested start_date..end_date
    readme = os.path.join(wf, "readme.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(f"# Rangkuman Kegiatan Pekanan: {wname.capitalize()} ({wstart.day:02d} {months[wstart.month-1].capitalize()} {wstart.year} - {wend.day:02d} {months[wend.month-1].capitalize()} {wend.year})\n\n")
            f.write("[Kembali](../../readme.md)\n\n")
            f.write("## 🔍 Ringkasan Kegiatan per Hari\n\n")

            d = wstart
            while d <= wend:
                if start_date <= d <= end_date:
                    fname = fname_for(d)
                    f.write(f"- **{display_date(d)}**  \n  Fokus: \n  Capaian: \n  [Lihat log harian](./{fname})\n\n")
                d += timedelta(days=1)

            f.write("\n## 📈 Capaian Mingguan\n\n- \n\n## ⚠️ Tantangan / Evaluasi\n\n- \n")

    # create daily files for days in this week that are within the original range
    d = wstart
    while d <= wend:
        if start_date <= d <= end_date:
            fname = fname_for(d)
            fpath = os.path.join(wf, fname)
            if not os.path.exists(fpath):
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(f"# {display_date(d)} - Log Kegiatan Harian\n")
                    f.write("[Kembali](readme.md)\n\n")
                    f.write("## 📌 Kegiatan\n1. Kegiatan Utama:\n   - Kegiatan: \n   - Alat/bahan: \n   - Durasi: \n\n")
                    f.write("## 🎯 Capaian Kegiatan\n- \n\n")
                    f.write("## 🚧 Kendala\n- \n\n")
                    f.write(f"## 🖼️ Dokumentasi Kegiatan\n![Foto 1](img/{d.isoformat()}_1.jpeg)\n\n")
                    f.write("[Kembali](readme.md)\n")
        d += timedelta(days=1)

print(f"Created batch folder: {BATCH_DIR}")
PY

echo "Done. Check: $BATCH_DIR"

######################################
# UPDATE README (via Python helper)
######################################
if [[ "$UPDATE_README" == "--update-readme" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  PY_UPDATE_SCRIPT="$SCRIPT_DIR/update_readme.py"

  if [[ ! -f "$PY_UPDATE_SCRIPT" ]]; then
    echo "ERROR: update_readme.py not found at $PY_UPDATE_SCRIPT"
    exit 1
  fi

  echo "Updating readme.md via update_readme.py ..."
  python3 "$PY_UPDATE_SCRIPT" "$BASE_DIR" "$BATCH_NAME"
fi