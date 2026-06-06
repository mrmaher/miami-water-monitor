-- Miami Water Monitor – Supabase (PostgreSQL) Schema
-- Run this in the Supabase SQL Editor to initialize your database.
-- Safe to re-run: all statements use CREATE TABLE IF NOT EXISTS.

-- ─────────────────────────────────────────────────────────────
-- Reference tables
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sources (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    org           TEXT NOT NULL,
    veracity_tier TEXT NOT NULL CHECK (veracity_tier IN ('TIER_1','TIER_2','TIER_3')),
    base_url      TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sites (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    location_type TEXT NOT NULL CHECK (location_type IN ('OCEAN_BEACH','CANAL','INTRACOASTAL','BAYSIDE')),
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    address       TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- Collection audit
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS collection_runs (
    id                SERIAL PRIMARY KEY,
    source_id         INTEGER NOT NULL REFERENCES sources(id),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'RUNNING'
                      CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED')),
    records_added     INTEGER DEFAULT 0,
    error_msg         TEXT,
    collector_version TEXT
);

-- ─────────────────────────────────────────────────────────────
-- Core water quality readings
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS water_readings (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES collection_runs(id),
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    source_id       INTEGER NOT NULL REFERENCES sources(id),
    metric          TEXT NOT NULL,
    value           DOUBLE PRECISION,
    unit            TEXT,
    result_class    TEXT CHECK (result_class IN ('GOOD','MODERATE','POOR','ADVISORY','UNKNOWN')),
    threshold_safe  DOUBLE PRECISION,
    threshold_unit  TEXT,
    sample_date     DATE NOT NULL,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_url      TEXT,
    lab_certified   BOOLEAN DEFAULT FALSE,
    veracity_tier   TEXT NOT NULL,
    raw_payload     JSONB,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_readings_site_date    ON water_readings(site_id, sample_date DESC);
CREATE INDEX IF NOT EXISTS idx_readings_source_date  ON water_readings(source_id, sample_date DESC);
CREATE INDEX IF NOT EXISTS idx_readings_collected    ON water_readings(collected_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Active advisories
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS advisories (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES collection_runs(id),
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    source_id       INTEGER NOT NULL REFERENCES sources(id),
    advisory_type   TEXT NOT NULL CHECK (advisory_type IN ('NO_CONTACT','CAUTION','LIFTED','UNKNOWN')),
    description     TEXT,
    issued_date     DATE,
    lifted_date     DATE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_url      TEXT,
    veracity_tier   TEXT NOT NULL,
    raw_payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_advisories_site      ON advisories(site_id, is_active);
CREATE INDEX IF NOT EXISTS idx_advisories_collected ON advisories(collected_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Weather readings (ready for Phase 2 — Open-Meteo integration)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS weather_readings (
    id              SERIAL PRIMARY KEY,
    site_id         INTEGER REFERENCES sites(id),   -- NULL = Miami Beach general
    metric          TEXT NOT NULL,  -- TEMP_C | WIND_SPEED_KMH | PRECIPITATION_MM |
                                    -- WAVE_HEIGHT_M | UV_INDEX | VISIBILITY_KM
    value           DOUBLE PRECISION NOT NULL,
    unit            TEXT,
    observation_type TEXT NOT NULL  -- HISTORICAL | CURRENT | FORECAST
                    CHECK (observation_type IN ('HISTORICAL','CURRENT','FORECAST')),
    valid_time      TIMESTAMPTZ NOT NULL,   -- when this reading applies to
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          TEXT,           -- e.g. "Open-Meteo", "NOAA NWS"
    raw_payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_weather_metric_time ON weather_readings(metric, valid_time DESC);
CREATE INDEX IF NOT EXISTS idx_weather_type        ON weather_readings(observation_type, valid_time DESC);

-- ─────────────────────────────────────────────────────────────
-- Seed data: sources
-- ─────────────────────────────────────────────────────────────

INSERT INTO sources (name, org, veracity_tier, base_url, notes) VALUES
    ('DOH Healthy Beaches',
     'Florida Department of Health – Miami-Dade',
     'TIER_1',
     'https://miamidade.floridahealth.gov',
     'Weekly NELAP-certified enterococcus testing. Standard: 70 MPN/100mL.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO sources (name, org, veracity_tier, base_url, notes) VALUES
    ('MB Rising Above',
     'City of Miami Beach – Environment & Sustainability',
     'TIER_1',
     'https://www.mbrisingabove.com/climate-adaptation/biscayne-bay/water-quality/',
     'Monthly canal/bay sampling + active No-Contact advisory page. NELAP-certified.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO sources (name, org, veracity_tier, base_url, notes) VALUES
    ('Miami Waterkeeper',
     'Miami Waterkeeper (Biscayne Bay Waterkeeper)',
     'TIER_2',
     'https://www.miamiwaterkeeper.org/water_quality_monitoring',
     'Weekly independent enterococcus testing via Swim Guide. QAPP methodology.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO sources (name, org, veracity_tier, base_url, notes) VALUES
    ('Open-Meteo',
     'Open-Meteo (open-source weather API)',
     'TIER_2',
     'https://open-meteo.com',
     'Free weather API — historical, current, and forecast. No API key required.')
ON CONFLICT (name) DO NOTHING;

-- ─────────────────────────────────────────────────────────────
-- Seed data: sites
-- ─────────────────────────────────────────────────────────────

INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('south_pointe',      'South Pointe Park',           'OCEAN_BEACH',  25.7648, -80.1329, 'South Pointe Dr, Miami Beach, FL',      'DOH weekly sampling site')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('collins_21st',      'Collins Park (21st St)',       'OCEAN_BEACH',  25.7868, -80.1295, '21st St & Collins Ave, Miami Beach, FL','DOH weekly sampling site')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('53rd_street',       '53rd Street Beach',            'OCEAN_BEACH',  25.8142, -80.1225, '53rd St, Miami Beach, FL',              'DOH weekly sampling site')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('north_shore_73rd',  'North Shore (73rd St)',         'OCEAN_BEACH',  25.8371, -80.1192, '73rd St, Miami Beach, FL',              'DOH weekly sampling site')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('79th_street',       '79th Street Beach',            'OCEAN_BEACH',  25.8537, -80.1186, '79th St, Miami Beach, FL',              'DOH weekly sampling site')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('purdy_ave_bayside', 'Purdy Ave Boat Ramp (Bayside)', 'BAYSIDE',     25.7930, -80.1460, '1800 Purdy Ave, Miami Beach, FL',       'DOH weekly bayside sampling site')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('park_view_canal',   'Park View Island Park Canal',  'CANAL',        25.8100, -80.1450, 'Park View Island Park, Miami Beach, FL','Active No-Contact advisory')
ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name, display_name, location_type, latitude, longitude, address, notes) VALUES
    ('biscayne_bay_mb',   'Biscayne Bay (Miami Beach)',   'INTRACOASTAL', 25.7900, -80.1500, 'Biscayne Bay adjacent to Miami Beach',  'City monthly stormwater bay sampling')
ON CONFLICT (name) DO NOTHING;
