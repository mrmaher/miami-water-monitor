"""
Advisories — full advisory log and active advisory detail.
"""
import streamlit as st
import pandas as pd
from db.connection import query

st.set_page_config(page_title="Advisories · Miami Water Monitor", page_icon="⚠️", layout="wide")

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1.5rem; }
  .adv-card {
    background: rgba(220,38,38,.08); border: 1px solid rgba(220,38,38,.35);
    border-radius: 10px; padding: 18px 20px; margin-bottom: 12px;
  }
  .adv-card-inactive {
    background: #111827; border: 1px solid #1f2d44;
    border-radius: 10px; padding: 14px 18px; margin-bottom: 8px;
  }
  .adv-type { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 20px; display: inline-block; margin-bottom: 8px; }
  .NO_CONTACT { background: rgba(220,38,38,.2); color: #fca5a5; }
  .CAUTION    { background: rgba(245,158,11,.15); color: #fcd34d; }
  .LIFTED     { background: rgba(34,197,94,.12); color: #86efac; }
  .UNKNOWN    { background: rgba(71,85,105,.15); color: #94a3b8; }
  .adv-site   { font-size: 15px; font-weight: 700; color: #e2e8f0; margin-bottom: 6px; }
  .adv-desc   { font-size: 13px; color: #94a3b8; line-height: 1.5; }
  .adv-meta   { font-size: 11px; color: #64748b; margin-top: 10px; }
</style>""", unsafe_allow_html=True)

st.markdown("## ⚠️ Water Quality Advisories")
st.markdown("<div style='color:#64748b;font-size:13px;margin-bottom:20px'>Official advisories from TIER_1 and TIER_2 sources</div>", unsafe_allow_html=True)

# ── Load advisories ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_advisories():
    active = query("""
        SELECT s.display_name, a.advisory_type, a.description, a.issued_date,
               a.lifted_date, a.collected_at, a.source_url, a.veracity_tier,
               src.name AS source_name
        FROM advisories a
        JOIN sites s ON s.id = a.site_id
        JOIN sources src ON src.id = a.source_id
        WHERE a.is_active = true OR a.is_active = 1
        ORDER BY a.is_active DESC, a.collected_at DESC
    """)
    return active

advisories = load_advisories()
active = [a for a in advisories if a.get('is_active') in (True, 1) and a['advisory_type'] != 'UNKNOWN']
inactive = [a for a in advisories if a.get('is_active') not in (True, 1)]

# ── Active advisories ─────────────────────────────────────────────────────────

if active:
    st.markdown(f"### 🔴 Active Advisories ({len(active)})")
    for a in active:
        desc = (a['description'] or '').replace('\n', ' ')[:500]
        issued = str(a['issued_date'] or '')[:10]
        st.markdown(f"""
        <div class="adv-card">
          <span class="adv-type {a['advisory_type']}">{a['advisory_type'].replace('_',' ')}</span>
          <div class="adv-site">{a['display_name']}</div>
          <div class="adv-desc">{desc}</div>
          <div class="adv-meta">
            Issued: {issued} &nbsp;·&nbsp; Source: {a['source_name']} ({a['veracity_tier']})
            {f'&nbsp;·&nbsp; <a href="{a["source_url"]}" target="_blank" style="color:#38bdf8">View source ↗</a>' if a.get('source_url') else ''}
          </div>
        </div>""", unsafe_allow_html=True)
else:
    st.success("✓ No active water quality advisories at this time.")

# ── Advisory context ──────────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📖 What do advisory levels mean?"):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        **🔴 No Contact**
        The highest level advisory. Do not swim, kayak, paddle, or have any
        water contact near this location. Typically issued after a sewage spill
        or when enterococcus exceeds safe levels for multiple consecutive days.
        Signage is posted at all public access points.
        """)
    with col2:
        st.markdown("""
        **🟡 Caution**
        Water quality is elevated above baseline but below the official
        threshold for a No Contact advisory. Exercise caution, especially
        for those with open wounds, compromised immune systems, or children.
        """)
    with col3:
        st.markdown("""
        **🟢 Lifted**
        A previously active advisory has been lifted after enterococcus
        levels tested below 70 MPN/100mL on two consecutive days (per
        City of Miami Beach protocol). Normal recreational use may resume.
        """)

# ── Standard thresholds ───────────────────────────────────────────────────────

with st.expander("📏 Water quality standards used"):
    st.markdown("""
    | Classification | Enterococcus Level | Source |
    |---|---|---|
    | **Safe** | 0 – 35 MPN/100mL | EPA / FL DOH |
    | **Caution** | 36 – 70 MPN/100mL | EPA / FL DOH |
    | **Unsafe** | > 70 MPN/100mL | EPA / FL DOH (triggers advisory) |

    The Florida DOH and City of Miami Beach only issue official advisories based on results from
    **NELAP-certified laboratories** (National Environmental Laboratory Accreditation Program).
    Miami Waterkeeper provides independent TIER_2 data using QAPP methodology — values may
    be flagged sooner but are not used for official advisory decisions.
    """)

# ── Advisory history table ────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("### 📋 Full Advisory History")

all_for_table = query("""
    SELECT s.display_name AS site, a.advisory_type, a.issued_date,
           a.lifted_date, a.is_active, src.name AS source, a.veracity_tier,
           SUBSTR(a.description, 1, 120) AS description
    FROM advisories a
    JOIN sites s ON s.id = a.site_id
    JOIN sources src ON src.id = a.source_id
    WHERE a.advisory_type != 'UNKNOWN'
    ORDER BY a.collected_at DESC
    LIMIT 100
""")

if all_for_table:
    df = pd.DataFrame(all_for_table)
    df['is_active'] = df['is_active'].map({True: '● Active', 1: '● Active', False: 'Lifted', 0: 'Lifted'})
    df.columns = ['Site','Type','Issued','Lifted','Status','Source','Tier','Description']
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No advisory history yet. Run the data collector to populate.")
