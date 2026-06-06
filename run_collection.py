#!/usr/bin/env python3
"""
Miami Water Monitor – Collection Orchestrator
Run this script to fetch data from all sources and store in the local DB.

Usage:
    python run_collection.py                    # run all collectors
    python run_collection.py --source doh       # run one collector
    python run_collection.py --dry-run          # init DB only, no fetching
    python run_collection.py --report           # print DB summary after run

Designed to be invoked on a schedule (daily or more frequent).
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

# ── Path setup ───────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH      = os.path.join(PROJECT_ROOT, 'water_monitor.db')
sys.path.insert(0, PROJECT_ROOT)

from db.init_db import init_db, get_db
from collectors.doh_beaches    import DOHBeachesCollector
from collectors.mb_rising_above import MBRisingAboveCollector
from collectors.waterkeeper    import WaterkeeperCollector

COLLECTORS = {
    "doh":         DOHBeachesCollector,
    "rising_above": MBRisingAboveCollector,
    "waterkeeper": WaterkeeperCollector,
}

COLLECTOR_ALIASES = {
    "doh":          "doh",
    "beaches":      "doh",
    "mb":           "rising_above",
    "rising":       "rising_above",
    "waterkeeper":  "waterkeeper",
    "wk":           "waterkeeper",
    "swim":         "waterkeeper",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def run_all(conn: sqlite3.Connection, source_filter: str = None) -> list[dict]:
    results = []
    for key, cls in COLLECTORS.items():
        if source_filter and COLLECTOR_ALIASES.get(source_filter, source_filter) != key:
            continue
        print(f"  → [{key}] {cls.__name__} ...", flush=True)
        collector = cls()
        result = collector.run()
        results.append(result)
        status_icon = "✓" if result["status"] == "SUCCESS" else "✗"
        print(f"    {status_icon} {result['status']}: {result['records']} records"
              + (f"  ERROR: {result.get('error','')}" if result.get('error') else ""),
              flush=True)
    return results


def print_report(conn: sqlite3.Connection):
    print("\n── DB Summary ──────────────────────────────────────────────")

    rows = conn.execute(
        "SELECT s.display_name, wr.result_class, wr.value, wr.unit, wr.sample_date, "
        "       src.name as source, wr.veracity_tier "
        "FROM water_readings wr "
        "JOIN sites s ON s.id = wr.site_id "
        "JOIN sources src ON src.id = wr.source_id "
        "ORDER BY wr.sample_date DESC, s.display_name "
        "LIMIT 20"
    ).fetchall()
    if rows:
        print("\nLatest water readings:")
        for r in rows:
            val_str = f"{r['value']:.1f} {r['unit']}" if r['value'] is not None else "N/A"
            print(f"  {r['sample_date']}  {r['display_name']:<30}  "
                  f"{val_str:<20}  {r['result_class']:<10}  [{r['source']}]")
    else:
        print("  No readings yet.")

    adv_rows = conn.execute(
        "SELECT s.display_name, a.advisory_type, a.is_active, a.issued_date, "
        "       a.description, src.name as source "
        "FROM advisories a "
        "JOIN sites s ON s.id = a.site_id "
        "JOIN sources src ON src.id = a.source_id "
        "ORDER BY a.is_active DESC, a.collected_at DESC "
        "LIMIT 10"
    ).fetchall()
    if adv_rows:
        print("\nAdvisories:")
        for a in adv_rows:
            active = "ACTIVE" if a['is_active'] else "inactive"
            desc = (a['description'] or "")[:80].replace('\n', ' ')
            print(f"  [{active}] {a['issued_date'] or '?'}  {a['display_name']:<30}  "
                  f"{a['advisory_type']:<12}  {desc}")

    run_rows = conn.execute(
        "SELECT cr.started_at, cr.status, cr.records_added, cr.completed_at, src.name "
        "FROM collection_runs cr JOIN sources src ON src.id = cr.source_id "
        "ORDER BY cr.started_at DESC LIMIT 10"
    ).fetchall()
    if run_rows:
        print("\nRecent collection runs:")
        for r in run_rows:
            dur = ""
            if r['completed_at'] and r['started_at']:
                try:
                    s = datetime.strptime(r['started_at'], '%Y-%m-%dT%H:%M:%SZ')
                    e = datetime.strptime(r['completed_at'], '%Y-%m-%dT%H:%M:%SZ')
                    dur = f" ({int((e-s).total_seconds())}s)"
                except Exception:
                    pass
            print(f"  {r['started_at']}  {r['name']:<30}  {r['status']:<10}  "
                  f"{r['records_added']} records{dur}")

    print("────────────────────────────────────────────────────────────\n")


def main():
    parser = argparse.ArgumentParser(description="Miami Water Monitor – data collector")
    parser.add_argument("--source", default=None,
                        help="Run only this collector: doh | rising_above | waterkeeper")
    parser.add_argument("--dry-run", action="store_true",
                        help="Initialize DB only, skip fetching")
    parser.add_argument("--report", action="store_true",
                        help="Print DB summary after run")
    parser.add_argument("--db", default=DB_PATH,
                        help="Path to SQLite database file")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"Miami Water Monitor – Collection Run")
    print(f"Started: {utcnow()}")
    print(f"DB:      {args.db}")
    print(f"{'='*60}")

    conn = init_db(args.db)
    print(f"Database ready.\n")

    if args.dry_run:
        print("--dry-run: skipping data fetch.")
        if args.report:
            print_report(conn)
        conn.close()
        return

    print("Running collectors:")
    results = run_all(conn, source_filter=args.source)

    total_records = sum(r["records"] for r in results)
    failed = [r for r in results if r["status"] == "FAILED"]
    print(f"\nCollection complete: {total_records} records added, "
          f"{len(failed)} failures.")

    if args.report or True:   # always print summary
        print_report(conn)

    conn.close()

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
