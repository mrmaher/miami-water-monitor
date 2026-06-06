-- Miami Water Monitor Database Schema
-- All timestamps stored as ISO-8601 UTC strings

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─────────────────────────────────────────────
-- Reference tables
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,          -- e.g. "DOH Healthy Beaches"
    org           TEXT NOT NULL,                 -- e.g. "Florida Dept of Health"
    veracity_tier TEXT NOT NULL,                 -- TIER_1 | TIER_2 | TIER_3
    -- TIER_1 = NELAP-certified lab results
    -- TIER_2 = Independent certified (Waterkeeper QAPP methods)
    -- TIER_3 = Scraped advisories / press / citizen reports
    base_url      TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS sites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    location_type TEXT NOT NULL,  -- OCEAN_BEACH | CANAL | INTRACOASTAL | BAYSIDE
    latitude      REAL,
    longitude     REAL,
    address       TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sites_name ON sites(name);

-- ─────────────────────────────────────────────
-- Collection audit
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS collection_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES sources(id),
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'RUNNING',  -- RUNNING | SUCCESS | PARTIAL | FAILED
    records_added   INTEGER DEFAULT 0,
    error_msg       TEXT,
    collector_version TEXT
);

-- ─────────────────────────────────────────────
-- Core water quality readings
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS water_readings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES collection_runs(id),
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    source_id       INTEGER NOT NULL REFERENCES sources(id),

    -- What was measured
    metric          TEXT NOT NULL,    -- ENTEROCOCCUS | FECAL_COLIFORM | TURBIDITY | TEMPERATURE | NUTRIENTS
    value           REAL,             -- NULL if advisory-only record
    unit            TEXT,             -- MPN/100mL | CFU/100mL | NTU | C | mg/L
    result_class    TEXT,             -- GOOD | MODERATE | POOR | ADVISORY | UNKNOWN

    -- Thresholds used (stored for auditability; standards can change)
    threshold_safe  REAL,             -- e.g. 70 for enterococcus
    threshold_unit  TEXT,

    -- Temporal tagging
    sample_date     TEXT NOT NULL,    -- ISO date the sample was taken (or advisory issued)
    collected_at    TEXT NOT NULL,    -- ISO datetime this record was fetched by us

    -- Provenance
    source_url      TEXT,
    lab_certified   INTEGER DEFAULT 0, -- 1 if NELAP-certified lab result
    veracity_tier   TEXT NOT NULL,     -- mirrors sources.veracity_tier at time of collection

    -- Full raw payload for auditability
    raw_payload     TEXT,             -- JSON string of source data
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_readings_site_date ON water_readings(site_id, sample_date);
CREATE INDEX IF NOT EXISTS idx_readings_source_date ON water_readings(source_id, sample_date);
CREATE INDEX IF NOT EXISTS idx_readings_collected ON water_readings(collected_at);

-- ─────────────────────────────────────────────
-- Active advisories (separate table for fast querying)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS advisories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES collection_runs(id),
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    source_id       INTEGER NOT NULL REFERENCES sources(id),

    advisory_type   TEXT NOT NULL,  -- NO_CONTACT | CAUTION | LIFTED | UNKNOWN
    description     TEXT,
    issued_date     TEXT,           -- ISO date advisory was issued (if known)
    lifted_date     TEXT,           -- ISO date advisory was lifted (NULL = still active)
    is_active       INTEGER NOT NULL DEFAULT 1,

    collected_at    TEXT NOT NULL,
    source_url      TEXT,
    veracity_tier   TEXT NOT NULL,
    raw_payload     TEXT
);

CREATE INDEX IF NOT EXISTS idx_advisories_site ON advisories(site_id, is_active);
CREATE INDEX IF NOT EXISTS idx_advisories_collected ON advisories(collected_at);

-- ─────────────────────────────────────────────
-- Seed data: sources
-- ─────────────────────────────────────────────

INSERT OR IGNORE INTO sources (name, org, veracity_tier, base_url, notes) VALUES
    ('DOH Healthy Beaches',
     'Florida Department of Health – Miami-Dade',
     'TIER_1',
     'https://miamidade.floridahealth.gov',
     'Weekly NELAP-certified enterococcus testing at ocean beach sites. Standard: 70 MPN/100mL.'),

    ('MB Rising Above',
     'City of Miami Beach – Environment & Sustainability',
     'TIER_1',
     'https://www.mbrisingabove.com/climate-adaptation/biscayne-bay/water-quality/',
     'Monthly canal/bay sampling + active No-Contact advisory page. NELAP-certified.'),

    ('Miami Waterkeeper',
     'Miami Waterkeeper (Biscayne Bay Waterkeeper)',
     'TIER_2',
     'https://www.miamiwaterkeeper.org/water_quality_monitoring',
     'Weekly independent citizen-science enterococcus testing via Swim Guide. QAPP methodology.');

-- ─────────────────────────────────────────────
-- Seed data: sites
-- ─────────────────────────────────────────────

INSERT OR IGNORE INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    -- DOH Healthy Beaches ocean sites
    ('south_pointe',      'South Pointe Park',          'OCEAN_BEACH',    25.7648, -80.1329, 'South Pointe Dr, Miami Beach, FL', 'DOH weekly sampling site'),
    ('collins_21st',      'Collins Park (21st St)',      'OCEAN_BEACH',    25.7868, -80.1295, '21st St & Collins Ave, Miami Beach, FL', 'DOH weekly sampling site'),
    ('53rd_street',       '53rd Street Beach',           'OCEAN_BEACH',    25.8142, -80.1225, '53rd St, Miami Beach, FL', 'DOH weekly sampling site'),
    ('north_shore_73rd',  'North Shore (73rd St)',        'OCEAN_BEACH',    25.8371, -80.1192, '73rd St, Miami Beach, FL', 'DOH weekly sampling site'),
    ('79th_street',       '79th Street Beach',           'OCEAN_BEACH',    25.8537, -80.1186, '79th St, Miami Beach, FL', 'DOH weekly sampling site'),
    ('purdy_ave_bayside', 'Purdy Ave Boat Ramp (Bayside)','BAYSIDE',       25.7930, -80.1460, '1800 Purdy Ave, Miami Beach, FL', 'DOH weekly bayside sampling site'),
    -- MB Rising Above canal/advisory sites
    ('park_view_canal',   'Park View Island Park Canal', 'CANAL',          25.8100, -80.1450, 'Park View Island Park, Miami Beach, FL', 'Active No-Contact advisory as of 2026-02-25'),
    -- General bay sampling
    ('biscayne_bay_mb',   'Biscayne Bay (Miami Beach)',  'INTRACOASTAL',   25.7900, -80.1500, 'Biscayne Bay adjacent to Miami Beach', 'City monthly stormwater bay sampling network');
