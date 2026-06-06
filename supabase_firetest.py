#!/usr/bin/env python3
"""
Supabase / Streamlit smoke test for Miami Water Monitor.

Purpose:
- Verify local env vars or Streamlit secrets are visible.
- Verify SUPABASE_URL is the correct base project URL.
- Verify SUPABASE_KEY works.
- Verify /rest/v1/rpc/run_query works directly.
- Verify supabase-py rpc("run_query") works.
- Print clear pass/fail diagnostics.

Usage:
  cd "/Users/maher/Documents/Claude/Projects/Miami Water Monitor"
  python supabase_firetest.py

Required env vars:
  SUPABASE_URL=https://gtysknyyiosmtekknpri.supabase.co
  SUPABASE_KEY=<anon_or_service_role_key>
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

PROJECT_REF = "gtysknyyiosmtekknpri"
EXPECTED_URL = f"https://{PROJECT_REF}.supabase.co"


def mask_secret(value: str, keep: int = 8) -> str:
    if not value:
        return "<missing>"
    if len(value) <= keep * 2:
        return value[:2] + "..." + value[-2:]
    return value[:keep] + "..." + value[-keep:]


def load_from_streamlit_secrets_if_available(key: str) -> str:
    """
    Allows this script to read .streamlit/secrets.toml when run inside the project,
    but does not require Streamlit to be installed.
    """
    try:
        import streamlit as st  # type: ignore
        val = st.secrets.get(key, "")
        return str(val).strip()
    except Exception:
        return ""


def get_config(key: str) -> str:
    return os.environ.get(key, "").strip() or load_from_streamlit_secrets_if_available(key)


def print_header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def fail(message: str) -> None:
    print(f"❌ FAIL: {message}")


def ok(message: str) -> None:
    print(f"✅ OK: {message}")


def warn(message: str) -> None:
    print(f"⚠️  WARN: {message}")


def main() -> int:
    print_header("Miami Water Monitor — Supabase Firetest")

    url = get_config("SUPABASE_URL")
    key = get_config("SUPABASE_KEY")

    print(f"SUPABASE_URL: {url or '<missing>'}")
    print(f"SUPABASE_KEY: {mask_secret(key)}")

    if not url:
        fail("SUPABASE_URL is missing.")
        print('Set it with: export SUPABASE_URL="https://gtysknyyiosmtekknpri.supabase.co"')
        return 2

    if not key:
        fail("SUPABASE_KEY is missing.")
        print('Set it with: export SUPABASE_KEY="paste_key_here"')
        return 2

    if url.rstrip("/") != EXPECTED_URL:
        fail(f"SUPABASE_URL should be exactly: {EXPECTED_URL}")
        print("Common mistake: do NOT include /rest/v1 at the end.")
        return 2

    ok("URL and key are present, and URL shape is correct.")

    print_header("Test 1 — Direct REST RPC /run_query")
    try:
        import requests
    except Exception as e:
        fail("Could not import requests. Run: python -m pip install requests")
        print(repr(e))
        return 3

    rpc_url = f"{url.rstrip('/')}/rest/v1/rpc/run_query"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"sql": "select 1 as ok", "params": []}

    try:
        response = requests.post(rpc_url, headers=headers, json=payload, timeout=30)
        print(f"POST {rpc_url}")
        print(f"HTTP status: {response.status_code}")
        print("Response text:")
        print(response.text[:2000])
    except Exception as e:
        fail("Direct REST request failed before receiving a response.")
        print(repr(e))
        return 4

    if response.status_code >= 400:
        fail("Direct REST RPC failed.")
        print("\nInterpretation:")
        print("- 404 / PGRST202 / PGRST125: function not visible to PostgREST, wrong schema, or schema cache not reloaded.")
        print("- 401 / 403: key problem or missing grants.")
        print("- 400: function signature/payload mismatch.")
        print("\nRun this in Supabase SQL Editor:")
        print("""
grant execute on function public.run_query(text, jsonb) to anon;
grant execute on function public.run_query(text, jsonb) to authenticated;
notify pgrst, 'reload schema';
select public.run_query('select 1 as ok', '[]'::jsonb);
""".strip())
        return 5

    try:
        parsed: Any = response.json()
    except Exception:
        parsed = response.text

    ok("Direct REST RPC returned HTTP success.")
    print("Parsed response:")
    print(json.dumps(parsed, indent=2, default=str) if not isinstance(parsed, str) else parsed)

    print_header("Test 2 — supabase-py client RPC")
    try:
        from supabase import create_client  # type: ignore
    except Exception as e:
        fail("Could not import supabase. Run: python -m pip install supabase")
        print(repr(e))
        return 6

    try:
        sb = create_client(url, key)
        result = sb.rpc("run_query", {"sql": "select 1 as ok", "params": []}).execute()
        ok("supabase-py rpc('run_query') worked.")
        print("result.data:")
        print(json.dumps(result.data, indent=2, default=str))
    except Exception as e:
        fail("supabase-py RPC failed.")
        print(repr(e))
        print("\nIf direct REST worked but supabase-py failed, pin or upgrade supabase package.")
        return 7

    print_header("Test 3 — Existing app query shape")
    app_sql = """
        SELECT 1 AS ok,
               now()::text AS database_time_utc
    """
    try:
        result = sb.rpc("run_query", {"sql": app_sql, "params": []}).execute()
        ok("Multi-line SQL through run_query worked.")
        print(json.dumps(result.data, indent=2, default=str))
    except Exception as e:
        fail("Multi-line SQL failed. The app's SQL formatting may be incompatible with run_query.")
        print(repr(e))
        return 8

    print_header("Final Result")
    ok("Supabase smoke test passed. The Streamlit failure is now likely inside app.py query SQL or data/table state, not credentials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
