"""Apply a Lightning SQL file to Zetaris, one statement at a time.

    python scripts/apply_sql.py sql/01_databases.sql
    python scripts/apply_sql.py sql/*.sql
    python scripts/apply_sql.py sql/02_rest_tables.sql --dry-run

Lightning SQL does not accept a batch, so statements are split on `;` and sent
individually. "Object already exists" is treated as success: these files are
meant to be re-runnable, and a re-run is the normal case after editing one
table.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearline.zetaris import ZetarisError, run_sql  # noqa: E402

ALREADY_EXISTS = re.compile(r"already exists|duplicate", re.I)


DELIMITER = "-- @@"


def statements(sql: str):
    """Split a file into statements.

    Semicolons alone are not enough: a `COMPILE USL ... DDL` statement contains
    several `CREATE TABLE (...);` blocks and splitting on `;` shreds it. A file
    may therefore mark its own boundaries with a `-- @@` line, which takes
    precedence. Files without one keep the simple semicolon behaviour.
    """
    lines = sql.splitlines()
    # A LINE that is the delimiter -- not the text appearing mid-sentence, as
    # it does in the comment explaining this very rule.
    if any(line.strip() == DELIMITER for line in lines):
        chunks, current = [], []
        for line in lines:
            if line.strip() == DELIMITER:
                chunks.append("\n".join(current))
                current = []
            else:
                current.append(line)
        chunks.append("\n".join(current))
    else:
        cleaned = "\n".join(
            line for line in sql.splitlines() if not line.strip().startswith("--")
        )
        chunks = cleaned.split(";")

    for raw in chunks:
        statement = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("--")
        ).strip().rstrip(";").strip()
        if statement:
            yield statement


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    failures = 0
    for name in args.files:
        path = Path(name)
        if not path.exists():
            print(f"!! {name} not found")
            failures += 1
            continue
        print(f"\n=== {path} ===")
        for statement in statements(path.read_text(encoding="utf-8")):
            label = " ".join(statement.split())[:76]
            if args.dry_run:
                print(f"  [dry-run] {label}")
                continue
            try:
                rows = run_sql(statement, limit=20)
                detail = f"{len(rows)} row(s)" if rows else "ok"
                print(f"  OK       {label}  -> {detail}")
            except ZetarisError as error:
                message = str(error)
                if ALREADY_EXISTS.search(message):
                    print(f"  EXISTS   {label}")
                else:
                    print(f"  FAIL     {label}\n           {message[:220]}")
                    failures += 1
    print(f"\n{'dry run complete' if args.dry_run else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
