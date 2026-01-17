#!/usr/bin/env python3
"""
update_readme.py

Usage:
  python3 update_readme.py /path/to/Activity-Log/2025-2026 batch01-genap

Behavior:
- Read BASE_DIR/readme.md
- Build navigation section for the given batch
- Replace existing section if found
- Otherwise append at the end
"""

import sys
from pathlib import Path
import re

if len(sys.argv) != 3:
    print("Usage: python3 update_readme.py BASE_DIR BATCH_NAME")
    sys.exit(1)

BASE_DIR = Path(sys.argv[1]).resolve()
BATCH_NAME = sys.argv[2]
README = BASE_DIR / "readme.md"
BATCH_DIR = BASE_DIR / BATCH_NAME

if not README.exists():
    print(f"ERROR: {README} not found")
    sys.exit(1)

if not BATCH_DIR.is_dir():
    print(f"ERROR: batch folder {BATCH_DIR} not found")
    sys.exit(1)

# --------------------------------------------------
# Step 1: Build batch navigation block
# --------------------------------------------------

lines = [f"### {BATCH_NAME}"]

week_dirs = sorted(
    [p for p in BATCH_DIR.iterdir() if p.is_dir() and re.match(r"week\d{2}", p.name)]
)

for week in week_dirs:
    week_readme = week / "readme.md"
    if not week_readme.exists():
        continue

    first_line = week_readme.read_text(encoding="utf-8").splitlines()[0]

    # Expect: "# Rangkuman Kegiatan Pekanan: WeekXX (DATE RANGE)"
    m = re.search(r"(Rangkuman Kegiatan Pekanan: Week\d{2} .*?\))", first_line)
    if not m:
        title = f"Rangkuman Kegiatan Pekanan: {week.name.capitalize()} (Tanggal belum diisi)"
    else:
        title = m.group(1)

    rel_link = f"{BATCH_NAME}/{week.name}/readme.md"
    lines.append(f"- [{title}]({rel_link})")

batch_block = "\n".join(lines)

# --------------------------------------------------
# Step 2: Read existing readme.md
# --------------------------------------------------

content = README.read_text(encoding="utf-8")

# Regex to find existing batch section
pattern = re.compile(
    rf"^###\s+{re.escape(BATCH_NAME)}\s*$.*?(?=^###\s+batch|\Z)",
    re.DOTALL | re.MULTILINE,
)

if pattern.search(content):
    # Replace existing batch section
    new_content = pattern.sub(batch_block + "\n\n", content)
else:
    # Append at end
    if not content.endswith("\n"):
        content += "\n"
    new_content = content + "\n" + batch_block + "\n"

# --------------------------------------------------
# Step 3: Write back
# --------------------------------------------------

README.write_text(new_content, encoding="utf-8")
print(f"Navigation updated for {BATCH_NAME} in {README}")