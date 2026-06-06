"""
DOH Healthy Beaches Collector
Source: Florida Department of Health – Miami-Dade County
Tier:   TIER_1 (NELAP-certified weekly enterococcus)
Sites:  South Pointe, 21st St, 53rd St, 73rd St, 79th St, Purdy Ave (bayside)
Method: ArcGIS Feature Service REST API (backing the FL Healthy Beaches map)
        Falls back to scraping the Miami-Dade DOH advisories page for recent
        press releases when the feature service is unavailable.

Standard: 70 MPN/100mL enterococcus – exceeding triggers advisory.
"""
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

from .base import BaseCollector, utcnow

SOURCE_NAME = "DOH Healthy Beaches"
SOURCE_URL  = "https://miamidade.floridahealth.gov"

# ArcGIS REST endpoint for Florida Healthy Beaches feature service
# (extracted from the FDOH interactive map appid=7106a20597de4bff98cc5ebc7f932047)
ARCGIS_FEATURE_SERVICE = (
    "https://services.arcgis.com/evvgmhMkdWxJfGCF/arcgis/rest/services/"
    "Florida_Healthy_Beaches/FeatureServer/0/query"
)

# Fallback: Miami-Dade DOH press release / beach advisory page
MIAMIDADE_DOH_URL = "https://miamidade.floridahealth.gov/programs-and-services/environmental-health/beaches-and-water/index.html"

# Site name → DB site key mapping
SITE_MAP = {
    "South Pointe":       "south_pointe",
    "South Pointe Drive": "south_pointe",
    "21st":               "collins_21st",
    "21st Street":        "collins_21st",
    "Collins Park":       "collins_21st",
    "53rd":               "53rd_street",
    "53rd Street":        "53rd_street",
    "73rd":               "north_shore_73rd",
    "73rd Street":        "north_shore_73rd",
    "North Shore":        "north_shore_73rd",
    "79th":               "79th_street",
    "79th Street":        "79th_street",
    "Purdy":              "purdy_ave_bayside",
    "Purdy Avenue":       "purdy_ave_bayside",
    "1800 Purdy":         "purdy_ave_bayside",
}

THRESHOLD_SAFE = 70.0
THRESHOLD_UNIT = "MPN/100mL"
METRIC         = "ENTEROCOCCUS"
UNIT           = "MPN/100mL"


def _classify(value: float) -> str:
    if value is None:
        return "UNKNOWN"
    if value <= 35:
        return "GOOD"
    if value <= 70:
        return "MODERATE"
    return "POOR"


def _match_site(text: str) -> str | None:
    for key, db_name in SITE_MAP.items():
        if key.lower() in text.lower():
            return db_name
    return None


class DOHBeachesCollector(BaseCollector):
    source_name = SOURCE_NAME

    def collect(self):
        # Strategy 1: ArcGIS REST API
        collected = self._try_arcgis()
        if collected:
            return

        # Strategy 2: Scrape DOH Miami-Dade advisory/news page
        collected = self._try_doh_page()
        if collected:
            return

        # Strategy 3: Scrape the statewide DOH beach quality page
        self._try_state_doh()

    # ── Strategy 1: ArcGIS Feature Service ───────────────────

    def _try_arcgis(self) -> bool:
        """Query the ArcGIS feature service for Miami-Dade beach data."""
        params = {
            "where":      "COUNTY='Miami-Dade' OR COUNTY='MIAMI-DADE'",
            "outFields":  "*",
            "f":          "json",
            "resultRecordCount": 50,
        }
        headers = {"User-Agent": "MiamiWaterMonitor/1.0 (research)"}
        try:
            resp = requests.get(ARCGIS_FEATURE_SERVICE, params=params,
                                headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return False

        features = data.get("features", [])
        if not features:
            # Try alternate field name
            params["where"] = "1=1"
            try:
                resp = requests.get(ARCGIS_FEATURE_SERVICE, params=params,
                                    headers=headers, timeout=15)
                data = resp.json()
                # Filter to Miami-Dade
                features = [
                    f for f in data.get("features", [])
                    if "miami" in str(f.get("attributes", {}).get("COUNTY", "")).lower()
                    or "miami" in str(f.get("attributes", {}).get("LOCATION", "")).lower()
                ]
            except Exception:
                return False

        if not features:
            return False

        for feat in features:
            attrs = feat.get("attributes", {})
            raw_location = attrs.get("LOCATION") or attrs.get("SITE_NAME") or ""
            site_key = _match_site(raw_location)
            if not site_key:
                continue

            # Parse sample date
            sample_ts = attrs.get("SAMPLE_DATE") or attrs.get("DATE") or attrs.get("SampleDate")
            if sample_ts:
                try:
                    # ArcGIS epoch ms
                    sample_date = datetime.fromtimestamp(
                        int(sample_ts) / 1000, tz=timezone.utc
                    ).strftime('%Y-%m-%d')
                except Exception:
                    sample_date = str(sample_ts)
            else:
                sample_date = utcnow()[:10]

            value_raw = (attrs.get("ENTERO") or attrs.get("ENTEROCOCCUS")
                         or attrs.get("RESULT") or attrs.get("Value"))
            try:
                value = float(value_raw) if value_raw is not None else None
            except (ValueError, TypeError):
                value = None

            result_class = _classify(value)

            self._insert_reading(
                site_name=site_key,
                metric=METRIC,
                value=value,
                unit=UNIT,
                result_class=result_class,
                sample_date=sample_date,
                threshold_safe=THRESHOLD_SAFE,
                threshold_unit=THRESHOLD_UNIT,
                source_url=ARCGIS_FEATURE_SERVICE,
                lab_certified=True,
                raw_payload=attrs,
                notes="ArcGIS feature service – NELAP certified"
            )
        return self.records_added > 0

    # ── Strategy 2: Miami-Dade DOH page scrape ───────────────

    def _try_doh_page(self) -> bool:
        headers = {"User-Agent": "MiamiWaterMonitor/1.0 (research)"}
        try:
            resp = requests.get(MIAMIDADE_DOH_URL, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception:
            return False

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(" ", strip=True)

        # Look for advisory mentions with site names
        advisory_pattern = re.compile(
            r'(advisory|no\s+swim|unsafe|contact)\s+.*?'
            r'(south\s+pointe|21st|53rd|73rd|79th|purdy|north\s+shore|collins)',
            re.IGNORECASE
        )
        found_any = False
        today = utcnow()[:10]

        for match in advisory_pattern.finditer(text):
            snippet = match.group(0)
            site_key = _match_site(snippet)
            if not site_key:
                continue
            advisory_type = "NO_CONTACT" if "no" in snippet.lower() or "unsafe" in snippet.lower() else "CAUTION"
            self._insert_advisory(
                site_name=site_key,
                advisory_type=advisory_type,
                description=snippet[:500],
                issued_date=today,
                is_active=True,
                source_url=MIAMIDADE_DOH_URL,
                raw_payload={"snippet": snippet, "page_url": MIAMIDADE_DOH_URL}
            )
            found_any = True

        # Also try to find tabular enterococcus data in the page
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                site_key = _match_site(" ".join(cells))
                if not site_key:
                    continue
                # Look for a numeric value in any cell
                for cell in cells[1:]:
                    try:
                        value = float(cell.replace(",", "").replace(">", "").replace("<", ""))
                        if 0 <= value <= 100000:
                            self._insert_reading(
                                site_name=site_key,
                                metric=METRIC,
                                value=value,
                                unit=UNIT,
                                result_class=_classify(value),
                                sample_date=today,
                                threshold_safe=THRESHOLD_SAFE,
                                threshold_unit=THRESHOLD_UNIT,
                                source_url=MIAMIDADE_DOH_URL,
                                lab_certified=True,
                                raw_payload={"cells": cells},
                                notes="Scraped from DOH Miami-Dade page table"
                            )
                            found_any = True
                            break
                    except ValueError:
                        continue

        return found_any

    # ── Strategy 3: State DOH Healthy Beaches page ───────────

    def _try_state_doh(self):
        """
        Scrape the statewide FL DOH beach page for any Miami-Dade advisory
        content visible in the HTML (the interactive map data won't be present,
        but press-release text or static advisory notices may be).
        Records a TIER_1 placeholder so the collection run isn't empty.
        """
        state_url = (
            "https://www.floridahealth.gov/community-environmental-public-health/"
            "environmental-public-health/water-quality/aquatic-toxins/beach-water-quality/"
        )
        headers = {"User-Agent": "MiamiWaterMonitor/1.0 (research)"}
        today = utcnow()[:10]
        try:
            resp = requests.get(state_url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text(" ", strip=True)

            # Scan for any Miami Beach / Miami-Dade advisory language
            if re.search(r'miami.dade|miami beach', text, re.IGNORECASE):
                # Record that we checked but found no numeric data
                self._insert_reading(
                    site_name="south_pointe",  # representative site
                    metric=METRIC,
                    value=None,
                    unit=UNIT,
                    result_class="UNKNOWN",
                    sample_date=today,
                    threshold_safe=THRESHOLD_SAFE,
                    threshold_unit=THRESHOLD_UNIT,
                    source_url=state_url,
                    lab_certified=False,
                    raw_payload={"note": "Page fetched; numeric data not available in static HTML (map is JS-rendered)"},
                    notes="State DOH page fetched; live data requires ArcGIS API"
                )
        except Exception:
            pass
