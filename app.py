
"""
Miami Water Monitor — Dashboard

Old-dashboard style UI with direct Supabase table reads.
No RPC. No SQL joins. No db.connection dependency.
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
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    .main { background: #f8fafc; }
    .hero {
        padding: 1.2rem 1.4rem;
        border-radius: 1.1rem;
        background: linear-gradient(135deg, #0f766e 0%, #0369a1 100%);
        color: white;
        margin-bottom: 1rem;
    }
    .hero h1 { margin: 0; font-size: 2rem; }
    .hero p { margin: .25rem 0 0 0; opacity: .9; }
    .metric-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 1rem;
        padding: 1rem;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .05);
    }
    .metric-label {
        color: #64748b;
        font-size: .8rem;
        text-transform: uppercase;
        letter-spacing: .04em;
    }
    .metric-value {
        color: #0f172a;
        font-size: 1.8rem;
        font-weight: 750;
        margin-top: .2rem;
    }
    .site-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 1rem;
        padding: 1rem;
        min-height: 185px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .05);
        margin-bottom: 1rem;
    }
    .site-title {
        font-size: 1.05rem;
        font-weight: 750;
        color: #0f172a;
        margin-bottom: .2rem;
    }
    .site-type {
        color: #64748b;
        font-size: .82rem;
        margin-bottom: .75rem;
    }
    .reading {
        font-size: 1.6rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: .25rem;
    }
    .subtle {
        color: #64748b;
        font-size: .82rem;
    }
    .status {
        display: inline-block;
        padding: .25rem .55rem;
        border-radius: 999px;
        font-size: .78rem;
        font-weight: 700;
        margin: .35rem 0;
    }
    .good { background: #dcfce7; color: #166534; }
    .moderate { background: #fef9c3; color: #854d0e; }
    .poor { background: #fee2e2; color: #991b1b; }
    .unknown { background: #e2e8f0; color: #334155; }
    .advisory {
        background: #fff7ed;
        border: 1px solid #fed7aa;
        color: #9a3412;
        border-radius: 1rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
</style>
""",
    unsafe_allow_html=True,
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
def load_table(name: str, limit: int = 5000) -> pd.DataFrame:
    sb = get_client()
    res = sb.table(name).select("*").limit(limit).execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_snapshot():
    sites = load_table("sites")
    readings = load_table("water_readings")
    sources = load_table("sources")
    advisories = load_table("advisories")
    runs = load_table("collection_runs", limit=500)

    for df in (sites, readings, sources, advisories, runs):
        if not df.empty and "id" in df.columns:
            df["id"] = pd.to_numeric(df["id"], errors="coerce")

    if sites.empty:
        latest = pd.DataFrame()
    elif readings.empty:
        latest = pd.DataFrame()
    else:
        readings["site_id"] = pd.to_numeric(readings.get("site_id"), errors="coerce")
        readings["source_id"] = pd.to_numeric(readings.get("source_id"), errors="coerce")

        merged = readings.merge(
            sites[["id", "name", "display_name", "location_type"]],
            how="left",
            left_on="site_id",
            right_on="id",
            suffixes=("", "_site"),
        )

        if not sources.empty and "source_id" in merged.columns:
            source_cols = [c for c in ["id", "name", "display_name", "veracity_tier"] if c in sources.columns]
            src = sources[source_cols].copy()
            src = src.rename(columns={"name": "source_name", "display_name": "source_display_name"})
            merged = merged.merge(
                src,
                how="left",
                left_on="source_id",
                right_on="id",
                suffixes=("", "_source"),
            )

        merged["sample_date_dt"] = pd.to_datetime(merged.get("sample_date"), errors="coerce")
        if "collected_at" in merged.columns:
            merged["collected_at_dt"] = pd.to_datetime(merged["collected_at"], errors="coerce")
        else:
            merged["collected_at_dt"] = merged["sample_date_dt"]

        latest = (
            merged.sort_values(["sample_date_dt", "collected_at_dt"], ascending=True)
            .groupby("site_id", as_index=False)
            .tail(1)
        )

    if not advisories.empty and "site_id" in advisories.columns and not sites.empty:
        advisories["site_id"] = pd.to_numeric(advisories["site_id"], errors="coerce")
        advisories = advisories.merge(
            sites[["id", "display_name"]],
            how="left",
            left_on="site_id",
            right_on="id",
            suffixes=("", "_site"),
        )

    if not runs.empty and "started_at" in runs.columns:
        runs["started_at_dt"] = pd.to_datetime(runs["started_at"], errors="coerce")
        runs = runs.sort_values("started_at_dt", ascending=False).head(10)

    return {
        "sites": sites,
        "latest": latest,
        "advisories": advisories,
        "runs": runs,
        "debug": {
            "sites": len(sites),
            "readings": len(readings),
            "sources": len(sources),
            "advisories": len(advisories),
            "runs": len(runs),
            "latest": len(latest),
        },
    }


def status_from_row(row) -> tuple[str, str, str]:
    rc = str(row.get("result_class", "") or "").upper()
    value = row.get("value")

    if rc in {"GOOD", "SAFE", "LOW"}:
        return "GOOD", "✓ Safe", "good"
    if rc in {"MODERATE", "CAUTION", "MEDIUM"}:
        return "MODERATE", "◑ Caution", "moderate"
    if rc in {"POOR", "UNSAFE", "HIGH", "NO_CONTACT"}:
        return "POOR", "✗ Unsafe", "poor"

    try:
        v = float(value)
        if v <= 35:
            return "GOOD", "✓ Safe", "good"
        if v <= 104:
            return "MODERATE", "◑ Caution", "moderate"
        return "POOR", "✗ Unsafe", "poor"
    except Exception:
        return "UNKNOWN", "? No Data", "unknown"


def type_label(x: str) -> str:
    return {
        "OCEAN_BEACH": "Ocean Beach",
        "CANAL": "Canal",
        "BAYSIDE": "Bayside",
        "INTRACOASTAL": "Intracoastal",
    }.get(str(x or ""), str(x or "Unknown"))


def site_card(site: dict, reading: dict | None, advisory: bool = False) -> str:
    if reading:
        _, status_label, klass = status_from_row(reading)
        val = reading.get("value")
        unit = reading.get("unit") or ""
        value_text = f"{float(val):.1f}" if val is not None else "—"
        date_text = str(reading.get("sample_date") or "")[:10] or "—"
        source = reading.get("source_name") or reading.get("source_display_name") or "—"
    else:
        status_label, klass = "? No Data", "unknown"
        value_text, unit, date_text, source = "—", "", "—", "—"

    if advisory:
        status_label, klass = "⚠ Advisory", "poor"

    return f"""
<div class="site-card">
  <div class="site-title">{site.get('display_name') or site.get('name')}</div>
  <div class="site-type">{type_label(site.get('location_type'))}</div>
  <div class="reading">{value_text} <span class="subtle">{unit}</span></div>
  <div class="status {klass}">{status_label}</div>
  <div class="subtle">{source}</div>
  <div class="subtle">Latest: {date_text}</div>
</div>
"""


def main():
    header_left, header_right = st.columns([0.82, 0.18])
    with header_left:
        st.markdown(
            """
<div class="hero">
  <h1>🌊 Miami Water Monitor</h1>
  <p>Beach & waterway safety · Miami Beach, FL</p>
</div>
""",
            unsafe_allow_html=True,
        )
    with header_right:
        if st.button("↻ Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    data = load_snapshot()
    sites = data["sites"]
    latest = data["latest"]
    advisories = data["advisories"]
    runs = data["runs"]
    debug = data["debug"]

    active_advisories = advisories
    if not advisories.empty:
        if "is_active" in advisories.columns:
            active_advisories = advisories[advisories["is_active"].fillna(False).astype(bool)]
        if "advisory_type" in active_advisories.columns:
            active_advisories = active_advisories[
                active_advisories["advisory_type"].fillna("").astype(str).str.upper() != "UNKNOWN"
            ]

    latest_by_site = {}
    if not latest.empty and "site_id" in latest.columns:
        latest_by_site = {int(r["site_id"]): r.to_dict() for _, r in latest.iterrows() if pd.notna(r["site_id"])}

    advisory_site_ids = set()
    if not active_advisories.empty and "site_id" in active_advisories.columns:
        advisory_site_ids = set(active_advisories["site_id"].dropna().astype(int).tolist())

    safe_count = 0
    poor_count = 0
    for _, site in sites.iterrows():
        r = latest_by_site.get(int(site["id"])) if pd.notna(site.get("id")) else None
        if r:
            rc, _, _ = status_from_row(r)
            safe_count += rc == "GOOD"
            poor_count += rc == "POOR"

    total_sites = len(sites)
    no_data = total_sites - len(latest_by_site)
    last_collect = None
    if not runs.empty:
        for col in ["completed_at", "started_at"]:
            if col in runs.columns and runs[col].notna().any():
                last_collect = str(runs.iloc[0].get(col) or "")[:10]
                break

    m1, m2, m3, m4, m5 = st.columns(5)
    metrics = [
        ("Total Sites", total_sites),
        ("Safe Right Now", safe_count),
        ("Unsafe / Advisory", poor_count + len(advisory_site_ids)),
        ("No Data", no_data),
        ("Last Collection", last_collect or "Never"),
    ]
    for col, (label, value) in zip([m1, m2, m3, m4, m5], metrics):
        with col:
            st.markdown(
                f"""
<div class="metric-card">
  <div class="metric-label">{label}</div>
  <div class="metric-value">{value}</div>
</div>
""",
                unsafe_allow_html=True,
            )

    if not active_advisories.empty:
        st.markdown("### ⚠️ Active Water Quality Advisories")
        for _, a in active_advisories.head(5).iterrows():
            site_name = a.get("display_name") or a.get("display_name_site") or f"Site {a.get('site_id')}"
            desc = a.get("description") or ""
            date = str(a.get("issued_date") or "")[:10]
            st.markdown(
                f'<div class="advisory"><b>{site_name}</b> · {date}<br>{str(desc)[:220]}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("### Current Status — All Sites")
    loc_filter = st.selectbox(
        "Filter by type",
        ["All", "Ocean Beach", "Canal", "Bayside", "Intracoastal"],
        label_visibility="collapsed",
    )
    type_map = {
        "Ocean Beach": "OCEAN_BEACH",
        "Canal": "CANAL",
        "Bayside": "BAYSIDE",
        "Intracoastal": "INTRACOASTAL",
    }

    filtered = sites
    if loc_filter != "All" and "location_type" in sites.columns:
        filtered = sites[sites["location_type"] == type_map[loc_filter]]

    cols = st.columns(4)
    for i, (_, site) in enumerate(filtered.iterrows()):
        site_dict = site.to_dict()
        site_id = int(site_dict["id"])
        reading = latest_by_site.get(site_id)
        with cols[i % 4]:
            st.markdown(
                site_card(site_dict, reading, site_id in advisory_site_ids),
                unsafe_allow_html=True,
            )

    with st.expander("Debug counts"):
        st.json(debug)
        st.write("Latest rows")
        st.dataframe(latest, use_container_width=True)
        st.write("Raw sites")
        st.dataframe(sites, use_container_width=True)
        st.write("Raw advisories")
        st.dataframe(advisories, use_container_width=True)

    st.markdown("---")
    st.caption(
        f"Miami Water Monitor · Direct Supabase table reads · Last loaded {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )


if __name__ == "__main__":
    main()
