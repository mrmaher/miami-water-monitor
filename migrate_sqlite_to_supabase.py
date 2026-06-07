#!/usr/bin/env python3
"""
Migrate local SQLite history into Supabase via supabase-py table API.

Usage:
  cd "/Users/maher/Documents/Claude/Projects/Miami Water Monitor"
  source .venv/bin/activate
  export SUPABASE_URL="https://gtysknyyiosmtekknpri.supabase.co"
  export SUPABASE_KEY="..."
  python3 migrate_sqlite_to_supabase.py

This script:
- Reads local water_monitor.db
- Clears Supabase child tables first
- Inserts parent tables first
- Converts SQLite 0/1 boolean fields to real booleans
- Preserves primary-key IDs
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from supabase import create_client


DB_PATH = Path("water_monitor.db")

DELETE_ORDER = ["water_readings", "advisories", "collection_runs", "sites", "sources"]
INSERT_ORDER = ["sources", "sites", "collection_runs", "water_readings", "advisories"]

BOOLEAN_COLUMNS = {
    "water_readings": {"lab_certified"},
    "advisories": {"is_active"},
}


def sqlite_rows(table: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def normalize_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)

    for col in BOOLEAN_COLUMNS.get(table, set()):
        if col in out and out[col] is not None:
            out[col] = bool(out[col])

    return out


def main() -> int:
    if not DB_PATH.exists():
        raise SystemExit(f"Missing SQLite database: {DB_PATH.resolve()}")

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

    sb = create_client(url, key)

    print("Source SQLite counts:")
    for table in INSERT_ORDER:
        rows = sqlite_rows(table)
        print(f"  {table}: {len(rows)}")

    print("\nClearing Supabase tables...")
    for table in DELETE_ORDER:
        sb.table(table).delete().neq("id", -999999999).execute()
        print(f"  cleared {table}")

    print("\nLoading Supabase tables...")
    for table in INSERT_ORDER:
        rows = [normalize_row(table, r) for r in sqlite_rows(table)]
        if not rows:
            print(f"  {table}: 0 rows")
            continue

        chunk_size = 100
        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            sb.table(table).insert(chunk).execute()
            inserted += len(chunk)

        print(f"  {table}: inserted {inserted}")

    print("\nVerifying Supabase counts...")
    for table in INSERT_ORDER:
        result = sb.table(table).select("*", count="exact").limit(1).execute()
        print(f"  {table}: {result.count}")

    print("\nDone. Refresh Streamlit with ?v=migrated-history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
