"""
Commits and pushes journal changes to the git repository.
"""

import subprocess
from datetime import date
from pathlib import Path


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def commit_and_push(repo_root: str, target_date: date, changed_files: list[str]) -> str:
    """
    Stage the changed files, commit, and push.
    Returns the commit hash or a status message.
    """
    repo = Path(repo_root)

    # Stage only the changed files (relative paths)
    rel_files = []
    for f in changed_files:
        try:
            rel = str(Path(f).relative_to(repo))
        except ValueError:
            rel = f
        rel_files.append(rel)

    _run(["git", "add", "--"] + rel_files, cwd=str(repo))

    # Check if there's anything to commit
    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(repo),
        capture_output=True,
    )
    if status.returncode == 0:
        return "Tidak ada perubahan untuk di-commit."

    date_str = target_date.strftime("%d %B %Y")
    commit_msg = f"journal: log kegiatan {date_str}"

    _run(["git", "commit", "-m", commit_msg], cwd=str(repo))

    # Get current branch
    branch_result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo))
    branch = branch_result.stdout.strip()

    # Push with retry logic (up to 4 retries with exponential backoff)
    import time
    last_error = None
    for attempt, wait in enumerate([0, 2, 4, 8, 16]):
        if wait:
            time.sleep(wait)
        try:
            _run(["git", "push", "-u", "origin", branch], cwd=str(repo))
            break
        except subprocess.CalledProcessError as e:
            last_error = e
            if attempt == 4:
                raise RuntimeError(
                    f"Push gagal setelah 4 percobaan: {e.stderr}"
                ) from e

    # Return short commit hash
    result = _run(["git", "rev-parse", "--short", "HEAD"], cwd=str(repo))
    return result.stdout.strip()
