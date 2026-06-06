#!/usr/bin/env python3
"""
Miami Water Monitor – Dashboard Server
Serves the dashboard HTML and JSON API using only Python stdlib.
No Flask, no external dependencies beyond requests/bs4 (used by collectors).

Usage:
    python dashboard/server.py            # default port 8080
    python dashboard/server.py --port 9000
    python dashboard/server.py --collect  # run collectors first, then serve

Open http://localhost:8080 in your browser.
"""
import argparse
import json
import os
import sqlite3
import sys
import threading
import webbrowser
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH      = os.path.join(PROJECT_ROOT, 'water_monitor.db')
HTML_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
sys.path.insert(0, PROJECT_ROOT)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ── API query functions ───────────────────────────────────────────────────────

def api_snapshot() -> dict:
    conn = get_conn()

    # Latest reading per site (most recent sample_date, then collected_at)
    latest_readings = rows_to_list(conn.execute("""
        SELECT
            s.name          AS site_name,
            s.display_name,
            s.location_type,
            s.latitude,
            s.longitude,
            wr.metric,
            wr.value,
            wr.unit,
            wr.result_class,
            wr.sample_date,
            wr.collected_at,
            wr.veracity_tier,
            wr.lab_certified,
            wr.threshold_safe,
            src.name        AS source_name,
            wr.notes
        FROM water_readings wr
        JOIN sites s   ON s.id  = wr.site_id
        JOIN sources src ON src.id = wr.source_id
        WHERE wr.rowid IN (
            SELECT wr2.rowid
            FROM water_readings wr2
            WHERE wr2.site_id = wr.site_id
              AND wr2.value IS NOT NULL
            ORDER BY wr2.sample_date DESC, wr2.collected_at DESC
            LIMIT 1
        )
        ORDER BY s.location_type, s.name
    """).fetchall())

    # Active advisories
    active_advisories = rows_to_list(conn.execute("""
        SELECT
            s.name          AS site_name,
            s.display_name,
            a.advisory_type,
            a.description,
            a.issued_date,
            a.collected_at,
            a.source_url,
            src.name        AS source_name,
            a.veracity_tier
        FROM advisories a
        JOIN sites s   ON s.id  = a.site_id
        JOIN sources src ON src.id = a.source_id
        WHERE a.is_active = 1
          AND a.advisory_type != 'UNKNOWN'
        ORDER BY a.collected_at DESC
    """).fetchall())

    # All sites (even those with no readings yet)
    all_sites = rows_to_list(conn.execute("""
        SELECT name, display_name, location_type, latitude, longitude
        FROM sites ORDER BY location_type, name
    """).fetchall())

    # Last collection run per source
    last_runs = rows_to_list(conn.execute("""
        SELECT src.name AS source_name, cr.status, cr.completed_at,
               cr.records_added, cr.started_at
        FROM collection_runs cr
        JOIN sources src ON src.id = cr.source_id
        WHERE cr.rowid IN (
            SELECT cr2.rowid FROM collection_runs cr2
            WHERE cr2.source_id = cr.source_id
            ORDER BY cr2.started_at DESC LIMIT 1
        )
    """).fetchall())

    # 30-day site averages
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    site_avgs_30 = rows_to_list(conn.execute("""
        SELECT s.name AS site_name, ROUND(AVG(wr.value), 1) AS avg_30d,
               COUNT(*) AS count_30d
        FROM water_readings wr
        JOIN sites s ON s.id = wr.site_id
        WHERE wr.value IS NOT NULL AND wr.sample_date >= ?
        GROUP BY s.name
    """, (cutoff_30,)).fetchall())

    conn.close()

    return {
        "generated_at":     datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "latest_readings":  latest_readings,
        "active_advisories": active_advisories,
        "all_sites":        all_sites,
        "last_runs":        last_runs,
        "site_avgs_30d":    site_avgs_30,
    }


def api_trends(site_name: str, days: int = 90, source_name: str = None) -> dict:
    conn = get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')

    where_clauses = ["wr.sample_date >= ?", "s.name = ?"]
    params = [cutoff, site_name]
    if source_name:
        where_clauses.append("src.name = ?")
        params.append(source_name)

    readings = rows_to_list(conn.execute(f"""
        SELECT
            wr.sample_date,
            wr.value,
            wr.result_class,
            wr.unit,
            wr.veracity_tier,
            wr.lab_certified,
            src.name        AS source_name,
            wr.collected_at,
            wr.notes
        FROM water_readings wr
        JOIN sites s   ON s.id  = wr.site_id
        JOIN sources src ON src.id = wr.source_id
        WHERE {' AND '.join(where_clauses)}
          AND wr.value IS NOT NULL
        ORDER BY wr.sample_date ASC, src.name
    """, params).fetchall())

    # Compute rolling 30-day average at each point
    # Also compute baseline (full history average)
    all_vals = rows_to_list(conn.execute("""
        SELECT wr.sample_date, wr.value
        FROM water_readings wr JOIN sites s ON s.id = wr.site_id
        WHERE s.name = ? AND wr.value IS NOT NULL
        ORDER BY wr.sample_date ASC
    """, (site_name,)).fetchall())

    baseline_avg = None
    if all_vals:
        vals = [r['value'] for r in all_vals]
        baseline_avg = round(sum(vals) / len(vals), 1)

    site_info = conn.execute(
        "SELECT display_name, location_type FROM sites WHERE name = ?", (site_name,)
    ).fetchone()
    site_display = dict(site_info) if site_info else {}

    conn.close()

    return {
        "site_name":    site_name,
        "display_name": site_display.get("display_name", site_name),
        "location_type": site_display.get("location_type"),
        "days":         days,
        "readings":     readings,
        "baseline_avg": baseline_avg,
        "threshold_safe": 70.0,
        "threshold_moderate": 35.0,
    }


def api_sites() -> list:
    conn = get_conn()
    sites = rows_to_list(conn.execute(
        "SELECT name, display_name, location_type, latitude, longitude, notes "
        "FROM sites ORDER BY location_type, name"
    ).fetchall())
    conn.close()
    return sites


def api_runs(limit: int = 20) -> list:
    conn = get_conn()
    runs = rows_to_list(conn.execute("""
        SELECT cr.id, cr.started_at, cr.completed_at, cr.status,
               cr.records_added, cr.error_msg, cr.collector_version,
               src.name AS source_name
        FROM collection_runs cr
        JOIN sources src ON src.id = cr.source_id
        ORDER BY cr.started_at DESC
        LIMIT ?
    """, (limit,)).fetchall())
    conn.close()
    return runs


# ── HTTP handler ──────────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default access log spam

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        qs     = parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            self._serve_html()
        elif path == '/api/snapshot':
            self._json(api_snapshot())
        elif path == '/api/trends':
            site = qs.get('site', ['south_pointe'])[0]
            days = int(qs.get('days', ['90'])[0])
            src  = qs.get('source', [None])[0]
            self._json(api_trends(site, days, src))
        elif path == '/api/sites':
            self._json(api_sites())
        elif path == '/api/runs':
            limit = int(qs.get('limit', ['20'])[0])
            self._json(api_runs(limit))
        else:
            self.send_error(404)

    def _serve_html(self):
        try:
            with open(HTML_PATH, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "Dashboard HTML not found")

    def _json(self, data):
        body = json.dumps(data, default=str).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Miami Water Monitor Dashboard")
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--collect', action='store_true',
                        help='Run data collectors before starting server')
    parser.add_argument('--no-browser', action='store_true',
                        help='Don\'t auto-open browser')
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print("Initializing database...")
        from db.init_db import init_db
        init_db(DB_PATH)

    if args.collect:
        print("Running data collectors...")
        from db.init_db import get_db
        conn = get_db(DB_PATH)
        from collectors.doh_beaches     import DOHBeachesCollector
        from collectors.mb_rising_above import MBRisingAboveCollector
        from collectors.waterkeeper     import WaterkeeperCollector
        for cls in [DOHBeachesCollector, MBRisingAboveCollector, WaterkeeperCollector]:
            r = cls(conn).run()
            print(f"  {r['source']}: {r['status']} ({r['records']} records)")
        conn.close()

    url = f"http://localhost:{args.port}"
    server = HTTPServer(('', args.port), DashboardHandler)
    print(f"\n{'='*50}")
    print(f"  Miami Water Monitor Dashboard")
    print(f"  {url}")
    print(f"  DB: {DB_PATH}")
    print(f"  Ctrl+C to stop")
    print(f"{'='*50}\n")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == '__main__':
    main()
