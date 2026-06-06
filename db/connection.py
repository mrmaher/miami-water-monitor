"""
DB Connection Adapter
─────────────────────
Routes to:
  • Supabase REST API (via supabase-py) when SUPABASE_URL + SUPABASE_KEY are set → production
  • SQLite                                                                         → local dev

All SQL-like queries are wrapped into supabase-py table operations for production,
or plain sqlite3 for local dev. No psycopg2, no connection strings, no pooler issues.
"""

import os
import json
import sqlite3
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SQLITE_PATH  = PROJECT_ROOT / "water_monitor.db"


# ── Read secrets ──────────────────────────────────────────────────────────────

def _get_secret(key: str) -> str:
    # 1. Environment variable
    val = os.environ.get(key, "").strip()
    if val:
        return val
    # 2. Streamlit secrets
    try:
        import streamlit as st
        val = st.secrets.get(key, "").strip()
        if val:
            return val
    except Exception:
        pass
    # 3. Local .streamlit/secrets.toml
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        try:
            import re
            text = secrets_path.read_text()
            m = re.search(rf'{key}\s*=\s*["\']([^"\']+)["\']', text)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
    return ""


SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_KEY = _get_secret("SUPABASE_KEY")
IS_POSTGRES  = bool(SUPABASE_URL and SUPABASE_KEY)


# ── Supabase client ───────────────────────────────────────────────────────────

_sb_client = None

def _get_sb():
    global _sb_client
    if _sb_client is None:
        from supabase import create_client
        _sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb_client


# ── SQLite ────────────────────────────────────────────────────────────────────

_sqlite_local = threading.local()

def _sqlite_conn() -> sqlite3.Connection:
    conn = getattr(_sqlite_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _sqlite_local.conn = conn
    return conn


# ── Public query API ──────────────────────────────────────────────────────────
#
# For Supabase production we use the supabase-py RPC mechanism with raw SQL
# via a helper Postgres function we create in the schema.
# This avoids all connection-string issues — it's pure HTTPS.
#

def query(sql: str, params: tuple = ()) -> list[dict]:
    if IS_POSTGRES:
        sb = _get_sb()
        # Replace ? placeholders with $1, $2, ... for the RPC call
        import re
        i = 0
        def replacer(m):
            nonlocal i
            i += 1
            return f"${i}"
        pg_sql = re.sub(r'\?', replacer, sql)
        # Build named params dict
        named = {f"p{j+1}": params[j] for j in range(len(params))}
        result = sb.rpc("run_query", {"sql": pg_sql, "params": list(params)}).execute()
        return result.data or []
    else:
        conn = _sqlite_conn()
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> any:
    if IS_POSTGRES:
        sb = _get_sb()
        import re
        i = 0
        def replacer(m):
            nonlocal i
            i += 1
            return f"${i}"
        pg_sql = re.sub(r'\?', replacer, sql)
        result = sb.rpc("run_query", {"sql": pg_sql, "params": list(params)}).execute()
        data = result.data
        if data and isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict):
                return list(first.values())[0]
        return None
    else:
        conn = _sqlite_conn()
        cur = conn.execute(sql, params)
        return cur.lastrowid


def commit():
    if not IS_POSTGRES:
        _sqlite_conn().commit()


def rollback():
    if not IS_POSTGRES:
        try: _sqlite_conn().rollback()
        except Exception: pass


def backend_name() -> str:
    return f"Supabase ({SUPABASE_URL})" if IS_POSTGRES else f"SQLite ({SQLITE_PATH.name})"
