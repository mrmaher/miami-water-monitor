"""
DB Connection Adapter
─────────────────────
Transparently routes to:
  • Postgres (Supabase) when DATABASE_URL is set  → production
  • SQLite                                         → local development

Usage:
    from db.connection import get_conn, query, execute, rows_to_dicts

    conn = get_conn()
    rows = query("SELECT * FROM sites WHERE location_type = ?", ("OCEAN_BEACH",))

All SQL uses ? as the placeholder — the adapter converts to %s for Postgres.
"""

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
SQLITE_PATH  = PROJECT_ROOT / "water_monitor.db"

# Read from env or Streamlit secrets (whichever is available)
def _normalize_url(url: str) -> str:
    """
    Auto-convert a Supabase direct connection URL to the Session Pooler URL.
    Streamlit Cloud runs on IPv4 — the direct host (db.xxx.supabase.co:5432)
    is IPv6-only on free plans, so we must use the Session Pooler instead.

    Direct:  postgresql://postgres:PWD@db.REF.supabase.co:5432/postgres
    Pooler:  postgresql://postgres.REF:PWD@aws-0-us-east-1.pooler.supabase.com:6543/postgres
    """
    m = re.match(
        r'postgresql://postgres:([^@]+)@db\.([^.]+)\.supabase\.co:5432/postgres',
        url
    )
    if m:
        password, project_ref = m.group(1), m.group(2)
        return (
            f"postgresql://postgres.{project_ref}:{password}"
            f"@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        )
    return url


def _get_database_url() -> str | None:
    # 1. Environment variable (GitHub Actions, local .env)
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return _normalize_url(url)
    # 2. Streamlit secrets (when running via streamlit)
    try:
        import streamlit as st
        url = st.secrets.get("DATABASE_URL", "").strip()
        if url:
            return _normalize_url(url)
    except Exception:
        pass
    # 3. Local .streamlit/secrets.toml parsed directly (non-Streamlit scripts)
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        try:
            text = secrets_path.read_text()
            m = re.search(r'DATABASE_URL\s*=\s*["\']([^"\']+)["\']', text)
            if m:
                return _normalize_url(m.group(1).strip())
        except Exception:
            pass
    return None


IS_POSTGRES = bool(_get_database_url())


# ── Postgres ──────────────────────────────────────────────────────────────────

_pg_local  = threading.local()  # thread-local connection pool

def _pg_conn():
    """Return a thread-local Postgres connection."""
    import psycopg2
    import psycopg2.extras
    conn = getattr(_pg_local, "conn", None)
    if conn is None or conn.closed:
        url = _get_database_url()
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        _pg_local.conn = conn
    return conn


def _to_pg(sql: str) -> str:
    """Convert SQLite ? placeholders to Postgres %s."""
    return sql.replace("?", "%s")


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


# ── Public API ────────────────────────────────────────────────────────────────

def get_conn():
    """Return the active connection (Postgres or SQLite)."""
    return _pg_conn() if IS_POSTGRES else _sqlite_conn()


def rows_to_dicts(rows) -> list[dict]:
    """Normalize rows from either driver to plain dicts."""
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(r) for r in rows]
    # psycopg2 RealDictRow is already dict-like
    return [dict(r) for r in rows]


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT and return list of dicts."""
    if IS_POSTGRES:
        conn = _pg_conn()
        with conn.cursor() as cur:
            cur.execute(_to_pg(sql), params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    else:
        conn = _sqlite_conn()
        rows = conn.execute(sql, params).fetchall()
        return rows_to_dicts(rows)


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = (), conn=None) -> Any:
    """Execute an INSERT/UPDATE/DELETE. Returns lastrowid."""
    _own_conn = conn is None
    if IS_POSTGRES:
        c = conn or _pg_conn()
        with c.cursor() as cur:
            cur.execute(_to_pg(sql), params)
            # Try to get lastrowid via RETURNING if it's an INSERT
            try:
                row = cur.fetchone()
                return row[0] if row else None
            except Exception:
                return None
    else:
        c = conn or _sqlite_conn()
        cur = c.execute(sql, params)
        return cur.lastrowid


def executescript(sql: str):
    """Run a multi-statement SQL script (schema creation etc.)."""
    if IS_POSTGRES:
        conn = _pg_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    else:
        conn = _sqlite_conn()
        conn.executescript(sql)
        conn.commit()


def commit():
    if IS_POSTGRES:
        _pg_conn().commit()
    else:
        _sqlite_conn().commit()


def rollback():
    if IS_POSTGRES:
        try: _pg_conn().rollback()
        except Exception: pass
    else:
        try: _sqlite_conn().rollback()
        except Exception: pass


@contextmanager
def transaction():
    """Context manager for atomic transactions."""
    try:
        yield
        commit()
    except Exception:
        rollback()
        raise


def backend_name() -> str:
    return "PostgreSQL (Supabase)" if IS_POSTGRES else f"SQLite ({SQLITE_PATH.name})"
