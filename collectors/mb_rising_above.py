"""
MB Rising Above Collector
Source: City of Miami Beach – Rising Above Water Quality Page
Tier:   TIER_1 (NELAP-certified monthly canal sampling + official advisories)
Sites:  Park View Canal, Biscayne Bay (MB network)
Method: Scrape the advisories page + Park View Canal sub-page

This is the authoritative source for:
  - Active "No Contact" advisories on city canals/waterways
  - Monthly canal/bay water quality sampling results (when published)
"""
import re
import json
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from .base import BaseCollector, utcnow

SOURCE_NAME = "MB Rising Above"

WATER_QUALITY_URL  = "https://www.mbrisingabove.com/climate-adaptation/biscayne-bay/water-quality/"
PARK_VIEW_URL      = "https://www.mbrisingabove.com/climate-adaptation/biscayne-bay/park-view-canal-water-quality/"
MB_WATER_QUAL_URL  = "https://www.miamibeachfl.gov/water-quality/water-quality-miami-beach/"

HEADERS = {"User-Agent": "MiamiWaterMonitor/1.0 (research)"}


def _parse_date(text: str) -> str | None:
    """Try to extract an ISO date from free text."""
    patterns = [
        r'(\w+ \d{1,2},\s*\d{4})',    # "February 25, 2026"
        r'(\d{1,2}/\d{1,2}/\d{4})',   # "02/25/2026"
        r'(\d{4}-\d{2}-\d{2})',        # "2026-02-25"
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1)
            for fmt in ('%B %d, %Y', '%b %d, %Y', '%m/%d/%Y', '%Y-%m-%d'):
                try:
                    return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
                except ValueError:
                    continue
    return None


class MBRisingAboveCollector(BaseCollector):
    source_name = SOURCE_NAME

    def collect(self):
        self._collect_water_quality_page()
        self._collect_park_view_page()

    def _collect_water_quality_page(self):
        try:
            resp = requests.get(WATER_QUALITY_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception:
            return

        soup = BeautifulSoup(resp.text, "lxml")
        full_text = soup.get_text(" ", strip=True)

        # ── Find page last-updated date ──────────────────────
        updated_match = re.search(
            r'most recent update.*?(?:was made on|updated on|:)?\s*(\w+ \d{1,2},\s*\d{4})',
            full_text, re.IGNORECASE
        )
        page_date = None
        if updated_match:
            page_date = _parse_date(updated_match.group(0))
        page_date = page_date or utcnow()[:10]

        # ── Parse active advisories ──────────────────────────
        # Look for the advisory section heading + bullet content
        advisory_section = soup.find(
            lambda tag: tag.name in ['h2', 'h3', 'h4', 'strong', 'p']
            and 'active water quality' in tag.get_text(strip=True).lower()
        )

        advisory_items = []
        if advisory_section:
            # Walk siblings after the heading to collect bullet items
            for sibling in advisory_section.find_next_siblings():
                tag_text = sibling.get_text(" ", strip=True)
                if not tag_text:
                    continue
                if sibling.name in ['h2', 'h3', 'h4'] and 'active' not in tag_text.lower():
                    break
                bullets = sibling.find_all('li')
                if bullets:
                    advisory_items.extend([li.get_text(" ", strip=True) for li in bullets])
                elif sibling.name == 'p' and len(tag_text) > 20:
                    advisory_items.append(tag_text)

        # Also regex-scan full text for canonical advisory language
        no_contact_matches = re.findall(
            r'["“]?No Contact["”]?\s+advisory[^.]*\.',
            full_text, re.IGNORECASE
        )
        advisory_items.extend(no_contact_matches)

        # Deduplicate and insert
        seen = set()
        for item in advisory_items:
            key = item[:80]
            if key in seen:
                continue
            seen.add(key)

            # Determine site
            site_key = "park_view_canal"
            if re.search(r'park\s*view|parkview', item, re.IGNORECASE):
                site_key = "park_view_canal"
            elif re.search(r'biscayne|canal|waterway', item, re.IGNORECASE):
                site_key = "biscayne_bay_mb"

            advisory_type = "NO_CONTACT" if re.search(r'no.?contact', item, re.IGNORECASE) else "CAUTION"

            self._insert_advisory(
                site_name=site_key,
                advisory_type=advisory_type,
                description=item[:1000],
                issued_date=page_date,
                is_active=True,
                source_url=WATER_QUALITY_URL,
                raw_payload={
                    "page_updated": page_date,
                    "text": item,
                    "source_url": WATER_QUALITY_URL
                }
            )

        # ── If no structured advisory found, record that we checked ──
        if self.records_added == 0:
            # Check for "no current advisories" language
            if re.search(r'no\s+(current|active)\s+advisor', full_text, re.IGNORECASE):
                self._insert_advisory(
                    site_name="biscayne_bay_mb",
                    advisory_type="UNKNOWN",
                    description="Page checked – no active advisories noted at time of collection.",
                    issued_date=page_date,
                    is_active=False,
                    source_url=WATER_QUALITY_URL,
                    raw_payload={"page_updated": page_date, "status": "no_current_advisory"}
                )
            else:
                # Record a CAUTION/UNKNOWN so the run isn't empty
                snippet = full_text[full_text.lower().find('advisory'):
                                    full_text.lower().find('advisory') + 500] \
                          if 'advisory' in full_text.lower() else full_text[:500]
                self._insert_advisory(
                    site_name="biscayne_bay_mb",
                    advisory_type="UNKNOWN",
                    description=snippet,
                    issued_date=page_date,
                    is_active=False,
                    source_url=WATER_QUALITY_URL,
                    raw_payload={"page_updated": page_date, "raw_snippet": snippet}
                )

    def _collect_park_view_page(self):
        """Park View Canal has its own dedicated page with more detail."""
        try:
            resp = requests.get(PARK_VIEW_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception:
            return

        soup = BeautifulSoup(resp.text, "lxml")
        full_text = soup.get_text(" ", strip=True)

        # Look for any numeric water quality readings on the page
        # e.g. "enterococcus levels of 1234 MPN/100mL"
        reading_pattern = re.compile(
            r'enterococcus[^0-9]*(\d[\d,]*(?:\.\d+)?)\s*(MPN|CFU)?(?:/100\s*mL)?',
            re.IGNORECASE
        )
        for match in reading_pattern.finditer(full_text):
            try:
                value = float(match.group(1).replace(",", ""))
            except ValueError:
                continue

            # Try to find a date near this reading
            context = full_text[max(0, match.start() - 200): match.end() + 200]
            sample_date = _parse_date(context) or utcnow()[:10]

            self._insert_reading(
                site_name="park_view_canal",
                metric="ENTEROCOCCUS",
                value=value,
                unit="MPN/100mL",
                result_class="POOR" if value > 70 else ("MODERATE" if value > 35 else "GOOD"),
                sample_date=sample_date,
                threshold_safe=70.0,
                threshold_unit="MPN/100mL",
                source_url=PARK_VIEW_URL,
                lab_certified=True,
                raw_payload={"context": context[:500], "match": match.group(0)},
                notes="Park View Canal dedicated page – NELAP certified"
            )

        # Capture the advisory status text
        page_date = _parse_date(full_text) or utcnow()[:10]
        is_active = bool(re.search(r'no.?contact|advisory\s+in\s+effect|active\s+advisory',
                                    full_text, re.IGNORECASE))
        description_match = re.search(
            r'(The\s+(?:city\s+has|advisory)[^.]{10,200}\.)', full_text, re.IGNORECASE
        )
        description = description_match.group(1) if description_match else full_text[:500]

        self._insert_advisory(
            site_name="park_view_canal",
            advisory_type="NO_CONTACT" if is_active else "UNKNOWN",
            description=description,
            issued_date=page_date,
            is_active=is_active,
            source_url=PARK_VIEW_URL,
            raw_payload={
                "page_url": PARK_VIEW_URL,
                "is_active": is_active,
                "page_date": page_date
            }
        )
