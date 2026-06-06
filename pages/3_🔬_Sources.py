"""
Sources — data provenance, collection log, and system status.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from db.connection import query, backend_name

st.set_page_config(page_title="Sources · Miami Water Monitor", page_icon="🔬", layout="wide")

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1.5rem; }
  .source-card {
    background: #111827; border: 1px solid #1f2d44;
    border-radius: 10px; padding: 16px 18px; margin-bottom: 10px;
  }
  .src-name  { font-size: 15px; font-weight: 700; color: #e2e8f0; }
  .src-org   { font-size: 12px; color: #64748b; margin: 3px 0 8px; }
  .src-notes { font-size: 12px; color: #94a3b8; line-height: 1.5; }
  .tier-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 20px; display: inline-block; margin-bottom: 6px; }
  .TIER_1 { background: rgba(52,211,153,.12); color: #34d399; }
  .TIER_2 { background: rgba(167,139,250,.12); color: #a78bfa; }
  .TIER_3 { background: rgba(71,85,105,.12);  color: #94a3b8; }
  .status-pill { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 20px; display: inline-block; }
  .SUCCESS { background: rgba(34,197,94,.12); color: #22c55e; }
  .FAILED  { background: rgba(239,68,68,.12); color: #ef4444; }
  .PARTIAL { background: rgba(245,158,11,.12); color: #f59e0b; }
  .RUNNING { background: rgba(71,85,105,.12); color: #94a3b8; }
</style>""", unsafe_allow_html=True)

st.markdown("## 🔬 Data Sources & Collection Log")
st.markdown(f"<div style='color:#64748b;font-size:13px;margin-bottom:20px'>DB backend: {backend_name()}</div>", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def load_sources_data():
    sources = query("SELECT * FROM sources ORDER BY veracity_tier, name")
    last_runs = query("""
        SELECT src.name AS source_name, cr.status, cr.started_at,
               cr.completed_at, cr.records_added, cr.error_msg, cr.collector_version
        FROM collection_runs cr JOIN sources src ON src.id = cr.source_id
        ORDER BY cr.started_at DESC LIMIT 30
    """)
    site_counts = query("""
        SELECT src.name AS source_name, COUNT(DISTINCT wr.site_id) AS sites,
               COUNT(*) AS total_readings,
               MAX(wr.sample_date) AS latest_sample
        FROM water_readings wr JOIN sources src ON src.id = wr.source_id
        GROUP BY src.name
    """)
    return sources, last_runs, {r['source_name']: r for r in site_counts}

sources, last_runs, site_counts = load_sources_data()

# ── Source cards ──────────────────────────────────────────────────────────────

st.markdown("### Data Sources")

TIER_DESC = {
    "TIER_1": "NELAP-certified lab results — used for official advisory decisions",
    "TIER_2": "Independent certified testing — QAPP methodology, earlier detection",
    "TIER_3": "Community / press release data — directional, not regulatory",
}

for src in sources:
    counts = site_counts.get(src['name'], {})
    last_run = next((r for r in last_runs if r['source_name'] == src['name']), None)
    status = last_run['status'] if last_run else "—"
    latest = str(counts.get('latest_sample', '—'))[:10]

    col_card, col_stats = st.columns([.65, .35])
    with col_card:
        url_link = f'<a href="{src["base_url"]}" target="_blank" style="color:#38bdf8;font-size:11px">Visit source ↗</a>' if src.get('base_url') else ''
        st.markdown(f"""
        <div class="source-card">
          <span class="tier-badge {src['veracity_tier']}">{src['veracity_tier']}</span>
          <div class="src-name">{src['name']}</div>
          <div class="src-org">{src['org']} &nbsp; {url_link}</div>
          <div class="src-notes">{src['notes'] or ''}</div>
          <div style="font-size:11px;color:#475569;margin-top:6px">{TIER_DESC.get(src['veracity_tier'],'')}</div>
        </div>""", unsafe_allow_html=True)
    with col_stats:
        total_r = counts.get('total_readings', 0)
        n_sites = counts.get('sites', 0)
        st.metric("Total Readings", total_r)
        st.metric("Sites Covered",  n_sites)
        st.metric("Latest Sample",  latest)
        if last_run:
            st.markdown(f'<span class="status-pill {status}">{status}</span>', unsafe_allow_html=True)

# ── Collection log ────────────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("### Collection Log")

if last_runs:
    df = pd.DataFrame(last_runs)

    def fmt_dt(val):
        if not val: return "—"
        try:
            return str(val)[:16].replace('T',' ')
        except: return str(val)[:16]

    def duration(row):
        try:
            s = datetime.fromisoformat(str(row['started_at']).replace('Z','+00:00'))
            e = datetime.fromisoformat(str(row['completed_at']).replace('Z','+00:00'))
            return f"{int((e-s).total_seconds())}s"
        except:
            return "—"

    df['Started']  = df['started_at'].apply(fmt_dt)
    df['Duration'] = df.apply(duration, axis=1)
    df_show = df[['Started','source_name','status','records_added','Duration','error_msg','collector_version']].copy()
    df_show.columns = ['Started','Source','Status','Records','Duration','Error','Version']
    df_show['Error'] = df_show['Error'].fillna('').str[:80]

    st.dataframe(df_show, use_container_width=True, hide_index=True,
                 column_config={
                     "Status":  st.column_config.TextColumn("Status"),
                     "Records": st.column_config.NumberColumn("Records", format="%d"),
                 })
else:
    st.info("No collection runs yet. Run `python run_collection.py` to collect data.")

# ── Veracity legend ───────────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
with st.expander("🏷️ Veracity tier definitions"):
    st.markdown("""
    | Tier | Description | Used for official advisories? |
    |---|---|---|
    | **TIER 1** | NELAP-certified laboratory results (FL DOH, City of Miami Beach) | ✅ Yes |
    | **TIER 2** | Independent certified testing with QAPP methodology (Miami Waterkeeper) | ⚠️ No — supplementary |
    | **TIER 3** | Community science, press releases, scrape-derived | ❌ No — directional only |

    Per City of Miami Beach policy, only NELAP-certified lab results are used to issue or lift
    official water quality advisories. TIER_2 data from Miami Waterkeeper often detects spikes
    24-48 hours earlier than NELAP results, providing an early-warning signal.
    """)

# ── Weather preview ───────────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("### 🌤️ Weather Integration — Phase 2")
st.info("""
**Coming soon:** Historical, current, and 7-day forecast weather data from Open-Meteo will be integrated
into the dashboard. Metrics will include temperature, precipitation, wind speed, UV index, wave height,
and visibility — all correlated with water quality readings to surface post-rain contamination patterns.

The `weather_readings` table is already provisioned in the database schema.
Run `python collectors/weather.py` to preview a data collection run.
""")
