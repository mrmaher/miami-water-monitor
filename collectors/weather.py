"""
Weather Collector — Phase 2 (Open-Meteo)
─────────────────────────────────────────
Source:  Open-Meteo (https://open-meteo.com) — free, no API key required
Tier:    TIER_2
Covers:  Miami Beach coordinates (25.7899°N, 80.1300°W)

Metrics collected:
  HISTORICAL  → last 7 days of actuals
  CURRENT     → present conditions
  FORECAST    → next 7 days

Variables tracked:
  temperature_2m          °C
  precipitation           mm
  windspeed_10m           km/h
  winddirection_10m       °
  weathercode             WMO code
  uv_index                dimensionless
  visibility              m → stored as km
  wave_height             m  (Marine API)
  wave_period             s  (Marine API)

Status: ACTIVE — integrated into collection pipeline.

DB table: weather_readings (created in schema_postgres.sql / schema.sql)
"""

import json
import requests
from datetime import datetime, timezone, timedelta
from db.connection import execute, commit, query_one, IS_POSTGRES, utcnow if False else None

try:
    from collectors.base import utcnow
except ImportError:
    from datetime import datetime, timezone
    def utcnow(): return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

SOURCE_NAME = "Open-Meteo"

MIAMI_BEACH_LAT = 25.7899
MIAMI_BEACH_LON = -80.1300

WEATHER_API   = "https://api.open-meteo.com/v1/forecast"
MARINE_API    = "https://marine-api.open-meteo.com/v1/marine"
HEADERS       = {"User-Agent": "MiamiWaterMonitor/2.0 (research)"}


def _source_id() -> int:
    row = query_one("SELECT id FROM sources WHERE name = ?", (SOURCE_NAME,))
    if not row:
        raise ValueError(f"Source '{SOURCE_NAME}' not seeded.")
    return row['id']


def _insert_weather(run_id: int, site_id: int | None, metric: str, value: float,
                    unit: str, obs_type: str, valid_time: str,
                    source: str = "Open-Meteo", raw: dict = None) -> None:
    payload = json.dumps(raw) if raw and not IS_POSTGRES else raw
    if IS_POSTGRES:
        execute(
            """INSERT INTO weather_readings
               (site_id,metric,value,unit,observation_type,valid_time,collected_at,source,raw_payload)
               VALUES (?,?,?,?,?,?,NOW(),?,?)""",
            (site_id, metric, value, unit, obs_type, valid_time, source, payload)
        )
    else:
        execute(
            """INSERT INTO weather_readings
               (site_id,metric,value,unit,observation_type,valid_time,collected_at,source,raw_payload)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (site_id, metric, value, unit, obs_type, valid_time, utcnow(), source, json.dumps(raw) if raw else None)
        )


class WeatherCollector:
    source_name = SOURCE_NAME

    def __init__(self):
        self.run_id = None
        self.records_added = 0

    def run(self) -> dict:
        import traceback
        src_id = _source_id()
        if IS_POSTGRES:
            from db.connection import query_one as qo
            row = qo(
                "INSERT INTO collection_runs (source_id, started_at, status, collector_version) "
                "VALUES (?, NOW(), 'RUNNING', '2.0.0') RETURNING id", (src_id,)
            )
            self.run_id = row['id']
        else:
            from db.connection import execute as ex
            self.run_id = ex(
                "INSERT INTO collection_runs (source_id, started_at, status, collector_version) "
                "VALUES (?, ?, 'RUNNING', '2.0.0')", (src_id, utcnow())
            )
        commit()

        try:
            self._collect_weather()
            self._collect_marine()
            commit()
            if IS_POSTGRES:
                execute("UPDATE collection_runs SET completed_at=NOW(), status='SUCCESS', records_added=? WHERE id=?",
                        (self.records_added, self.run_id))
            else:
                execute("UPDATE collection_runs SET completed_at=?, status='SUCCESS', records_added=? WHERE id=?",
                        (utcnow(), self.records_added, self.run_id))
            commit()
        except Exception as e:
            from db.connection import rollback as rb
            rb()
            execute("UPDATE collection_runs SET status='FAILED', error_msg=? WHERE id=?",
                    (str(e)[:500], self.run_id))
            commit()
            return {'source': SOURCE_NAME, 'status': 'FAILED', 'records': 0, 'error': str(e)}

        return {'source': SOURCE_NAME, 'status': 'SUCCESS', 'records': self.records_added}

    def _collect_weather(self):
        today = datetime.now(timezone.utc).date()
        past  = today - timedelta(days=7)
        future = today + timedelta(days=7)

        params = {
            "latitude":   MIAMI_BEACH_LAT,
            "longitude":  MIAMI_BEACH_LON,
            "hourly":     "temperature_2m,precipitation,windspeed_10m,winddirection_10m,weathercode,uv_index,visibility",
            "current":    "temperature_2m,precipitation,windspeed_10m,winddirection_10m,weathercode,uv_index",
            "start_date": past.isoformat(),
            "end_date":   future.isoformat(),
            "timezone":   "America/New_York",
        }
        resp = requests.get(WEATHER_API, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Current conditions
        current = data.get("current", {})
        now_str = current.get("time", utcnow())
        metric_map = {
            "temperature_2m":    ("TEMP_C",          "°C"),
            "precipitation":     ("PRECIPITATION_MM", "mm"),
            "windspeed_10m":     ("WIND_SPEED_KMH",  "km/h"),
            "winddirection_10m": ("WIND_DIR_DEG",    "°"),
            "uv_index":          ("UV_INDEX",         ""),
        }
        for key, (metric, unit) in metric_map.items():
            val = current.get(key)
            if val is not None:
                _insert_weather(self.run_id, None, metric, float(val), unit,
                                "CURRENT", now_str, raw={"key": key, "raw": current})
                self.records_added += 1

        # Hourly historical + forecast
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        today_str = today.isoformat()

        for i, t in enumerate(times):
            obs_type = "HISTORICAL" if t[:10] < today_str else "FORECAST"
            for key, (metric, unit) in metric_map.items():
                vals = hourly.get(key, [])
                if i < len(vals) and vals[i] is not None:
                    _insert_weather(self.run_id, None, metric, float(vals[i]), unit,
                                    obs_type, t + ":00Z", raw=None)
                    self.records_added += 1

            # Visibility stored in km
            vis_list = hourly.get("visibility", [])
            if i < len(vis_list) and vis_list[i] is not None:
                _insert_weather(self.run_id, None, "VISIBILITY_KM",
                                round(float(vis_list[i]) / 1000, 2), "km",
                                obs_type, t + ":00Z", raw=None)
                self.records_added += 1

    def _collect_marine(self):
        today  = datetime.now(timezone.utc).date()
        past   = today - timedelta(days=7)
        future = today + timedelta(days=7)

        params = {
            "latitude":   MIAMI_BEACH_LAT,
            "longitude":  MIAMI_BEACH_LON,
            "hourly":     "wave_height,wave_period,wave_direction",
            "start_date": past.isoformat(),
            "end_date":   future.isoformat(),
            "timezone":   "America/New_York",
        }
        try:
            resp = requests.get(MARINE_API, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return  # Marine API failure is non-fatal

        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        today_str = today.isoformat()
        wave_metrics = {
            "wave_height":    ("WAVE_HEIGHT_M",  "m"),
            "wave_period":    ("WAVE_PERIOD_S",  "s"),
            "wave_direction": ("WAVE_DIR_DEG",   "°"),
        }
        for i, t in enumerate(times):
            obs_type = "HISTORICAL" if t[:10] < today_str else "FORECAST"
            for key, (metric, unit) in wave_metrics.items():
                vals = hourly.get(key, [])
                if i < len(vals) and vals[i] is not None:
                    _insert_weather(self.run_id, None, metric, float(vals[i]), unit,
                                    obs_type, t + ":00Z", raw=None)
                    self.records_added += 1


if __name__ == "__main__":
    result = WeatherCollector().run()
    print(result)
