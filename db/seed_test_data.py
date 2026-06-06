#!/usr/bin/env python3
"""
Seed 90 days of realistic synthetic water quality data.
Simulates real-world Miami Beach patterns:
  - Ocean beaches: mostly safe (10-40 MPN) with post-rain spikes
  - Park View Canal: chronically elevated (50-300 MPN), current advisory
  - Waterkeeper adds supplementary readings ~weekly
  - Rainy season (June-Oct) produces more spikes

Run: python db/seed_test_data.py
"""
import os, sys, json, random, sqlite3
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.init_db import init_db, DB_PATH

random.seed(42)

# ── Synthetic rain events (boost bacteria 2-7 days after) ─────────────────
RAIN_EVENTS = [
    # (start_day_offset_from_today, duration_days)
    (-85, 2), (-71, 3), (-58, 1), (-44, 4), (-31, 2), (-21, 3), (-10, 2), (-3, 1)
]

def is_post_rain(day_offset: int) -> float:
    """Return multiplier for post-rain bacteria spike."""
    mult = 1.0
    for start, dur in RAIN_EVENTS:
        if start <= day_offset <= start + dur + 3:
            lag = day_offset - start
            mult = max(mult, 1.0 + 4.0 * max(0, 1 - lag/5.0))
    return mult

# Site profiles: (base_mean, base_std, seasonal_amp)
SITE_PROFILES = {
    "south_pointe":      dict(mean=18, std=12, floor=2,  post_rain_cap=180),
    "collins_21st":      dict(mean=15, std=10, floor=2,  post_rain_cap=150),
    "53rd_street":       dict(mean=22, std=15, floor=2,  post_rain_cap=200),
    "north_shore_73rd":  dict(mean=20, std=13, floor=2,  post_rain_cap=160),
    "79th_street":       dict(mean=25, std=18, floor=3,  post_rain_cap=220),
    "purdy_ave_bayside": dict(mean=45, std=30, floor=5,  post_rain_cap=400),
    "park_view_canal":   dict(mean=180,std=90, floor=40, post_rain_cap=2000),
    "biscayne_bay_mb":   dict(mean=40, std=25, floor=5,  post_rain_cap=350),
}

def gen_value(site_name: str, day_offset: int) -> float:
    p = SITE_PROFILES[site_name]
    mult = is_post_rain(day_offset)
    raw = random.gauss(p['mean'] * mult, p['std'] * mult)
    raw = max(p['floor'], min(p.get('post_rain_cap', 500), raw))
    return round(raw, 1)

def classify(v: float) -> str:
    if v <= 35: return "GOOD"
    if v <= 70: return "MODERATE"
    return "POOR"


def seed(db_path: str = DB_PATH):
    conn = init_db(db_path)

    today = datetime.now(timezone.utc).date()
    source_rows = {r['name']: r['id'] for r in conn.execute("SELECT id, name FROM sources").fetchall()}
    site_rows   = {r['name']: r['id'] for r in conn.execute("SELECT id, name FROM sites").fetchall()}

    # ── Create one collection run per source for seeding ─────────────────
    def make_run(source_id: int) -> int:
        cur = conn.execute(
            "INSERT INTO collection_runs (source_id, started_at, completed_at, status, records_added, collector_version) "
            "VALUES (?, ?, ?, 'SUCCESS', 0, 'seed')",
            (source_id, '2026-06-06T00:00:00Z', '2026-06-06T00:01:00Z')
        )
        return cur.lastrowid

    doh_run_id = make_run(source_rows['DOH Healthy Beaches'])
    mb_run_id  = make_run(source_rows['MB Rising Above'])
    wk_run_id  = make_run(source_rows['Miami Waterkeeper'])

    doh_sites = ["south_pointe","collins_21st","53rd_street","north_shore_73rd","79th_street","purdy_ave_bayside"]
    mb_sites  = ["park_view_canal","biscayne_bay_mb"]
    wk_sites  = ["south_pointe","collins_21st","53rd_street","north_shore_73rd","park_view_canal"]

    total = 0

    # ── DOH: weekly readings for ocean beaches (Mondays) ─────────────────
    for day_offset in range(-90, 1):
        date = today + timedelta(days=day_offset)
        if date.weekday() != 0:  # Monday only
            continue
        date_str = date.isoformat()
        for site in doh_sites:
            val = gen_value(site, day_offset)
            conn.execute("""INSERT INTO water_readings
                (run_id,site_id,source_id,metric,value,unit,result_class,
                 threshold_safe,threshold_unit,sample_date,collected_at,
                 source_url,lab_certified,veracity_tier,raw_payload,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doh_run_id, site_rows[site], source_rows['DOH Healthy Beaches'],
                 'ENTEROCOCCUS', val, 'MPN/100mL', classify(val),
                 70.0, 'MPN/100mL', date_str, '2026-06-06T00:00:00Z',
                 'https://miamidade.floridahealth.gov', 1, 'TIER_1',
                 json.dumps({"site": site, "value": val, "synthetic": True}),
                 'Synthetic seed data – DOH weekly'))
            total += 1

    # ── MB Rising Above: monthly canal readings ───────────────────────────
    for day_offset in range(-90, 1):
        date = today + timedelta(days=day_offset)
        if date.day != 1:  # 1st of month only
            continue
        date_str = date.isoformat()
        for site in mb_sites:
            val = gen_value(site, day_offset)
            conn.execute("""INSERT INTO water_readings
                (run_id,site_id,source_id,metric,value,unit,result_class,
                 threshold_safe,threshold_unit,sample_date,collected_at,
                 source_url,lab_certified,veracity_tier,raw_payload,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mb_run_id, site_rows[site], source_rows['MB Rising Above'],
                 'ENTEROCOCCUS', val, 'MPN/100mL', classify(val),
                 70.0, 'MPN/100mL', date_str, '2026-06-06T00:00:00Z',
                 'https://www.mbrisingabove.com/climate-adaptation/biscayne-bay/water-quality/', 1, 'TIER_1',
                 json.dumps({"site": site, "value": val, "synthetic": True}),
                 'Synthetic seed data – MB monthly'))
            total += 1

    # ── Miami Waterkeeper: weekly (Thursdays) ─────────────────────────────
    for day_offset in range(-90, 1):
        date = today + timedelta(days=day_offset)
        if date.weekday() != 3:  # Thursday only
            continue
        date_str = date.isoformat()
        for site in wk_sites:
            val = gen_value(site, day_offset)
            # Waterkeeper tends to read slightly higher (different sampling spot, no dilution bias)
            val = round(min(val * random.uniform(0.9, 1.3), SITE_PROFILES[site]['post_rain_cap']), 1)
            conn.execute("""INSERT INTO water_readings
                (run_id,site_id,source_id,metric,value,unit,result_class,
                 threshold_safe,threshold_unit,sample_date,collected_at,
                 source_url,lab_certified,veracity_tier,raw_payload,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (wk_run_id, site_rows[site], source_rows['Miami Waterkeeper'],
                 'ENTEROCOCCUS', val, 'CFU/100mL', classify(val),
                 70.0, 'CFU/100mL', date_str, '2026-06-06T00:00:00Z',
                 'https://www.miamiwaterkeeper.org/water_quality_monitoring', 0, 'TIER_2',
                 json.dumps({"site": site, "value": val, "synthetic": True}),
                 'Synthetic seed data – Waterkeeper weekly'))
            total += 1

    # ── Park View Canal – active NO_CONTACT advisory ──────────────────────
    conn.execute("""INSERT INTO advisories
        (run_id,site_id,source_id,advisory_type,description,issued_date,
         lifted_date,is_active,collected_at,source_url,veracity_tier,raw_payload)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mb_run_id, site_rows['park_view_canal'], source_rows['MB Rising Above'],
         'NO_CONTACT',
         'The city has issued a "No Contact" advisory for the waters near Park View Island Park. '
         'The advisory recommends not swimming or engaging in recreational water activities '
         'near this location until the advisory is lifted. Signage has been posted.',
         '2026-02-25', None, 1, '2026-06-06T00:00:00Z',
         'https://www.mbrisingabove.com/climate-adaptation/biscayne-bay/water-quality/',
         'TIER_1',
         json.dumps({"source": "MB Rising Above", "page_updated": "2026-02-25"})))

    # Update run record counts
    conn.execute("UPDATE collection_runs SET records_added=? WHERE id=?",
                 (sum(1 for _ in conn.execute("SELECT 1 FROM water_readings WHERE run_id=?", (doh_run_id,))),
                  doh_run_id))
    conn.execute("UPDATE collection_runs SET records_added=? WHERE id=?",
                 (sum(1 for _ in conn.execute("SELECT 1 FROM water_readings WHERE run_id=?", (mb_run_id,))),
                  mb_run_id))
    conn.execute("UPDATE collection_runs SET records_added=? WHERE id=?",
                 (sum(1 for _ in conn.execute("SELECT 1 FROM water_readings WHERE run_id=?", (wk_run_id,))),
                  wk_run_id))

    conn.commit()
    conn.close()

    print(f"✓ Seeded {total} readings across 3 sources / 8 sites / 90 days")
    print(f"  + 1 active NO_CONTACT advisory for Park View Canal")
    print(f"  DB: {db_path}")


if __name__ == '__main__':
    db_arg = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    seed(db_arg)
