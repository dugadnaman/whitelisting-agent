#!/usr/bin/env python3
"""
CLI Data Migration Utility: SQLite -> PostgreSQL for Karix Whitelisting.
Usage:
  python3 scripts/migrate_sqlite_to_postgres.py [--sqlite-path karix_store.db] [--postgres-url postgresql://user:pass@host:5432/dbname]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import _load_env_file
from db import DEFAULT_SQLITE_PATH, get_database_url, migrate_sqlite_to_postgres

_load_env_file()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate data from SQLite (karix_store.db) to PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE_PATH),
        help=f"Path to local SQLite database file (default: {DEFAULT_SQLITE_PATH})",
    )
    parser.add_argument(
        "--postgres-url",
        default=get_database_url(),
        help="Target PostgreSQL connection URL (e.g. postgresql://user:pass@host:5432/dbname). Defaults to DATABASE_URL / POSTGRES_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect SQLite row counts without inserting into PostgreSQL.",
    )

    args = parser.parse_args()

    sqlite_file = Path(args.sqlite_path)
    if not sqlite_file.exists():
        print(f"❌ Error: SQLite database not found at {sqlite_file}")
        return 1

    print("=" * 60)
    print("🚀 Karix Whitelisting: SQLite -> PostgreSQL Migration Engine")
    print("=" * 60)
    print(f"📁 Source SQLite:  {sqlite_file} ({sqlite_file.stat().st_size:,} bytes)")

    if args.dry_run:
        import sqlite3

        conn = sqlite3.connect(str(sqlite_file))
        c = conn.cursor()
        print("\n📊 Source SQLite Row Counts (Dry Run):")
        for table in ["users", "activities", "ingestion_jobs", "job_tasks", "operational_assignments"]:
            try:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                cnt = c.fetchone()[0]
                print(f"  • {table:<25}: {cnt:>6} rows")
            except Exception as e:
                print(f"  • {table:<25}: Table missing or empty ({e})")
        conn.close()
        print("\n✅ Dry run complete. Specify --postgres-url or DATABASE_URL to execute migration.")
        return 0

    if not args.postgres_url:
        print("❌ Error: Target PostgreSQL URL is required.")
        print("Set DATABASE_URL or POSTGRES_URL in environment or pass --postgres-url.")
        return 1

    safe_target = args.postgres_url.split("@")[-1] if "@" in args.postgres_url else "configured host"
    print(f"🐘 Target Postgres: ...@{safe_target}")
    print("\n⏳ Executing migration with conflict safety (ON CONFLICT DO NOTHING)...")

    try:
        report = migrate_sqlite_to_postgres(sqlite_path=sqlite_file, pg_url=args.postgres_url)
        print("\n✅ Migration Finished Successfully:")
        total_migrated = 0
        for table, count in report.items():
            print(f"  • {table:<25}: {count:>6} rows migrated")
            total_migrated += count
        print("-" * 60)
        print(f"🎉 Total rows migrated to PostgreSQL: {total_migrated:,}")
        return 0
    except Exception as exc:
        print(f"\n❌ Migration failed: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
