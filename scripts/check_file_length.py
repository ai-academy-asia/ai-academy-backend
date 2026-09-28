"""Fail when a tracked Python file exceeds the line limit (team standard: < 300).

Alembic revisions are generated and exempt. Run: ``python scripts/check_file_length.py``.
"""
import os
import subprocess
import sys

LIMIT = 300
EXEMPT = ("migrations/",)


def main() -> int:
    files = subprocess.run(
        # --others: new files count before they are committed, too.
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    too_long = []
    for path in files:
        # Deleted-but-still-tracked paths show up locally before the commit.
        if path.startswith(EXEMPT) or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            count = sum(1 for _ in fh)
        if count >= LIMIT:
            too_long.append((count, path))
    for count, path in sorted(too_long, reverse=True):
        print(f"{path}: {count} lines (limit {LIMIT - 1})")
    return 1 if too_long else 0


if __name__ == "__main__":
    sys.exit(main())
