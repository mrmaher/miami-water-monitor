"""
Miami Waterkeeper Collector
Source: Miami Waterkeeper / Swim Guide
Tier:   TIER_2 (independent certified testing, QAPP methodology)
Sites:  All MB-adjacent sites in Swim Guide database
Method: Swim Guide public API (theswimguide.org) → filter to Miami Beach
        Falls back to scraping the Waterkeeper water quality data page.

Miami Waterkeeper tests weekly; standard matches EPA/DOH: 70 CFU/MPN per 100mL.
"""
import re
import json
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from .base import BaseCollector, utcnow

SOURCE_NAME = "Miami Waterkeeper"

# Swim Guide public API – Miami Beach area (lat/lon center + 25km radius)
SWIM_GUIDE_API = "https://www.theswimguide.org/api/v3/beaches"
MIAMI_BEACH_LAT = 25.7899
MIAMI_BEACH_LON = -80.1300
RADIUS_KM       = 25

WATERKEEPER_DATA_URL = "https://www.miamiwaterkeeper.org/miami_water_quality_data"
WATERKEEPER_MAP_URL  = "https://www.miamiwaterkeeper.org/water_quality_map"

HEADERS = {
    "User-Agent": "MiamiWaterMonitor/1.0 (research)",
    "Accept":     "application/json, text/html",
}

# Swim Guide status → our classification
STATUS_MAP = {
    "safe":           "GOOD",
    "unsafe":         "POOR",
    "caution":        "MODERATE",
    "unknown":        "UNKNOWN",
    "data_not_shown": "UNKNOWN",
}

THRESHOLD_SAFE = 70.0
METRIC         = "ENTEROCOCCUS"
UNIT           = "CFU/100mL"

# Miami Beach geographic bounding box (rough)
LAT_MIN, LAT_MAX = 25.75, 25.87
LON_MIN, LON_MAX = -80.16, -80.10

# Map Swim Guide beach names to our DB site keys where possible
SWIM_GUIDE_SITE_MAP = {
    "South Pointe":   "south_pointe",
    "21st":           "collins_21st",
    "Collins":        "collins_21st",
    "53rd":           "53rd_street",
    "73rd":           "north_shore_73rd",
    "North Shore":    "north_shore_73rd",
    "79th":           "79th_street",
    "Purdy":          "purdy_ave_bayside",
    "Park View":      "park_view_canal",
    "Biscayne":       "biscayne_bay_mb",
}


def _match_site(name: str) -> str:
    for key, db_key in SWIM_GUIDE_SITE_MAP.items():
        if key.lower() in name.lower():
            return db_key
    # Default: if it's clearly a Miami Beach ocean beach, use south_pointe as proxy
    if any(w in name.lower() for w in ["miami beach", "beach", "ocean"]):
        return "south_pointe"
    return "biscayne_bay_mb"


def _classify(value: float | None, status: str | None) -> str:
    if value is not None:
        if value <= 35:  return "GOOD"
        if value <= 70:  return "MODERATE"
        return "POOR"
    return STATUS_MAP.get((status or "").lower(), "UNKNOWN")


class WaterkeeperCollector(BaseCollector):
    source_name = SOURCE_NAME

    def collect(self):
        collected = self._try_swim_guide_api()
        if not collected:
            self._try_waterkeeper_page()

    # ── Strategy 1: Swim Guide API ────────────────────────────

    def _try_swim_guide_api(self) -> bool:
        params = {
            "latitude":  MIAMI_BEACH_LAT,
            "longitude": MIAMI_BEACH_LON,
            "radius":    RADIUS_KM,
            "lang":      "en",
        }
        try:
            resp = requests.get(SWIM_GUIDE_API, params=params,
                                headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                return False
            beaches = resp.json()
            if not isinstance(beaches, list) or not beaches:
                # Try alternate response shape
                data = beaches if isinstance(beaches, dict) else {}
                beaches = data.get("beaches") or data.get("results") or []
        except Exception:
            return False

        if not beaches:
            return False

        today = utcnow()[:10]
        for beach in beaches:
            # Filter to Miami Beach geography
            lat = beach.get("latitude") or beach.get("lat") or 0
            lon = beach.get("longitude") or beach.get("lon") or beach.get("lng") or 0
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                continue

            name = beach.get("name") or beach.get("beachName") or ""
            site_key = _match_site(name)

            # Latest sample
            sample = beach.get("latestSample") or beach.get("mostRecentSample") or {}
            value_raw = sample.get("result") or sample.get("value") or beach.get("latestResult")
            try:
                value = float(value_raw) if value_raw is not None else None
            except (TypeError, ValueError):
                value = None

            status = (sample.get("status") or beach.get("swimmable") or
                      beach.get("status") or "unknown")
            sample_date = (sample.get("collectedDate") or sample.get("date") or
                           beach.get("lastSampleDate") or today)
            # Normalize date
            if isinstance(sample_date, (int, float)):
                sample_date = datetime.fromtimestamp(
                    sample_date / 1000, tz=timezone.utc
                ).strftime('%Y-%m-%d')

            result_class = _classify(value, str(status))

            self._insert_reading(
                site_name=site_key,
                metric=METRIC,
                value=value,
                unit=UNIT,
                result_class=result_class,
                sample_date=str(sample_date)[:10],
                threshold_safe=THRESHOLD_SAFE,
                threshold_unit=UNIT,
                source_url=SWIM_GUIDE_API,
                lab_certified=False,
                raw_payload={
                    "beach_id":  beach.get("id"),
                    "name":      name,
                    "latitude":  lat,
                    "longitude": lon,
                    "status":    status,
                    "sample":    sample,
                },
                notes="Swim Guide API – Miami Waterkeeper TIER_2 testing"
            )

        return self.records_added > 0

    # ── Strategy 2: Waterkeeper data page scrape ─────────────

    def _try_waterkeeper_page(self):
        today = utcnow()[:10]
        for url in [WATERKEEPER_DATA_URL, WATERKEEPER_MAP_URL]:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
            except Exception:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            full_text = soup.get_text(" ", strip=True)

            # Look for site name + numeric result pairs
            # Pattern: "<site name> ... <number> CFU/MPN/100mL"
            reading_pattern = re.compile(
                r'([A-Z][^.]*?(?:beach|park|street|pointe|shore|canal|bay)[^.]*?)'
                r'[:\-–]\s*(\d[\d,]*(?:\.\d+)?)\s*(?:CFU|MPN)?(?:/100\s*mL)?',
                re.IGNORECASE
            )
            for match in reading_pattern.finditer(full_text):
                site_text = match.group(1)
                try:
                    value = float(match.group(2).replace(",", ""))
                except ValueError:
                    continue
                if value > 500000:  # sanity check
                    continue
                site_key = _match_site(site_text)
                context = full_text[max(0, match.start()-100): match.end()+100]
                sample_date_str = self._extract_date_near(context) or today

                self._insert_reading(
                    site_name=site_key,
                    metric=METRIC,
                    value=value,
                    unit=UNIT,
                    result_class=_classify(value, None),
                    sample_date=sample_date_str,
                    threshold_safe=THRESHOLD_SAFE,
                    threshold_unit=UNIT,
                    source_url=url,
                    lab_certified=False,
                    raw_payload={"match": match.group(0), "context": context},
                    notes="Scraped from Miami Waterkeeper data page"
                )

            # Also look for safety status language
            status_pattern = re.compile(
                r'(south\s+pointe|21st|53rd|73rd|79th|north\s+shore|park\s+view|biscayne)'
                r'[^.]*?(safe|unsafe|caution|no.?swim|advisory)',
                re.IGNORECASE
            )
            for match in status_pattern.finditer(full_text):
                site_key = _match_site(match.group(1))
                status_text = match.group(2).lower()
                rc = "GOOD" if "safe" in status_text and "un" not in status_text else \
                     "POOR" if "unsafe" in status_text or "no" in status_text else "MODERATE"
                self._insert_reading(
                    site_name=site_key,
                    metric=METRIC,
                    value=None,
                    unit=UNIT,
                    result_class=rc,
                    sample_date=today,
                    threshold_safe=THRESHOLD_SAFE,
                    threshold_unit=UNIT,
                    source_url=url,
                    lab_certified=False,
                    raw_payload={"match": match.group(0), "url": url},
                    notes="Status scraped from Waterkeeper page – no numeric value"
                )

            if self.records_added > 0:
                return

        # Record a staleness marker so run isn't empty
        if self.records_added == 0:
            self._insert_reading(
                site_name="south_pointe",
                metric=METRIC,
                value=None,
                unit=UNIT,
                result_class="UNKNOWN",
                sample_date=today,
                threshold_safe=THRESHOLD_SAFE,
                threshold_unit=UNIT,
                source_url=WATERKEEPER_DATA_URL,
                lab_certified=False,
                raw_payload={"note": "Swim Guide API unavailable and page scrape found no data"},
                notes="No data retrieved this run – Swim Guide API/page unavailable"
            )

    @staticmethod
    def _extract_date_near(text: str) -> str | None:
        for pat, fmt in [
            (r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),
            (r'\w+ \d{1,2},\s*\d{4}', '%B %d, %Y'),
            (r'\d{1,2}/\d{1,2}/\d{4}', '%m/%d/%Y'),
        ]:
            m = re.search(pat, text)
            if m:
                try:
                    return datetime.strptime(m.group(0), fmt).strftime('%Y-%m-%d')
                except ValueError:
                    continue
        return None
