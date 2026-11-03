"""
One-off: move the Premier League's raw files into the per-competition
layout (data/raw/<Div>/) that load_data expects.

    python src/tools/migrate_layout.py           # show what would move
    python src/tools/migrate_layout.py --apply   # move it (git mv)

    data/raw/EPL<yy-yy>.csv          -> data/raw/E0/results_<yy-yy>.csv
    data/raw/fotmob/<yy-yy>.csv      -> data/raw/E0/fotmob_<yy-yy>.csv
    data/raw/understat/<yy-yy>.csv   -> data/raw/E0/understat_<yy-yy>.csv

Uses ``git mv`` so history follows the files. Refuses to overwrite
anything already at a destination. Safe to re-run: files already moved
are simply not found any more.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DEST = RAW / "E0"

SEASON = r"(\d{2}-\d{2})\.csv"

RULES = [
    (RAW, re.compile(rf"^EPL{SEASON}$"), "results"),
    (RAW / "fotmob", re.compile(rf"^{SEASON}$"), "fotmob"),
    (RAW / "understat", re.compile(rf"^{SEASON}$"), "understat"),
]


def planned_moves():

    moves = []

    for folder, pattern, prefix in RULES:

        if not folder.is_dir():
            continue

        for path in sorted(folder.iterdir()):
            match = pattern.match(path.name)
            if match:
                moves.append((path, DEST / f"{prefix}_{match.group(1)}.csv"))

    return moves


def main():

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually move the files.")
    args = parser.parse_args()

    moves = planned_moves()

    if not moves:
        print("Nothing to move - already migrated.")
        return

    clashes = [dst for _, dst in moves if dst.exists()]
    if clashes:
        sys.exit(f"Refusing to overwrite: {', '.join(str(c.relative_to(ROOT)) for c in clashes)}")

    for src, dst in moves:
        print(f"{src.relative_to(ROOT)}  ->  {dst.relative_to(ROOT)}")

    if not args.apply:
        print(f"\n{len(moves)} file(s). Dry run - re-run with --apply to move them.")
        return

    DEST.mkdir(parents=True, exist_ok=True)

    for src, dst in moves:
        subprocess.run(
            ["git", "mv", str(src.relative_to(ROOT)), str(dst.relative_to(ROOT))],
            cwd=ROOT, check=True,
        )

    # Old cache folders are empty now
    for folder, _, _ in RULES[1:]:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()

    print(f"\nMoved {len(moves)} file(s).")


if __name__ == "__main__":
    main()
