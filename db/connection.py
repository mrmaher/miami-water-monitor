"""
Database adapter for Miami Water Monitor.

Supports:
- Supabase/PostgREST via SUPABASE_URL + SUPABASE_KEY
- Local SQLite fallback when Supabase env/secrets are absent

Important:
The Supabase SQL function public.run_query(sql text, params jsonb) currently executes
dynamic SQL and does NOT bind params. Therefore this adapter safely inlines simple
scalar params before calling run_query.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = PROJECT_ROOT / "water_monitor.db"

_sqlite_local = threading.local()


def _get_config(key: str) -> str:
    """Read config from environment first, then Streamlit secrets if available."""
    val = os.environ.get(key, "").strip()
    if val:
        return val

    try:
        import streamlit as st  # type: ignore

        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""


SUPABASE_URL = _get_config("SUPABASE_URL")
SUPABASE_KEY = _get_config("SUPABASE_KEY")
IS_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
IS_POSTGRES = IS_SUPABASE  # Backward-compatible name used by collectors


def _sqlite_conn() -> sqlite3.Connection:
    conn = getattr(_sqlite_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _sqlite_local.conn = conn
    return conn


def _sql_literal(value: Any) -> str:
    """Return a SQL literal for simple scalar values used by this app."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    # Dates/datetimes arrive as strings from app.py. Single-quote and escape.
    return "'" + str(value).replace("'", "''") + "'"


def _inline_params(sql: str, params: tuple[Any, ...] | list[Any]) -> str:
    """Replace SQLite-style ? placeholders with SQL literals for run_query."""
    rendered = sql
    for value in params:
        if "?" not in rendered:
            raise ValueError(f"Too many query params supplied for SQL: {sql[:200]}")
        rendered = rendered.replace("?", _sql_literal(value), 1)

    # Do not check for remaining "?" because a later string literal may legitimately
    # contain question marks, especially error tracebacks stored in collection_runs.
    return rendered


def _supabase_client():
    from supabase import create_client  # type: ignore

    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _normalize_rows(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def query(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict]:
    """Run SELECT SQL and return list[dict]."""
    if IS_SUPABASE:
        sb = _supabase_client()
        pg_sql = _inline_params(sql, params)
        result = sb.rpc("run_query", {"sql": pg_sql, "params": []}).execute()
        return _normalize_rows(result.data)

    conn = _sqlite_conn()
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def query_one(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
    """Run write SQL. For Supabase run_query, returns rows if any."""
    if IS_SUPABASE:
        sb = _supabase_client()
        pg_sql = _inline_params(sql, params)
        result = sb.rpc("run_query", {"sql": pg_sql, "params": []}).execute()
        return result.data

    conn = _sqlite_conn()
    cur = conn.execute(sql, params)
    return cur.lastrowid


def commit() -> None:
    if not IS_SUPABASE:
        _sqlite_conn().commit()


def rollback() -> None:
    if not IS_SUPABASE:
        _sqlite_conn().rollback()


def backend_name() -> str:
    if IS_SUPABASE:
        return "Supabase/PostgREST"
    return f"SQLite ({SQLITE_PATH})"
