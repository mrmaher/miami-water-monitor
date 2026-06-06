"""
Trends — per-site historical analysis with Plotly charts.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timezone, timedelta
from db.connection import query

st.set_page_config(page_title="Trends · Miami Water Monitor", page_icon="📊", layout="wide")

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1.5rem; }
  .stat-box { background:#111827;border:1px solid #1f2d44;border-radius:10px;padding:14px 16px;text-align:center; }
  .stat-label { font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.6px; }
  .stat-value { font-size:22px;font-weight:700;margin-top:4px; }
  .GOOD { color:#22c55e; } .MODERATE { color:#f59e0b; } .POOR { color:#ef4444; } .neutral { color:#38bdf8; }
</style>""", unsafe_allow_html=True)

st.markdown("## 📊 Trend Analysis")
st.markdown("<div style='color:#64748b;font-size:13px;margin-bottom:20px'>Per-site enterococcus history · trailing averages · threshold comparison</div>", unsafe_allow_html=True)

# ── Controls ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_sites():
    return query("SELECT name, display_name, location_type FROM sites ORDER BY location_type, name")

sites = load_sites()
site_options = {s['display_name']: s['name'] for s in sites}

c1, c2, c3 = st.columns([.45, .25, .3])
with c1:
    selected_display = st.selectbox("Site", list(site_options.keys()))
with c2:
    days = st.selectbox("Period", [30, 60, 90, 180], index=2, format_func=lambda d: f"{d} days")
with c3:
    sources_filter = st.multiselect("Sources", ["DOH Healthy Beaches", "MB Rising Above", "Miami Waterkeeper"],
                                     default=["DOH Healthy Beaches", "MB Rising Above", "Miami Waterkeeper"])

selected_site = site_options[selected_display]

# ── Load data ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_trend(site_name: str, days: int):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    readings = query("""
        SELECT wr.sample_date, wr.value, wr.result_class, wr.unit,
               wr.veracity_tier, wr.lab_certified, src.name AS source_name
        FROM water_readings wr
        JOIN sites s ON s.id = wr.site_id
        JOIN sources src ON src.id = wr.source_id
        WHERE s.name = ? AND wr.sample_date >= ? AND wr.value IS NOT NULL
        ORDER BY wr.sample_date ASC, src.name
    """, (site_name, cutoff))

    baseline = query("""
        SELECT ROUND(AVG(wr.value), 1) AS avg_val, COUNT(*) AS cnt
        FROM water_readings wr JOIN sites s ON s.id = wr.site_id
        WHERE s.name = ? AND wr.value IS NOT NULL
    """, (site_name,))

    return readings, baseline[0] if baseline else {}

readings_raw, baseline = load_trend(selected_site, days)

# Apply source filter
readings = [r for r in readings_raw if r['source_name'] in sources_filter] if sources_filter else readings_raw

# ── Stats row ─────────────────────────────────────────────────────────────────

def rc(v): return "GOOD" if v<=35 else "MODERATE" if v<=70 else "POOR" if v is not None else "neutral"

vals = [r['value'] for r in readings if r['value'] is not None]
latest_val = vals[-1] if vals else None
avg_val    = round(sum(vals)/len(vals), 1) if vals else None
peak_val   = max(vals) if vals else None
safe_days  = sum(1 for v in vals if v <= 70)
base_avg   = baseline.get('avg_val')

s1,s2,s3,s4,s5,s6 = st.columns(6)
def stat(col, label, value, cls="neutral"):
    v = f"{value:.1f}" if isinstance(value, float) else str(value) if value is not None else "—"
    with col:
        st.markdown(f"""<div class="stat-box">
          <div class="stat-label">{label}</div>
          <div class="stat-value {cls}">{v}</div>
        </div>""", unsafe_allow_html=True)

stat(s1, "Latest",        latest_val, rc(latest_val))
stat(s2, f"{days}d Avg",  avg_val,    rc(avg_val))
stat(s3, "Baseline Avg",  base_avg,   rc(base_avg))
stat(s4, "Peak (period)", peak_val,   rc(peak_val))
stat(s5, "Safe readings", f"{safe_days}/{len(vals)}" if vals else "—",
     "GOOD" if vals and safe_days==len(vals) else "POOR" if vals and safe_days==0 else "MODERATE")
stat(s6, "Threshold",     70, "neutral")

st.markdown("<br>", unsafe_allow_html=True)

# ── Plotly chart ──────────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "DOH Healthy Beaches": "#38bdf8",
    "MB Rising Above":     "#34d399",
    "Miami Waterkeeper":   "#818cf8",
}

fig = go.Figure()

if readings:
    df = pd.DataFrame(readings)
    df['sample_date'] = pd.to_datetime(df['sample_date'])
    df['value'] = pd.to_numeric(df['value'])

    # One trace per source
    for src_name in df['source_name'].unique():
        sub = df[df['source_name'] == src_name].sort_values('sample_date')
        fig.add_trace(go.Scatter(
            x=sub['sample_date'], y=sub['value'],
            mode='lines+markers', name=src_name,
            line=dict(color=SOURCE_COLORS.get(src_name, '#94a3b8'), width=2),
            marker=dict(size=6),
            hovertemplate=(
                f"<b>{src_name}</b><br>"
                "Date: %{x|%b %d, %Y}<br>"
                "Value: %{y:.1f} MPN/100mL<br>"
                "<extra></extra>"
            )
        ))

    # Rolling 30-day average
    df_all = df.sort_values('sample_date').copy()
    df_all = df_all.groupby('sample_date')['value'].mean().reset_index()
    df_all['rolling'] = df_all['value'].rolling(window=min(4, len(df_all)), min_periods=1).mean().round(1)
    fig.add_trace(go.Scatter(
        x=df_all['sample_date'], y=df_all['rolling'],
        mode='lines', name='30-day Rolling Avg',
        line=dict(color='#f59e0b', width=1.5, dash='dot'),
        hovertemplate="Rolling Avg: %{y:.1f} MPN/100mL<extra></extra>"
    ))

    # Baseline average line
    if base_avg:
        fig.add_hline(y=float(base_avg), line_color="#64748b", line_dash="dash", line_width=1,
                      annotation_text=f"Baseline {base_avg}", annotation_font_color="#64748b",
                      annotation_position="bottom right")

# Threshold lines
x_range = [datetime.now(timezone.utc)-timedelta(days=days), datetime.now(timezone.utc)]
fig.add_hline(y=70, line_color="#ef4444", line_dash="dash", line_width=1.5,
              annotation_text="70 MPN — unsafe threshold", annotation_font_color="#ef4444",
              annotation_position="top right")
fig.add_hline(y=35, line_color="#f59e0b", line_dash="dash", line_width=1,
              annotation_text="35 MPN — caution zone", annotation_font_color="#f59e0b",
              annotation_position="bottom right")

# Shade danger zone
fig.add_hrect(y0=70, y1=max([r['value'] for r in readings if r['value']] + [100]) * 1.1 if readings else 200,
              fillcolor="rgba(239,68,68,.05)", line_width=0)
fig.add_hrect(y0=35, y1=70, fillcolor="rgba(245,158,11,.05)", line_width=0)

fig.update_layout(
    plot_bgcolor='#0a0f1e', paper_bgcolor='#111827',
    font=dict(family='system-ui', color='#94a3b8', size=12),
    margin=dict(l=10, r=10, t=20, b=10),
    height=360,
    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                bgcolor='rgba(0,0,0,0)', font=dict(size=11)),
    xaxis=dict(gridcolor='#1f2d44', linecolor='#1f2d44', tickfont=dict(size=10)),
    yaxis=dict(gridcolor='#1f2d44', linecolor='#1f2d44', tickfont=dict(size=10),
               title='MPN/100mL', title_font=dict(size=10), rangemode='tozero'),
    hovermode='x unified',
    hoverlabel=dict(bgcolor='#1a2235', bordercolor='#1f2d44', font_color='#e2e8f0'),
)

if not readings:
    fig.add_annotation(text="No readings for this site and period yet.<br>Run the data collector to populate.",
                       xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                       font=dict(color="#475569", size=14))

st.plotly_chart(fig, use_container_width=True)

# ── Raw data table ────────────────────────────────────────────────────────────

with st.expander("📋 Raw readings table"):
    if readings:
        df_show = pd.DataFrame(readings)[['sample_date','value','result_class','source_name','veracity_tier','lab_certified']]
        df_show.columns = ['Sample Date','Value (MPN/100mL)','Classification','Source','Veracity Tier','NELAP Certified']
        df_show = df_show.sort_values('Sample Date', ascending=False)
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.info("No readings to display.")
