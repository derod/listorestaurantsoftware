"""CLI to migrate loyalty data from the old Soda Silvia rewards SQLite DB.

Run from the project root with the same DATA_DIR/DATABASE_URL env the app uses:

    python migrate_loyalty.py /path/to/soda_silvia.db
    # or set LOYALTY_SOURCE_DB=/path/to/soda_silvia.db and run without args

The heavy lifting lives in app/loyalty_migration.py so the app can also run it
automatically on startup (env MIGRATE_LOYALTY_SRC). Idempotent.
"""
import os
import sys

from app.loyalty_migration import migrate_from_sqlite


def main():
    src = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("LOYALTY_SOURCE_DB", "")).strip()
    if not src or not os.path.isfile(src):
        print(f"ERROR: source DB not found: {src!r}")
        print("Pass the old soda_silvia.db path as an argument or set LOYALTY_SOURCE_DB.")
        sys.exit(1)
    result = migrate_from_sqlite(src)
    print("Migration complete.")
    for k in result["added"]:
        print(f"  {k:10} added={result['added'][k]:4}  skipped(existing)={result['skipped'][k]}")


if __name__ == "__main__":
    main()
