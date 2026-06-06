# 🌊 Miami Water Monitor

Real-time beach and waterway safety dashboard for Miami Beach, FL.
Tracks enterococcus bacteria levels across ocean beaches, canals, and intracoastal waterways
from three independent data sources to inform open-water swimmers and beachgoers.

**Live app:** `https://miami-water-monitor.streamlit.app` *(after deployment)*

---

## Architecture

```
Data Sources (3)          Collectors (Python)      Database          Dashboard
─────────────────         ───────────────────      ─────────         ─────────
FL DOH Healthy Beaches ──► doh_beaches.py    ──┐
MB Rising Above        ──► mb_rising_above.py──┼──► Supabase    ──► Streamlit
Miami Waterkeeper      ──► waterkeeper.py    ──┘   (Postgres)       Cloud
Open-Meteo (Phase 2)   ──► weather.py        ──┘

Schedule: GitHub Actions cron → 7am ET daily → writes to Supabase
```

| Layer | Technology | Why |
|---|---|---|
| Dashboard | Streamlit Community Cloud | Free, permanent public URL, auto-deploys from GitHub |
| Database | Supabase (Postgres) | Free, persistent, 500MB, inspectable via web UI |
| Collection | GitHub Actions (cron) | Free, cloud-hosted, runs without your laptop |
| Local dev | SQLite | Zero config, same codebase, no credentials needed |

---

## One-time Setup (30 minutes)

### Step 1 — GitHub repository

1. Go to [github.com](https://github.com) → **New repository**
2. Name it exactly: `miami-water-monitor`
3. Set visibility: **Public** (required for free Streamlit Community Cloud)
4. Do **not** initialize with README (you have one)
5. Push this project folder:

```bash
cd "/Users/maher/Documents/Claude/Projects/Miami Water Monitor"
git init
git add .
git commit -m "Initial commit — Miami Water Monitor"
git remote add origin https://github.com/YOUR_USERNAME/miami-water-monitor.git
git push -u origin main
```

---

### Step 2 — Supabase database

1. Go to [supabase.com](https://supabase.com) → **New project**
   - Name: `miami-water-monitor`
   - Region: `us-east-1` (closest to Miami)
   - Save your database password somewhere safe

2. Once the project is ready, go to **SQL Editor** → paste the entire contents of
   `db/schema_postgres.sql` → click **Run**
   *(This creates all tables and seeds the initial sites/sources data)*

3. Get your connection string:
   **Settings → Database → Connection string → URI** → copy it

   It looks like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.[REF].supabase.co:5432/postgres
   ```

---

### Step 3 — Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → **Sign in with GitHub**
2. Click **New app**
3. Repository: `YOUR_USERNAME/miami-water-monitor`
4. Branch: `main`
5. Main file path: `app.py`
6. App URL: `miami-water-monitor` (or customize)
7. Click **Advanced settings** → **Secrets** → paste:

```toml
DATABASE_URL = "postgresql://postgres:[YOUR-PASSWORD]@db.[REF].supabase.co:5432/postgres"
```

8. Click **Deploy** — your app will be live at `https://miami-water-monitor.streamlit.app`

---

### Step 4 — GitHub Actions (daily collection)

1. Go to your GitHub repo → **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
   - Name: `DATABASE_URL`
   - Value: *(paste the same Postgres URI from Step 2)*
3. Go to **Actions tab** → find **Daily Water Quality Collection** → click **Run workflow**

   This triggers the first manual run. After that, it runs automatically every morning at 7am ET.

---

### Step 5 — Load test data (optional, for immediate demo)

Before live data starts flowing, populate 90 days of realistic synthetic data:

```bash
cd "/Users/maher/Documents/Claude/Projects/Miami Water Monitor"
pip install -r requirements.txt

# Set your Supabase URL for local scripts
export DATABASE_URL="postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres"

python db/seed_test_data.py
```

---

## Local development

No credentials needed — uses SQLite automatically:

```bash
cd "/Users/maher/Documents/Claude/Projects/Miami Water Monitor"
pip install -r requirements.txt
python db/init_db.py          # initialize local SQLite DB
python db/seed_test_data.py   # optional: load 90 days of test data
streamlit run app.py          # open http://localhost:8501
```

To run collectors locally against the live Supabase DB:
```bash
export DATABASE_URL="postgresql://..."
python run_collection.py
```

---

## Project structure

```
miami-water-monitor/
  app.py                          # 🏠 Home dashboard (Streamlit)
  run_collection.py               # Orchestrator — runs all collectors
  requirements.txt

  pages/
    1_📊_Trends.py                # Per-site trend analysis (Plotly charts)
    2_⚠️_Advisories.py           # Advisory log and detail
    3_🔬_Sources.py               # Data provenance + collection log

  collectors/
    base.py                       # Shared audit logic (works SQLite + Postgres)
    doh_beaches.py                # FL DOH Healthy Beaches (TIER_1)
    mb_rising_above.py            # MB Rising Above advisories (TIER_1)
    waterkeeper.py                # Miami Waterkeeper / Swim Guide (TIER_2)
    weather.py                    # Open-Meteo weather (Phase 2)

  db/
    connection.py                 # Smart adapter: Postgres prod / SQLite local
    schema_postgres.sql           # Supabase schema — run once in SQL Editor
    schema.sql                    # SQLite schema (local dev)
    init_db.py                    # Local DB initializer
    seed_test_data.py             # 90-day synthetic data seeder

  .streamlit/
    config.toml                   # Dark ocean theme
    secrets.toml.example          # Template — copy to secrets.toml locally

  .github/
    workflows/
      collect.yml                 # GitHub Actions daily cron (7am ET)

  .gitignore                      # Excludes secrets.toml and *.db files
```

---

## Data sources

| Source | Tier | Frequency | Sites | Certification |
|---|---|---|---|---|
| FL DOH Healthy Beaches | TIER_1 | Weekly (Mondays) | 6 ocean + bayside | NELAP-certified |
| MB Rising Above | TIER_1 | Monthly + advisories | Canal + Bay | NELAP-certified |
| Miami Waterkeeper | TIER_2 | Weekly (Thursdays) | 5 sites | QAPP methodology |
| Open-Meteo *(Phase 2)* | TIER_2 | Daily | Miami Beach | Open-source API |

**Safety standard:** 70 MPN/100mL enterococcus (EPA / FL DOH threshold for marine water)

---

## Roadmap

- [x] Water quality data collection (3 sources)
- [x] Active advisory tracking
- [x] Streamlit dashboard with trend analysis
- [x] Supabase production database
- [x] GitHub Actions daily collection
- [ ] **Phase 2:** Weather integration (Open-Meteo) — table already provisioned
- [ ] **Phase 3:** Email / SMS alerts for new advisories
- [ ] **Phase 4:** Historical correlation — rain events vs. bacteria spikes
- [ ] **Phase 5:** Miami Waterkeeper API (if access granted)

---

*Not a substitute for official health advisories. Always check FL DOH and City of Miami Beach
official channels before entering the water. Data may be delayed 24-48 hours.*
