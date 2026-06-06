"""
Miami Water Monitor — Home Dashboard
Real-time beach & waterway safety snapshot for Miami Beach, FL.
"""

import streamlit as st
from datetime import datetime, timezone, timedelta
from db.connection import query, query_one, backend_name

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Miami Water Monitor",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Hide Streamlit default header chrome */
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1.5rem; padding-bottom: 3rem; }

  /* Site status cards */
  .site-card {
    background: #111827;
    border: 1px solid #1f2d44;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 4px;
    position: relative;
    overflow: hidden;
    cursor: pointer;
    transition: border-color .2s;
  }
  .site-card:hover { border-color: #38bdf8; }
  .card-stripe {
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
  }
  .card-name   { font-size: 13px; font-weight: 600; color: #e2e8f0; margin-bottom: 8px; }
  .card-type   { font-size: 10px; color: #64748b; }
  .card-value  { font-size: 26px; font-weight: 700; margin: 6px 0 2px; }
  .card-unit   { font-size: 11px; color: #64748b; margin-left: 2px; }
  .card-status { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 20px; display: inline-block; margin: 4px 0; }
  .card-footer { font-size: 10px; color: #64748b; margin-top: 10px; padding-top: 8px; border-top: 1px solid #1f2d44; display: flex; justify-content: space-between; }
  .tier-dot    { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 3px; vertical-align: middle; }

  /* Status color classes */
  .GOOD      { color: #22c55e; }
  .MODERATE  { color: #f59e0b; }
  .POOR      { color: #ef4444; }
  .ADVISORY  { color: #dc2626; }
  .UNKNOWN   { color: #475569; }

  .bg-GOOD     { background: rgba(34,197,94,.12);  color: #22c55e; }
  .bg-MODERATE { background: rgba(245,158,11,.12); color: #f59e0b; }
  .bg-POOR     { background: rgba(239,68,68,.12);  color: #ef4444; }
  .bg-ADVISORY { background: rgba(220,38,38,.15);  color: #dc2626; }
  .bg-UNKNOWN  { background: rgba(71,85,105,.12);  color: #475569; }

  .stripe-GOOD     { background: #22c55e; }
  .stripe-MODERATE { background: #f59e0b; }
  .stripe-POOR     { background: #ef4444; }
  .stripe-ADVISORY { background: #dc2626; }
  .stripe-UNKNOWN  { background: #334155; }

  /* Advisory banner */
  .advisory-banner {
    background: rgba(220,38,38,.12);
    border: 1px solid rgba(220,38,38,.4);
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 20px;
  }
  .advisory-title { color: #fca5a5; font-weight: 700; font-size: 14px; margin-bottom: 8px; }
  .advisory-item  { color: #e2e8f0; font-size: 13px; padding: 6px 0; border-top: 1px solid rgba(220,38,38,.2); }
  .advisory-site  { font-weight: 600; color: #fca5a5; }

  /* Metric chips */
  .metric-chip {
    background: #111827; border: 1px solid #1f2d44;
    border-radius: 8px; padding: 10px 14px; text-align: center; margin-bottom: 8px;
  }
  .chip-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .6px; }
  .chip-value { font-size: 20px; font-weight: 700; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)  # 5-minute cache
def load_snapshot():
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')

    latest = query("""
        SELECT s.name AS site_name, s.display_name, s.location_type,
               wr.value, wr.unit, wr.result_class, wr.sample_date,
               wr.collected_at, wr.veracity_tier, wr.lab_certified,
               src.name AS source_name
        FROM water_readings wr
        JOIN sites s ON s.id = wr.site_id
        JOIN sources src ON src.id = wr.source_id
        WHERE wr.id IN (
            SELECT id FROM water_readings wr2
            WHERE wr2.site_id = wr.site_id AND wr2.value IS NOT NULL
            ORDER BY wr2.sample_date DESC, wr2.collected_at DESC
            LIMIT 1
        )
        ORDER BY s.location_type, s.name
    """)

    advisories = query("""
        SELECT s.display_name, a.advisory_type, a.description, a.issued_date, src.name AS source_name
        FROM advisories a
        JOIN sites s ON s.id = a.site_id
        JOIN sources src ON src.id = a.source_id
        WHERE a.is_active = true AND a.advisory_type != 'UNKNOWN'
        ORDER BY a.collected_at DESC
    """) if True else query("""
        SELECT s.display_name, a.advisory_type, a.description, a.issued_date, src.name AS source_name
        FROM advisories a
        JOIN sites s ON s.id = a.site_id
        JOIN sources src ON src.id = a.source_id
        WHERE a.is_active = 1 AND a.advisory_type != 'UNKNOWN'
        ORDER BY a.collected_at DESC
    """)

    avgs = query("""
        SELECT s.name AS site_name, ROUND(AVG(wr.value), 1) AS avg_30d, COUNT(*) AS cnt
        FROM water_readings wr JOIN sites s ON s.id = wr.site_id
        WHERE wr.value IS NOT NULL AND wr.sample_date >= ?
        GROUP BY s.name
    """, (cutoff_30,))

    all_sites = query("SELECT name, display_name, location_type FROM sites ORDER BY location_type, name")
    last_runs = query("""
        SELECT src.name AS source_name, cr.status, cr.completed_at, cr.records_added
        FROM collection_runs cr JOIN sources src ON src.id = cr.source_id
        ORDER BY cr.started_at DESC LIMIT 10
    """)

    return {
        "latest":     {r['site_name']: r for r in latest},
        "advisories": advisories,
        "avgs":       {r['site_name']: r for r in avgs},
        "all_sites":  all_sites,
        "last_runs":  last_runs,
    }


def _rc(value):
    if value is None: return "UNKNOWN"
    if value <= 35:   return "GOOD"
    if value <= 70:   return "MODERATE"
    return "POOR"


STATUS_LABEL = {
    "GOOD":     "✓ Safe",
    "MODERATE": "◑ Caution",
    "POOR":     "✗ Unsafe",
    "ADVISORY": "⚠ Advisory",
    "UNKNOWN":  "? No Data",
}
TYPE_LABEL = {
    "OCEAN_BEACH":  "Ocean Beach",
    "CANAL":        "Canal",
    "BAYSIDE":      "Bayside",
    "INTRACOASTAL": "Intracoastal",
}


def site_card(site, reading, avg, is_advisory):
    rc = "ADVISORY" if is_advisory else (reading['result_class'] if reading else "UNKNOWN")
    val = reading['value'] if reading else None
    val_str = f"{val:.1f}" if val is not None else ("ADVISORY" if is_advisory else "—")
    unit_str = f'<span class="card-unit">MPN/100mL</span>' if val is not None else ""
    avg_str = f"<div style='font-size:10px;color:#64748b;margin-top:4px'>30d avg: {avg['avg_30d']}</div>" if avg else ""
    src = (reading['source_name'] or '').replace(' Healthy Beaches','').replace(' Rising Above','') if reading else "—"
    tier = reading['veracity_tier'] if reading else ""
    tier_color = "#34d399" if tier == "TIER_1" else "#a78bfa"
    date_str = str(reading['sample_date'])[:10] if reading else "—"

    return f"""
    <div class="site-card">
      <div class="card-stripe stripe-{rc}"></div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div class="card-name">{site['display_name']}</div>
        <div class="card-type">{TYPE_LABEL.get(site['location_type'], site['location_type'])}</div>
      </div>
      <div class="card-value {rc}">{val_str}{unit_str}</div>
      <span class="card-status bg-{rc}">{STATUS_LABEL.get(rc, rc)}</span>
      {avg_str}
      <div class="card-footer">
        <span><span class="tier-dot" style="background:{tier_color}"></span>{src}</span>
        <span>{date_str}</span>
      </div>
    </div>"""


# ── Header ────────────────────────────────────────────────────────────────────

col_logo, col_title, col_refresh = st.columns([.05, .8, .15])
with col_logo:
    st.markdown("<div style='font-size:32px;margin-top:4px'>🌊</div>", unsafe_allow_html=True)
with col_title:
    st.markdown("""
    <div style='margin-top:4px'>
      <span style='font-size:20px;font-weight:700;color:#e2e8f0'>Miami Water Monitor</span>
      <span style='font-size:12px;color:#64748b;margin-left:10px'>Beach & waterway safety · Miami Beach, FL</span>
    </div>""", unsafe_allow_html=True)
with col_refresh:
    if st.button("↻ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("<hr style='border:none;border-top:1px solid #1f2d44;margin:8px 0 16px'>", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────

data = load_snapshot()
latest     = data['latest']
advisories = data['advisories']
avgs       = data['avgs']
all_sites  = data['all_sites']
last_runs  = data['last_runs']

advisory_sites = {a['display_name'] for a in advisories}

# ── Advisory banner ───────────────────────────────────────────────────────────

if advisories:
    items = "".join(f"""
      <div class="advisory-item">
        <span class="advisory-site">{a['display_name']}</span>
        &nbsp;·&nbsp; {(a['description'] or '')[:160]}
        <span style='float:right;color:#64748b;font-size:11px'>{str(a['issued_date'] or '')[:10]}</span>
      </div>""" for a in advisories)
    st.markdown(f"""
    <div class="advisory-banner">
      <div class="advisory-title">⚠️ Active Water Quality Advisories</div>
      {items}
    </div>""", unsafe_allow_html=True)

# ── Summary metrics ───────────────────────────────────────────────────────────

total_sites  = len(all_sites)
safe_count   = sum(1 for s in all_sites if (r := latest.get(s['name'])) and r['result_class'] == 'GOOD')
poor_count   = sum(1 for s in all_sites if (r := latest.get(s['name'])) and r['result_class'] == 'POOR')
no_data      = sum(1 for s in all_sites if s['name'] not in latest)
last_collect = last_runs[0]['completed_at'] if last_runs else None

m1, m2, m3, m4, m5 = st.columns(5)
def chip(col, label, value, color="#38bdf8"):
    with col:
        st.markdown(f"""
        <div class="metric-chip">
          <div class="chip-label">{label}</div>
          <div class="chip-value" style="color:{color}">{value}</div>
        </div>""", unsafe_allow_html=True)

chip(m1, "Total Sites", total_sites)
chip(m2, "Safe Right Now", safe_count, "#22c55e")
chip(m3, "Unsafe / Advisory", poor_count + len(advisories), "#ef4444" if poor_count + len(advisories) > 0 else "#22c55e")
chip(m4, "Active Advisories", len(advisories), "#dc2626" if advisories else "#22c55e")
chip(m5, "Last Collection", str(last_collect or "Never")[:10], "#64748b")

st.markdown("<br>", unsafe_allow_html=True)

# ── Site filter ───────────────────────────────────────────────────────────────

col_head, col_filter = st.columns([.5, .5])
with col_head:
    st.markdown("<div style='font-size:13px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px'>Current Status — All Sites</div>", unsafe_allow_html=True)
with col_filter:
    loc_filter = st.selectbox("Filter by type", ["All", "Ocean Beach", "Canal", "Bayside", "Intracoastal"],
                               label_visibility="collapsed")

type_map = {"Ocean Beach": "OCEAN_BEACH", "Canal": "CANAL",
            "Bayside": "BAYSIDE", "Intracoastal": "INTRACOASTAL"}
filtered_sites = all_sites if loc_filter == "All" else \
    [s for s in all_sites if s['location_type'] == type_map.get(loc_filter)]

# ── Site cards grid (4 columns) ───────────────────────────────────────────────

cols = st.columns(4)
for i, site in enumerate(filtered_sites):
    reading    = latest.get(site['name'])
    avg        = avgs.get(site['name'])
    is_adv     = site['display_name'] in advisory_sites
    with cols[i % 4]:
        st.markdown(site_card(site, reading, avg, is_adv), unsafe_allow_html=True)

# ── Quick navigation hint ─────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
<div style='background:#111827;border:1px solid #1f2d44;border-radius:10px;padding:14px 20px;
            display:flex;gap:24px;align-items:center;flex-wrap:wrap'>
  <span style='color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.6px'>Explore →</span>
  <span style='color:#38bdf8;font-size:13px'>📊 Trends — per-site history & trailing averages</span>
  <span style='color:#38bdf8;font-size:13px'>⚠️ Advisories — full advisory log</span>
  <span style='color:#38bdf8;font-size:13px'>🔬 Sources — data provenance & collection log</span>
</div>""", unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown(f"""
<div style='margin-top:32px;padding-top:16px;border-top:1px solid #1f2d44;
            font-size:11px;color:#475569;display:flex;justify-content:space-between'>
  <span>Miami Water Monitor · Data sourced from FL DOH, City of Miami Beach, Miami Waterkeeper</span>
  <span>DB: {backend_name()} · Not a substitute for official health advisories</span>
</div>""", unsafe_allow_html=True)
