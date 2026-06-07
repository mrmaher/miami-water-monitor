"""
Miami Water Monitor — Field App

Emergency fieldable Streamlit app:
- Avoids SQL joins through run_query/RPC.
- Reads Supabase tables directly using supabase-py table API.
- Merges sites/sources/readings in pandas.
- Displays latest swim-stop status by location.

Required Streamlit secrets:
SUPABASE_URL = "https://gtysknyyiosmtekknpri.supabase.co"
SUPABASE_KEY = "..."
"""

from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from supabase import create_client


st.set_page_config(
    page_title="Miami Water Monitor",
    page_icon="🌊",
    layout="wide",
)


@st.cache_resource(ttl=600)
def get_client():
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY", "")
    if not url or not key:
        st.error("Missing SUPABASE_URL or SUPABASE_KEY in Streamlit secrets.")
        st.stop()
    return create_client(url, key)


@st.cache_data(ttl=300)
def load_table(table: str, limit: int = 5000) -> pd.DataFrame:
    sb = get_client()
    res = sb.table(table).select("*").limit(limit).execute()
    return pd.DataFrame(res.data or [])


def classify_status(row) -> str:
    rc = str(row.get("result_class", "") or "").upper()
    value = row.get("value")

    if rc in {"POOR", "UNSAFE", "HIGH", "NO_CONTACT"}:
        return "🔴 Avoid"
    if rc in {"MODERATE", "CAUTION", "MEDIUM"}:
        return "🟡 Caution"
    if rc in {"GOOD", "SAFE", "LOW"}:
        return "🟢 Likely OK"

    try:
        v = float(value)
        if v <= 35:
            return "🟢 Likely OK"
        if v <= 104:
            return "🟡 Caution"
        return "🔴 Avoid"
    except Exception:
        return "⚪ Unknown"


def main():
    st.title("🌊 Miami Water Monitor")
    st.caption("Field view for bike-ride swim stops. Latest available readings from Supabase.")

    sites = load_table("sites")
    readings = load_table("water_readings")
    sources = load_table("sources")
    advisories = load_table("advisories")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sites", len(sites))
    c2.metric("Readings", len(readings))
    c3.metric("Sources", len(sources))
    c4.metric("Advisories", len(advisories))

    if readings.empty:
        st.warning("No water readings found in Supabase yet.")
        st.write("Sites table:")
        st.dataframe(sites, use_container_width=True)
        return

    for df in [sites, readings, sources]:
        if "id" in df.columns:
            df["id"] = pd.to_numeric(df["id"], errors="coerce")
    if "site_id" in readings.columns:
        readings["site_id"] = pd.to_numeric(readings["site_id"], errors="coerce")
    if "source_id" in readings.columns:
        readings["source_id"] = pd.to_numeric(readings["source_id"], errors="coerce")

    merged = readings.merge(
        sites[["id", "name", "display_name", "location_type"]] if not sites.empty else pd.DataFrame(),
        how="left",
        left_on="site_id",
        right_on="id",
        suffixes=("", "_site"),
    )

    if not sources.empty and "source_id" in merged.columns:
        merged = merged.merge(
            sources[["id", "name"]].rename(columns={"name": "source_name"}),
            how="left",
            left_on="source_id",
            right_on="id",
            suffixes=("", "_source"),
        )
    else:
        merged["source_name"] = ""

    if "sample_date" in merged.columns:
        merged["sample_date_dt"] = pd.to_datetime(merged["sample_date"], errors="coerce")
    else:
        merged["sample_date_dt"] = pd.NaT

    sort_cols = ["sample_date_dt"]
    if "collected_at" in merged.columns:
        merged["collected_at_dt"] = pd.to_datetime(merged["collected_at"], errors="coerce")
        sort_cols.append("collected_at_dt")

    latest = (
        merged.sort_values(sort_cols, ascending=True)
        .groupby("site_id", as_index=False)
        .tail(1)
        .sort_values(["location_type", "display_name"], na_position="last")
    )

    latest["Swim status"] = latest.apply(classify_status, axis=1)

    show_cols = [
        "Swim status",
        "display_name",
        "location_type",
        "sample_date",
        "value",
        "unit",
        "result_class",
        "source_name",
        "metric",
    ]
    show_cols = [c for c in show_cols if c in latest.columns]

    st.subheader("Latest swim-stop status")
    st.dataframe(latest[show_cols], use_container_width=True, hide_index=True)

    st.subheader("Ride-stop cards")
    for _, row in latest.iterrows():
        status = classify_status(row)
        name = row.get("display_name") or row.get("name") or f"Site {row.get('site_id')}"
        date = row.get("sample_date", "unknown date")
        value = row.get("value", "—")
        unit = row.get("unit", "")
        source = row.get("source_name", "unknown source")
        result_class = row.get("result_class", "UNKNOWN")

        with st.container(border=True):
            st.markdown(f"### {status} — {name}")
            st.write(f"Latest: **{value} {unit}** · **{result_class}** · {date} · {source}")

    if not advisories.empty:
        st.subheader("Advisories")
        st.dataframe(advisories, use_container_width=True, hide_index=True)

    with st.expander("Debug: raw latest merged rows"):
        st.dataframe(merged.sort_values(sort_cols, ascending=False).head(50), use_container_width=True)

    st.caption(f"Last loaded: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
