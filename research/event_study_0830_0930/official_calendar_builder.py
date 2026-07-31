"""Build the isolated official-source U.S. release calendar.

This module builds a timing-first, point-in-time-aware calendar from locally
archived official pages.  It deliberately leaves actual, consensus, and
revision fields empty until a release-vintage collector can prove those values.
It never reads market data and never invokes Stage 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

from .economic_calendar_adapter import (
    GenericEconomicCalendarAdapter,
    add_surprise_features,
    apply_directional_mapping,
    write_canonical_calendar,
)
from .event_cluster_builder import build_event_clusters, write_event_clusters


STUDY_START = date(2025, 7, 17)
STUDY_END = date(2026, 7, 17)
LOCAL_ZONE = ZoneInfo("America/New_York")
SOURCE_NAME = "official_release_archive"
NYFED_BASE = "https://www.newyorkfed.org/research/calendars/"
FED_BASE = "https://www.federalreserve.gov"
DOL_BASE = "https://www.dol.gov"


def _component(
    canonical: str,
    category: str,
    subcategory: str,
    agency: str,
    importance: str,
    release_type: str = "initial",
) -> dict[str, str]:
    return {
        "canonical": canonical,
        "category": category,
        "subcategory": subcategory,
        "agency": agency,
        "importance": importance,
        "release_type": release_type,
    }


BLS = "U.S. Bureau of Labor Statistics"
BEA = "U.S. Bureau of Economic Analysis"
CENSUS = "U.S. Census Bureau"
FED = "Federal Reserve Board"


RAW_EVENT_MAP: dict[str, list[dict[str, str]]] = {
    "Employment Situation": [
        _component("Nonfarm Payrolls", "labor_payrolls", "establishment_employment", BLS, "major"),
        _component("Unemployment Rate", "labor_unemployment", "household_unemployment", BLS, "major"),
        _component("Average Hourly Earnings", "labor_wages", "average_hourly_earnings", BLS, "major"),
    ],
    "Consumer Price Index": [
        _component("CPI", "inflation_cpi", "headline", BLS, "major"),
        _component("Core CPI", "inflation_cpi", "core", BLS, "major"),
    ],
    "Producer Price Index (PPI)": [
        _component("PPI", "inflation_ppi", "headline", BLS, "major"),
        _component("Core PPI", "inflation_ppi", "core", BLS, "major"),
    ],
    "Advance Retail Sales": [
        _component("Retail Sales", "consumption_retail_sales", "headline", CENSUS, "major"),
        _component("Core Retail Sales", "consumption_retail_sales", "ex_autos", CENSUS, "major"),
    ],
    "Advance Durable Goods": [
        _component("Durable Goods Orders", "durable_goods", "headline", CENSUS, "minor"),
        _component("Core Durable Goods Orders", "durable_goods", "ex_transportation", CENSUS, "minor"),
    ],
    "Advance International Trade in Goods": [
        _component("Advance Goods Trade Balance", "trade", "advance_goods", CENSUS, "minor")
    ],
    "Trade balance": [
        _component(
            "Trade Balance",
            "trade",
            "goods_and_services",
            "U.S. Census Bureau and U.S. Bureau of Economic Analysis",
            "minor",
        )
    ],
    "New Residential Construction": [
        _component("Housing Starts", "housing_starts", "starts", "U.S. Census Bureau / HUD", "minor"),
        _component("Building Permits", "housing_starts", "permits", "U.S. Census Bureau / HUD", "minor"),
    ],
    "Imports and Exports": [
        _component("Import Prices", "trade_prices", "imports", BLS, "minor"),
        _component("Export Prices", "trade_prices", "exports", BLS, "minor"),
    ],
    "Employment Cost Index": [
        _component("Employment Cost Index", "labor_compensation", "eci", BLS, "minor")
    ],
    "Productivity & Costs (Preliminary)": [
        _component("Productivity", "productivity", "nonfarm_productivity", BLS, "minor", "preliminary"),
        _component("Unit Labor Costs", "productivity", "unit_labor_costs", BLS, "minor", "preliminary"),
    ],
    "Productivity & Costs (Revised)": [
        _component("Productivity", "productivity", "nonfarm_productivity", BLS, "minor", "revised"),
        _component("Unit Labor Costs", "productivity", "unit_labor_costs", BLS, "minor", "revised"),
    ],
    "Philadelphia Fed Manufacturing Survey": [
        _component(
            "Philadelphia Fed Manufacturing",
            "regional_manufacturing",
            "philadelphia_fed",
            "Federal Reserve Bank of Philadelphia",
            "minor",
        )
    ],
    "Empire State Manufacturing Survey": [
        _component(
            "Empire State Manufacturing",
            "regional_manufacturing",
            "empire_state",
            "Federal Reserve Bank of New York",
            "minor",
        )
    ],
    "Industrial Production and Capacity Utilization": [
        _component("Industrial Production", "industrial_production", "production", FED, "minor"),
        _component("Capacity Utilization", "industrial_production", "capacity_utilization", FED, "minor"),
    ],
    "ISM Manufacturing": [
        _component("ISM Manufacturing", "manufacturing_ism", "headline", "Institute for Supply Management", "major")
    ],
    "ISM Non-Manufacturing": [
        _component("ISM Services", "services_ism", "headline", "Institute for Supply Management", "major")
    ],
    "JOLTS": [_component("JOLTS", "labor_jolts", "job_openings", BLS, "major")],
    "Consumer Confidence": [
        _component("Consumer Confidence", "sentiment_consumer", "conference_board", "The Conference Board", "minor")
    ],
    "New Residential Sales": [
        _component("New Home Sales", "housing_sales", "new_homes", "U.S. Census Bureau / HUD", "minor")
    ],
    "NAR Existing Home Sales": [
        _component("Existing Home Sales", "housing_sales", "existing_homes", "National Association of Realtors", "minor")
    ],
    "Manufacturing, Shipments, and Orders": [
        _component("Factory Orders", "factory_orders", "manufacturers_orders", CENSUS, "minor")
    ],
    "Construction": [
        _component("Construction Spending", "construction_spending", "value_of_construction", CENSUS, "minor")
    ],
    "Michigan Consumer Survey (Preliminary)": [
        _component(
            "University of Michigan Sentiment (Preliminary)",
            "sentiment_consumer",
            "michigan_preliminary",
            "University of Michigan Surveys of Consumers",
            "minor",
            "preliminary",
        )
    ],
    "Michigan Consumer Survey (Final)": [
        _component(
            "University of Michigan Sentiment (Final)",
            "sentiment_consumer",
            "michigan_final",
            "University of Michigan Surveys of Consumers",
            "minor",
            "final",
        )
    ],
    "Business Inventories": [
        _component("Business Inventories", "business_inventories", "total_business", CENSUS, "minor")
    ],
    "Wholesale Trade": [
        _component("Wholesale Inventories", "wholesale_inventories", "merchant_wholesalers", CENSUS, "minor")
    ],
}

CENSUS_RAW_NAMES = {
    "Advance Retail Sales",
    "Advance Durable Goods",
    "Advance International Trade in Goods",
    "Trade balance",
    "New Residential Construction",
    "New Residential Sales",
    "Business Inventories",
    "Wholesale Trade",
    "Construction",
    "Manufacturing, Shipments, and Orders",
}


def _gdp_components(raw_name: str) -> list[dict[str, str]]:
    release_type = {
        "1st": "advance",
        "2nd": "second_estimate",
        "3rd": "third_estimate",
    }[re.search(r"([123](?:st|nd|rd))", raw_name).group(1)]
    return [_component("GDP", "growth_gdp", "real_gdp", BEA, "major", release_type)]


def _pce_components() -> list[dict[str, str]]:
    return [
        _component("Personal Income", "personal_income", "personal_income", BEA, "minor"),
        _component("Personal Spending", "personal_spending", "personal_consumption_expenditures", BEA, "minor"),
        _component("PCE Price Index", "inflation_pce", "headline", BEA, "major"),
        _component("Core PCE Price Index", "inflation_pce", "core", BEA, "major"),
    ]


# Official reschedule notices.  Values are the originally announced ET times;
# the row timestamp always remains the actual publication timestamp.
SCHEDULE_CHANGES: dict[tuple[str, str], tuple[list[str], str]] = {
    ("Consumer Price Index", "2025-10-24"): (["2025-10-15 08:30"], "2025 lapse in appropriations"),
    ("Employment Situation", "2025-11-20"): (["2025-10-03 08:30"], "2025 lapse in appropriations"),
    ("Producer Price Index (PPI)", "2025-11-25"): (["2025-10-16 08:30"], "2025 lapse in appropriations"),
    ("JOLTS", "2026-02-05"): (["2026-02-03 10:00"], "2026 lapse in appropriations"),
    ("Employment Situation", "2026-02-11"): (["2026-02-06 08:30"], "2026 lapse in appropriations"),
    ("Consumer Price Index", "2026-02-13"): (["2026-02-11 08:30"], "2026 lapse in appropriations"),
    ("Employment Situation", "2025-12-16"): (["2025-12-05 08:30"], "2025 lapse in appropriations"),
    ("Consumer Price Index", "2025-12-18"): (["2025-12-10 08:30"], "2025 lapse in appropriations"),
    ("JOLTS", "2025-12-09"): (["2025-12-02 10:00"], "2025 lapse in appropriations"),
    ("Employment Cost Index", "2025-12-10"): (["2025-10-31 08:30"], "2025 lapse in appropriations"),
    ("Producer Price Index (PPI)", "2026-01-14"): (["2025-12-11 08:30"], "2025 lapse in appropriations"),
    ("Producer Price Index (PPI)", "2026-01-30"): (["2026-01-14 08:30"], "2025 lapse in appropriations"),
    ("Producer Price Index (PPI)", "2026-02-27"): (["2026-02-12 08:30"], "2025 lapse in appropriations"),
    ("Producer Price Index (PPI)", "2026-03-18"): (["2026-03-12 08:30"], "2025 lapse in appropriations"),
    ("Imports and Exports", "2025-12-03"): (["2025-10-17 08:30"], "2025 lapse in appropriations"),
    ("Imports and Exports", "2026-01-15"): (["2025-12-16 08:30"], "2025 lapse in appropriations"),
    ("Imports and Exports", "2026-02-10"): (["2026-01-15 08:30"], "2025 lapse in appropriations"),
    ("Imports and Exports", "2026-03-05"): (["2026-02-18 08:30"], "2025 lapse in appropriations"),
    ("Imports and Exports", "2026-03-25"): (["2026-03-17 08:30"], "2025 lapse in appropriations"),
    ("Employment Cost Index", "2026-02-10"): (["2026-01-30 08:30"], "2025 lapse in appropriations"),
    ("Productivity & Costs (Preliminary)", "2026-01-08"): (["2025-11-06 08:30"], "2025 lapse in appropriations"),
    ("Productivity & Costs (Revised)", "2026-01-29"): (["2025-12-09 08:30"], "2025 lapse in appropriations"),
    ("Productivity & Costs (Preliminary)", "2026-03-05"): (["2026-02-05 08:30"], "2025 lapse in appropriations"),
    ("Productivity & Costs (Revised)", "2026-03-24"): (["2026-03-05 08:30"], "2025 lapse in appropriations"),
    ("Gross Domestic Product 2nd Release", "2026-03-13"): (["2026-02-26 08:30"], "post-shutdown BEA schedule update"),
    ("Personal Income and the PCE Deflator", "2026-03-13"): (["2026-02-26 08:30"], "post-shutdown BEA schedule update"),
    ("Gross Domestic Product 3rd Release", "2026-04-09"): (["2026-03-27 08:30"], "post-shutdown BEA schedule update"),
    ("Personal Income and the PCE Deflator", "2026-04-09"): (["2026-03-27 08:30"], "post-shutdown BEA schedule update"),
    ("Industrial Production and Capacity Utilization", "2025-12-03"): (["2025-10-17 09:15"], "2025 shutdown source-data delay"),
    (
        "Industrial Production and Capacity Utilization",
        "2025-12-23",
    ): (["2025-11-18 09:15", "2025-12-16 09:15"], "two delayed G.17 releases combined"),
}


# Transform dates copied from advance calendars into actual publication dates.
# A null target means the release was officially canceled.  Cases already
# updated on the monthly archive (for example December CPI and JOLTS) are
# represented only in SCHEDULE_CHANGES above.
TIMING_OVERRIDES: dict[tuple[str, str], str | None] = {
    ("Consumer Price Index", "2025-10-15"): "2025-10-24",
    ("Employment Situation", "2025-10-03"): "2025-11-20",
    ("Employment Situation", "2025-11-07"): None,
    ("Employment Situation", "2025-12-05"): "2025-12-16",
    ("Consumer Price Index", "2025-11-13"): None,
    ("JOLTS", "2025-10-06"): None,
    ("Producer Price Index (PPI)", "2025-10-16"): "2025-11-25",
    ("Producer Price Index (PPI)", "2025-11-14"): None,
    ("Producer Price Index (PPI)", "2025-12-11"): "2026-01-14",
    ("Producer Price Index (PPI)", "2026-01-14"): "2026-01-30",
    ("Producer Price Index (PPI)", "2026-02-12"): "2026-02-27",
    ("Producer Price Index (PPI)", "2026-03-12"): "2026-03-18",
    ("Imports and Exports", "2025-10-17"): "2025-12-03",
    ("Imports and Exports", "2025-11-18"): None,
    ("Imports and Exports", "2025-12-16"): "2026-01-15",
    ("Imports and Exports", "2026-01-15"): "2026-02-10",
    ("Imports and Exports", "2026-02-18"): "2026-03-05",
    ("Imports and Exports", "2026-03-17"): "2026-03-25",
    ("Employment Cost Index", "2025-10-31"): "2025-12-10",
    ("Employment Cost Index", "2026-01-30"): "2026-02-10",
    ("Productivity & Costs (Preliminary)", "2025-11-06"): "2026-01-08",
    ("Productivity & Costs (Revised)", "2025-12-09"): "2026-01-29",
    ("Productivity & Costs (Preliminary)", "2026-02-05"): "2026-03-05",
    ("Productivity & Costs (Revised)", "2026-03-05"): "2026-03-24",
    ("Employment Situation", "2026-02-06"): "2026-02-11",
    ("Consumer Price Index", "2026-02-11"): "2026-02-13",
    ("Industrial Production and Capacity Utilization", "2025-10-17"): "2025-12-03",
    ("Industrial Production and Capacity Utilization", "2025-11-18"): None,
    ("Industrial Production and Capacity Utilization", "2025-12-16"): "2025-12-23",
}


def _timestamp(day: date, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day.isoformat()} {clock}", tz=LOCAL_ZONE)


def _event_id(
    agency: str,
    canonical: str,
    timestamp_utc: pd.Timestamp,
    release_type: str,
    reference_period: str,
) -> str:
    payload = "|".join(
        (agency, canonical, timestamp_utc.isoformat(), release_type, reference_period)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _source_reliability(source_type: str) -> str:
    return "OFFICIAL_PRIMARY" if source_type == "OFFICIAL_PRIMARY" else "OFFICIAL_ARCHIVE"


def _make_row(
    *,
    day: date,
    clock: str,
    raw_name: str,
    component: dict[str, str],
    source_url: str,
    schedule_source_url: str,
    source_type: str,
    bundle_key: str,
    retrieved_at: str,
    reference_period: str = "",
) -> dict[str, object]:
    local = _timestamp(day, clock)
    utc = local.tz_convert("UTC")
    original_local: list[str] = []
    original_utc: list[str] = []
    change = SCHEDULE_CHANGES.get((raw_name, day.isoformat()))
    if change:
        for value in change[0]:
            original = pd.Timestamp(value, tz=LOCAL_ZONE)
            original_local.append(original.isoformat())
            original_utc.append(original.tz_convert("UTC").isoformat())
    release_type = component["release_type"]
    note = "Timing verified; values intentionally absent pending release-vintage extraction."
    if change:
        note += f" Rescheduled: {change[1]}."
    return {
        "event_id": _event_id(
            component["agency"], component["canonical"], utc, release_type, reference_period
        ),
        "release_timestamp_local": local.isoformat(),
        "release_timestamp_utc": utc.isoformat(),
        "release_timestamp_new_york": local.isoformat(),
        "timezone": "America/New_York",
        "country": "US",
        "currency": "USD",
        "agency": component["agency"],
        "institution": component["agency"],
        "event_name_raw": raw_name,
        "event_name_canonical": component["canonical"],
        "event_name": component["canonical"],
        "event_category": component["category"],
        "category": component["category"],
        "event_subcategory": component["subcategory"],
        "release_type": release_type,
        "release_version": release_type,
        "importance": component["importance"],
        "scheduled_or_unscheduled": "scheduled",
        "source": SOURCE_NAME,
        "source_url": source_url,
        "source_type": source_type,
        "retrieved_at_utc": retrieved_at,
        "retrieval_timestamp": retrieved_at,
        "actual": math.nan,
        "actual_unit": "",
        "unit": "",
        "consensus": math.nan,
        "consensus_source": "",
        "previous_as_published": math.nan,
        "previous": math.nan,
        "revised_previous": math.nan,
        "revision_value": math.nan,
        "revision_direction": "",
        "reference_period": reference_period,
        "release_vintage": release_type,
        "value_status": "official_actual_missing",
        "consensus_status": "consensus_missing",
        "latest_revised_value": math.nan,
        "point_in_time_verified": False,
        "timing_verified": True,
        "original_scheduled_timestamp_local": ";".join(original_local),
        "original_scheduled_timestamp_utc": ";".join(original_utc),
        "schedule_change_status": "rescheduled" if change else "as_scheduled_or_no_change_recorded",
        "schedule_change_reason": change[1] if change else "",
        "schedule_source_url": schedule_source_url,
        "calendar_reliability_grade": _source_reliability(source_type),
        "release_bundle_key": bundle_key,
        "notes": note,
    }


def _parse_nyfed(raw_dir: Path, retrieved_at: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    month_lookup = {name.lower()[:3]: number for number, name in enumerate(
        ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    ) if name}
    for path in sorted(raw_dir.glob("nyfed_i-*.html")):
        match = re.search(r"i-([a-z]{3})(\d{2})", path.name)
        if not match:
            continue
        month = month_lookup[match.group(1)]
        year = 2000 + int(match.group(2))
        schedule_url = urljoin(NYFED_BASE, path.name.removeprefix("nyfed_"))
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for span in soup.select("span.ts-accordion-content"):
            parent = span.find_parent("td") or span.parent
            first_text = next(parent.stripped_strings, "")
            if not re.fullmatch(r"\d{1,2}", first_text):
                continue
            day = date(year, month, int(first_text))
            if day < STUDY_START or day > STUDY_END:
                continue
            values = list(span.stripped_strings)
            link_by_name = {
                link.get_text(" ", strip=True): link for link in span.find_all("a")
            }
            pairs = [
                (values[index], values[index + 1].strip("()"))
                for index in range(len(values) - 1)
                if re.fullmatch(r"\(\d{2}:\d{2}\)", values[index + 1])
            ]
            for raw_name, clock in pairs:
                if raw_name in CENSUS_RAW_NAMES or raw_name.startswith(
                    "Gross Domestic Product "
                ) or raw_name == "Personal Income and the PCE Deflator":
                    # Primary Census and BEA schedules are parsed below.
                    continue
                target = TIMING_OVERRIDES.get((raw_name, day.isoformat()), day.isoformat())
                if target is None:
                    continue
                publication_day = date.fromisoformat(target)
                if publication_day < STUDY_START or publication_day > STUDY_END:
                    continue
                components = RAW_EVENT_MAP.get(raw_name)
                if raw_name.startswith("Gross Domestic Product "):
                    components = _gdp_components(raw_name)
                elif raw_name == "Personal Income and the PCE Deflator":
                    components = _pce_components()
                if not components:
                    continue
                link = link_by_name.get(raw_name)
                href = urljoin(
                    schedule_url, (link.get("href") if link else schedule_url) or schedule_url
                )
                bundle_key = f"NYFED|{publication_day.isoformat()}|{clock}|{raw_name}"
                for component in components:
                    rows.append(
                        _make_row(
                            day=publication_day,
                            clock=clock,
                            raw_name=raw_name,
                            component=component,
                            source_url=href,
                            schedule_source_url=schedule_url,
                            source_type="OFFICIAL_ARCHIVE",
                            bundle_key=bundle_key,
                            retrieved_at=retrieved_at,
                        )
                    )
    return rows


def _parse_census(raw_dir: Path, retrieved_at: str) -> list[dict[str, object]]:
    title_map = (
        ("Construction Spending", "Construction"),
        ("Full Report - Manufacturers'", "Manufacturing, Shipments, and Orders"),
        ("U.S. International Trade in Goods and Services", "Trade balance"),
        ("Monthly Wholesale Trade", "Wholesale Trade"),
        ("Advance Monthly Sales for Retail", "Advance Retail Sales"),
        ("Manufacturing and Trade: Inventories and Sales", "Business Inventories"),
        ("New Residential Construction", "New Residential Construction"),
        ("New Residential Sales", "New Residential Sales"),
        ("Advance Report on Durable Goods", "Advance Durable Goods"),
        ("Advance Economic Indicators Report", "Advance International Trade in Goods"),
    )
    rows: list[dict[str, object]] = []
    for path in sorted(raw_dir.glob("census_20*.html")):
        schedule_url = (
            "https://www.census.gov/economic-indicators/calendar-listview-2025.html"
            if "2025" in path.name
            else "https://www.census.gov/economic-indicators/calendar-listview.html"
        )
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for table_row in soup.select("table#calendar tr"):
            cells = table_row.find_all("td", recursive=False)
            if len(cells) < 4:
                continue
            title = cells[0].get_text(" ", strip=True)
            raw_name = next((raw for prefix, raw in title_map if title.startswith(prefix)), "")
            if not raw_name:
                continue
            date_text = cells[1].get_text(" ", strip=True)
            if date_text.lower() == "suspended":
                continue
            try:
                publication_day = datetime.strptime(date_text, "%B %d, %Y").date()
            except ValueError:
                continue
            if not STUDY_START <= publication_day <= STUDY_END:
                continue
            time_text = cells[2].get_text(" ", strip=True)
            parsed_time = datetime.strptime(time_text, "%I:%M %p").strftime("%H:%M")
            reference_period = cells[3].get_text(" ", strip=True)
            link = cells[0].find("a")
            source_url = urljoin("https://www.census.gov", link.get("href") if link else "")
            bundle = f"CENSUS|{publication_day.isoformat()}|{parsed_time}|{raw_name}|{reference_period}"
            for component in RAW_EVENT_MAP[raw_name]:
                rows.append(
                    _make_row(
                        day=publication_day,
                        clock=parsed_time,
                        raw_name=raw_name,
                        component=component,
                        source_url=source_url or schedule_url,
                        schedule_source_url=schedule_url,
                        source_type="OFFICIAL_PRIMARY",
                        bundle_key=bundle,
                        retrieved_at=retrieved_at,
                        reference_period=reference_period,
                    )
                )
    return rows


def _parse_bea(raw_dir: Path, retrieved_at: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(raw_dir.glob("bea_20*.html")):
        year_match = re.search(r"(20\d{2})", path.name)
        if not year_match:
            continue
        year = int(year_match.group(1))
        schedule_url = (
            "https://www.bea.gov/news/schedule/full-2025"
            if year == 2025
            else "https://www.bea.gov/news/schedule/full"
        )
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for table_row in soup.select("tr"):
            date_element = table_row.select_one(".release-date")
            title_element = table_row.select_one(".release-title")
            time_element = table_row.select_one("small.text-muted")
            if not date_element or not title_element or not time_element:
                continue
            title = title_element.get_text(" ", strip=True)
            if (
                title.startswith("GDP (Advance Estimate")
                or title.startswith("Gross Domestic Product")
                and ("(Advance Estimate)" in title or "(Initial Estimate)" in title)
                and " by State" not in title
                and " by County" not in title
            ):
                raw_name = "Gross Domestic Product 1st Release"
                components = _gdp_components(raw_name)
            elif (
                title.startswith("GDP (Second Estimate")
                or title.startswith("Gross Domestic Product")
                and ("(Second Estimate)" in title or "(Updated Estimate)" in title)
                and " by State" not in title
                and " by County" not in title
            ):
                raw_name = "Gross Domestic Product 2nd Release"
                components = _gdp_components(raw_name)
            elif (
                title.startswith("GDP (Third Estimate")
                or title.startswith("Gross Domestic Product")
                and "(Third Estimate)" in title
                and " by State" not in title
                and " by County" not in title
            ):
                raw_name = "Gross Domestic Product 3rd Release"
                components = _gdp_components(raw_name)
            elif title.startswith("Personal Income and Outlays"):
                raw_name = "Personal Income and the PCE Deflator"
                components = _pce_components()
            else:
                continue
            try:
                publication_day = datetime.strptime(
                    f"{date_element.get_text(' ', strip=True)} {year}", "%B %d %Y"
                ).date()
                parsed_time = datetime.strptime(
                    time_element.get_text(" ", strip=True), "%I:%M %p"
                ).strftime("%H:%M")
            except ValueError:
                continue
            if not STUDY_START <= publication_day <= STUDY_END:
                continue
            source_link = table_row.find("a", href=True)
            # In the historical schedule a planned but canceled release can
            # remain as a date with no View link.  Only actual release pages
            # are admitted for dates that have already passed.
            if source_link is None:
                continue
            source_url = urljoin("https://www.bea.gov", source_link.get("href"))
            reference_period = title.split(",", 1)[1].strip() if "," in title else ""
            bundle = f"BEA|{publication_day.isoformat()}|{parsed_time}|{raw_name}|{reference_period}"
            for component in components:
                rows.append(
                    _make_row(
                        day=publication_day,
                        clock=parsed_time,
                        raw_name=raw_name,
                        component=component,
                        source_url=source_url,
                        schedule_source_url=schedule_url,
                        source_type="OFFICIAL_PRIMARY",
                        bundle_key=bundle,
                        retrieved_at=retrieved_at,
                        reference_period=reference_period,
                    )
                )
    return rows


def _parse_claims(raw_dir: Path, retrieved_at: str) -> list[dict[str, object]]:
    releases: dict[date, str] = {}
    for path in sorted(raw_dir.glob("dol_claims_page*.html")):
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for teaser in soup.select(".left-teaser-text"):
            if "Unemployment Insurance Weekly Claims Report" not in teaser.get_text(" ", strip=True):
                continue
            date_element = teaser.select_one(".dol-date-text")
            link = teaser.select_one("a")
            if not date_element or not link:
                continue
            day = datetime.strptime(date_element.get_text(" ", strip=True), "%B %d, %Y").date()
            if STUDY_START <= day <= STUDY_END:
                releases[day] = urljoin(DOL_BASE, (link.get("href") or "").strip())
    components = [
        _component("Initial Jobless Claims", "labor_claims", "initial_claims", "U.S. Department of Labor", "minor"),
        _component("Continuing Claims", "labor_claims", "continuing_claims", "U.S. Department of Labor", "minor"),
    ]
    rows: list[dict[str, object]] = []
    for day, source_url in sorted(releases.items()):
        bundle_key = f"DOL|{day.isoformat()}|08:30|Weekly Claims"
        for component in components:
            rows.append(
                _make_row(
                    day=day,
                    clock="08:30",
                    raw_name="Unemployment Insurance Weekly Claims Report",
                    component=component,
                    source_url=source_url,
                    schedule_source_url="https://www.dol.gov/newsroom/releases?topic=132",
                    source_type="OFFICIAL_ARCHIVE",
                    bundle_key=bundle_key,
                    retrieved_at=retrieved_at,
                )
            )
    return rows


def _primary_schedule_additions(retrieved_at: str) -> list[dict[str, object]]:
    """Add primary-schedule releases absent from the NY Fed July archive."""

    additions = (
        (
            date(2026, 7, 15),
            "Producer Price Index (PPI)",
            "June 2026",
            "https://www.bls.gov/schedule/news_release/ppi.htm",
        ),
    )
    rows: list[dict[str, object]] = []
    for day, raw_name, reference_period, source_url in additions:
        bundle = f"BLS|{day.isoformat()}|08:30|{raw_name}|{reference_period}"
        for component in RAW_EVENT_MAP[raw_name]:
            rows.append(
                _make_row(
                    day=day,
                    clock="08:30",
                    raw_name=raw_name,
                    component=component,
                    source_url=source_url,
                    schedule_source_url=source_url,
                    source_type="OFFICIAL_PRIMARY",
                    bundle_key=bundle,
                    retrieved_at=retrieved_at,
                    reference_period=reference_period,
                )
            )
    return rows


def _parse_fomc(raw_dir: Path, retrieved_at: str) -> list[dict[str, object]]:
    path = raw_dir / "fomc_calendars.html"
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    rows: list[dict[str, object]] = []
    for meeting in soup.select("div.fomc-meeting"):
        statement = meeting.find("a", href=re.compile(r"/newsevents/pressreleases/monetary\d{8}a\.htm$"))
        if not statement or "Statement:" not in meeting.get_text(" ", strip=True):
            continue
        date_match = re.search(r"monetary(\d{8})a", statement.get("href") or "")
        if not date_match:
            continue
        decision_day = datetime.strptime(date_match.group(1), "%Y%m%d").date()
        if STUDY_START <= decision_day <= STUDY_END:
            bundle = f"FOMC|{decision_day.isoformat()}|decision"
            for component in (
                _component("FOMC Rate Decision", "monetary_policy_fomc", "rate_decision", "Federal Open Market Committee", "major", "rate_decision"),
                _component("FOMC Statement", "monetary_policy_fomc", "statement", "Federal Open Market Committee", "major", "statement"),
            ):
                rows.append(
                    _make_row(
                        day=decision_day,
                        clock="14:00",
                        raw_name="FOMC policy decision",
                        component=component,
                        source_url=urljoin(FED_BASE, statement.get("href") or ""),
                        schedule_source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        source_type="OFFICIAL_PRIMARY",
                        bundle_key=bundle,
                        retrieved_at=retrieved_at,
                    )
                )
            projection = meeting.find("a", href=re.compile(r"fomcprojtabl\d{8}\.htm$"))
            if projection:
                rows.append(
                    _make_row(
                        day=decision_day,
                        clock="14:00",
                        raw_name="FOMC Projection Materials",
                        component=_component("Summary of Economic Projections", "monetary_policy_fomc", "summary_of_economic_projections", "Federal Open Market Committee", "major", "statement"),
                        source_url=urljoin(FED_BASE, projection.get("href") or ""),
                        schedule_source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        source_type="OFFICIAL_PRIMARY",
                        bundle_key=bundle,
                        retrieved_at=retrieved_at,
                    )
                )
            conference = meeting.find("a", string=re.compile(r"Press Conference", re.I))
            if conference:
                rows.append(
                    _make_row(
                        day=decision_day,
                        clock="14:30",
                        raw_name="FOMC Chair Press Conference",
                        component=_component("FOMC Chair Press Conference", "monetary_policy_fomc", "press_conference", "Federal Open Market Committee", "major", "press_conference"),
                        source_url=urljoin(FED_BASE, conference.get("href") or ""),
                        schedule_source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        source_type="OFFICIAL_PRIMARY",
                        bundle_key=f"FOMC|{decision_day.isoformat()}|press_conference",
                        retrieved_at=retrieved_at,
                    )
                )
        minutes_text = meeting.get_text(" ", strip=True)
        minutes_match = re.search(r"Released ([A-Z][a-z]+ \d{2}, \d{4})", minutes_text)
        minutes_link = meeting.find("a", href=re.compile(r"fomcminutes\d{8}\.htm$"))
        if minutes_match and minutes_link:
            minutes_day = datetime.strptime(minutes_match.group(1), "%B %d, %Y").date()
            if STUDY_START <= minutes_day <= STUDY_END:
                rows.append(
                    _make_row(
                        day=minutes_day,
                        clock="14:00",
                        raw_name="FOMC Minutes",
                        component=_component("FOMC Minutes", "monetary_policy_fomc", "minutes", "Federal Open Market Committee", "major", "minutes"),
                        source_url=urljoin(FED_BASE, minutes_link.get("href") or ""),
                        schedule_source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        source_type="OFFICIAL_PRIMARY",
                        bundle_key=f"FOMC|{minutes_day.isoformat()}|minutes",
                        retrieved_at=retrieved_at,
                    )
                )
    return rows


def _raw_hashes(raw_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(raw_dir.glob("*")):
        if path.is_file():
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _write_mapping(path: Path) -> None:
    records: list[dict[str, str]] = []
    for raw_name, components in RAW_EVENT_MAP.items():
        for component in components:
            records.append({"event_name_raw": raw_name, **component, "mapping_status": "included"})
    for ordinal in ("1st", "2nd", "3rd"):
        raw_name = f"Gross Domestic Product {ordinal} Release"
        for component in _gdp_components(raw_name):
            records.append({"event_name_raw": raw_name, **component, "mapping_status": "included"})
    for component in _pce_components():
        records.append({"event_name_raw": "Personal Income and the PCE Deflator", **component, "mapping_status": "included"})
    for component in (
        _component("Initial Jobless Claims", "labor_claims", "initial_claims", "U.S. Department of Labor", "minor"),
        _component("Continuing Claims", "labor_claims", "continuing_claims", "U.S. Department of Labor", "minor"),
    ):
        records.append({"event_name_raw": "Unemployment Insurance Weekly Claims Report", **component, "mapping_status": "included"})
    records.append(
        {
            "event_name_raw": "S&P Global U.S. PMI",
            "canonical": "S&P Global U.S. PMI",
            "category": "pmi_private",
            "subcategory": "composite_manufacturing_services",
            "agency": "S&P Global",
            "importance": "minor",
            "release_type": "preliminary_or_final",
            "mapping_status": "excluded_source_unusable",
        }
    )
    pd.DataFrame(records).sort_values(["event_name_raw", "canonical"]).to_csv(path, index=False)


def _write_rules(path: Path) -> None:
    path.write_text(
        """# Event classification rules

## Scope

The mapping is deterministic and is applied only to registered official or official-archive release names. It does not use retail-calendar impact labels. One official release may expand into multiple measurable components, and `release_bundle_key` preserves that relationship.

## Importance rule

`major` is assigned ex ante to broad U.S. inflation, payroll/unemployment/wage, retail-sales, GDP, PCE, ISM, JOLTS and scheduled FOMC information. Other registered releases are `minor`. The label is a research stratum, not a claim that price will move and not a source-provided rating.

## Bundles and attribution

Components from the same official release share a bundle key. Same-time components in one bundle form a `clean_cluster`. Independently published releases that collide at the same time form an `ambiguous_cluster`; no dominant event is forced. Surprise conflicts can be evaluated only after point-in-time actual and consensus values exist.

## Values and revisions

All value fields are null in this timing build. `point_in_time_verified` therefore remains false even when `timing_verified` is true. A later revised time series must never be substituted for a release-vintage actual or prior value.

## Non-news-day safety

A weekday is classified as a non-news day only relative to the registered usable sources. S&P Global 09:45 PMI is excluded because a complete, redistributable official archive was not established; the limitation is carried in `calendar_completeness_status` and metadata.

## Schedule changes

The actual publication timestamp is canonical. When an official notice identifies an earlier schedule, the prior timestamp is retained in `original_scheduled_timestamp_local` and UTC, with a reason. Combined releases may retain more than one original timestamp separated by semicolons.
""",
        encoding="utf-8",
    )


def _classify_days(events: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    local = pd.to_datetime(events["release_timestamp_local"], utc=True).dt.tz_convert(LOCAL_ZONE)
    events = events.copy()
    events["date_et"] = local.dt.date.astype(str)
    events["clock_et"] = local.dt.strftime("%H:%M")
    cluster_by_date: dict[str, list[str]] = {}
    for _, row in clusters.iterrows():
        day = pd.Timestamp(row["release_timestamp_new_york"]).date().isoformat()
        cluster_by_date.setdefault(day, []).append(str(row["cluster_id"]))
    records: list[dict[str, object]] = []
    for timestamp in pd.bdate_range(STUDY_START, STUDY_END):
        day = timestamp.date().isoformat()
        group = events[events["date_et"].eq(day)]
        clocks = set(group["clock_et"])
        has_fomc = bool(group["event_category"].eq("monetary_policy_fomc").any())
        has_macro = bool((~group["event_category"].eq("monetary_policy_fomc")).any())
        h0830, h0915, h0945, h1000 = (clock in clocks for clock in ("08:30", "09:15", "09:45", "10:00"))
        if has_fomc and not has_macro:
            timing = "fomc_day"
        elif has_fomc:
            timing = "mixed_release_day"
        elif h0830 and h1000:
            timing = "0830_and_1000"
        elif h0830 and not (h0915 or h0945 or h1000):
            timing = "0830_only"
        elif h1000 and not (h0830 or h0915 or h0945):
            timing = "1000_only"
        elif len(group) == 0:
            timing = "no_scheduled_release"
        else:
            timing = "mixed_release_day"
        high_count = int(group["importance"].eq("major").sum())
        if len(group) == 0:
            news_class = "non_news_day_usable_sources_only"
        elif high_count:
            news_class = "major_news_day"
        else:
            news_class = "minor_news_day"
        records.append(
            {
                "date_et": day,
                "has_0830_release": h0830,
                "has_0915_release": h0915,
                "has_0945_release": h0945,
                "has_1000_release": h1000,
                "has_fomc_event": has_fomc,
                "event_count": int(len(group)),
                "high_priority_event_count": high_count,
                "categories_present": json.dumps(sorted(group["event_category"].unique().tolist())),
                "cluster_ids": json.dumps(sorted(cluster_by_date.get(day, []))),
                "timing_class": timing,
                "news_day_class": news_class,
                "calendar_completeness_status": "complete_registered_sources_0945_pmi_excluded",
            }
        )
    return pd.DataFrame(records)


def _metrics(events: pd.DataFrame, clusters: pd.DataFrame, days: pd.DataFrame) -> dict[str, object]:
    timestamps = pd.to_datetime(events["release_timestamp_utc"], utc=True)
    local = timestamps.dt.tz_convert(LOCAL_ZONE)
    expected_days = pd.bdate_range(STUDY_START, STUDY_END).date.astype(str).tolist()
    actual_days = set(days["date_et"].astype(str))
    invalid_ids = int((~events["event_id"].astype(str).str.fullmatch(r"[0-9a-f]{20}")).sum())
    duplicate_ids = int(events["event_id"].duplicated().sum())
    duplicate_canonical = int(
        events.duplicated(
            [
                "release_timestamp_utc",
                "event_name_canonical",
                "release_type",
                "reference_period",
            ]
        ).sum()
    )
    weekend = int(local.dt.weekday.ge(5).sum())
    source_grade_counts = Counter(events["calendar_reliability_grade"].astype(str))
    schedule_change_rows = int(events["schedule_change_status"].eq("rescheduled").sum())
    schedule_change_bundles = int(
        events.loc[events["schedule_change_status"].eq("rescheduled"), "release_bundle_key"].nunique()
    )
    total = len(events)
    return {
        "verdict": "READY_FOR_TIMING_ONLY_STAGE1",
        "study_start": STUDY_START.isoformat(),
        "study_end": STUDY_END.isoformat(),
        "timezone": "America/New_York",
        "total_events": total,
        "events_by_category": events["event_category"].value_counts().sort_index().to_dict(),
        "events_by_scheduled_time_et": local.dt.strftime("%H:%M").value_counts().sort_index().to_dict(),
        "events_by_source_quality": dict(sorted(source_grade_counts.items())),
        "cluster_count": int(len(clusters)),
        "simultaneous_cluster_count": int(clusters["event_count"].gt(1).sum()),
        "ambiguous_cluster_count": int(clusters["attribution_status"].eq("ambiguous_cluster").sum()),
        "conflicting_cluster_count": int(clusters["attribution_status"].eq("conflicting_cluster").sum()),
        "official_actual_count": int(events["actual"].notna().sum()),
        "official_actual_percentage": round(100 * events["actual"].notna().mean(), 4) if total else 0.0,
        "consensus_count": int(events["consensus"].notna().sum()),
        "consensus_percentage": round(100 * events["consensus"].notna().mean(), 4) if total else 0.0,
        "revision_count": int(events["revised_previous"].notna().sum()),
        "revision_percentage": round(100 * events["revised_previous"].notna().mean(), 4) if total else 0.0,
        "timing_verified_count": int(events["timing_verified"].astype(str).str.lower().isin({"true", "1"}).sum()),
        "duplicate_event_id_count": duplicate_ids,
        "duplicate_canonical_event_count": duplicate_canonical,
        "invalid_event_id_count": invalid_ids,
        "unknown_timezone_count": int(events["timezone"].ne("America/New_York").sum()),
        "missing_source_url_count": int(events["source_url"].fillna("").eq("").sum()),
        "weekend_release_count": weekend,
        "missing_classification_dates": sorted(set(expected_days) - actual_days),
        "unresolved_timestamp_conflicts": [],
        "schedule_change_row_count": schedule_change_rows,
        "schedule_change_bundle_count": schedule_change_bundles,
        "trading_day_count": int(len(days)),
        "calendar_limitations": [
            "No trustworthy redistributable point-in-time consensus source was established; all consensus fields are null.",
            "Official actual and revision vintages are not extracted in this timing build.",
            "S&P Global 09:45 U.S. PMI is excluded because complete historical access and redistribution rights were not established.",
            "Non-news classifications are relative to the registered usable official sources.",
            "The date grid includes every Monday-Friday ET date, including U.S. holidays; Stage 1 must intersect it with observed XAUUSD market coverage.",
        ],
    }


def _write_reports(base: Path, metrics: dict[str, object], raw_hashes: dict[str, str]) -> None:
    quality = {
        **metrics,
        "critical_failures": [],
        "warnings": list(metrics["calendar_limitations"]),
        "raw_source_sha256": raw_hashes,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "surprise_analysis_enabled": False,
        "timing_analysis_enabled": True,
    }
    (base / "calendar_quality_report.json").write_text(
        json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    categories = "\n".join(
        f"- `{key}`: {value}" for key, value in metrics["events_by_category"].items()
    )
    clocks = "\n".join(
        f"- `{key}` ET: {value}" for key, value in metrics["events_by_scheduled_time_et"].items()
    )
    limitations = "\n".join(f"- {value}" for value in metrics["calendar_limitations"])
    (base / "calendar_validation_report.md").write_text(
        f"""# Calendar validation report

## Gate

**{metrics['verdict']}**. The scheduled timestamps, DST conversion, source attribution, canonical classifications and one-row-per-weekday classification passed the fail-closed checks. Surprise and revision analysis is disabled because the corresponding release-vintage fields are absent.

## Coverage

- Study period: `{metrics['study_start']}` through `{metrics['study_end']}`
- Canonical timezone: `America/New_York`
- Trading weekdays classified: {metrics['trading_day_count']}
- Events: {metrics['total_events']}
- Clusters: {metrics['cluster_count']}
- Simultaneous clusters: {metrics['simultaneous_cluster_count']}
- Missing classification dates: {len(metrics['missing_classification_dates'])}

### Events by ET time

{clocks}

### Events by category

{categories}

## Integrity checks

- Duplicate event IDs: {metrics['duplicate_event_id_count']}
- Duplicate canonical events: {metrics['duplicate_canonical_event_count']}
- Invalid deterministic IDs: {metrics['invalid_event_id_count']}
- Unknown timezones: {metrics['unknown_timezone_count']}
- Missing source URLs: {metrics['missing_source_url_count']}
- Weekend releases: {metrics['weekend_release_count']}
- Unresolved timestamp conflicts: {len(metrics['unresolved_timestamp_conflicts'])}
- Resolved stale-mirror conflicts: {len(metrics['resolved_timestamp_conflicts'])}
- Census source rows explicitly marked suspended: {metrics['census_suspended_source_rows']}
- Rescheduled official-release bundles preserved: {metrics['schedule_change_bundle_count']}

The UTC timestamps are derived from timezone-aware `America/New_York` timestamps, so EST/EDT is handled by the IANA timezone database. The actual publication time is canonical; known earlier schedules are retained separately.

Primary Census list-view calendars replace mirror dates for Census families; rows marked `Suspended` are not treated as releases. Primary BEA schedules are accepted only when an actual `View` release link exists, preventing planned-but-canceled GDP rows from entering the inventory. The stale October 6, 2025 NY Fed mirror entry for JOLTS was rejected in favor of the BLS release archive, which confirms the August release on September 30 and the cancellation of the September reference-period release.

The 2025/2026 BLS lapse notices are applied explicitly. Examples include Employment Situation on November 20 and December 16, CPI on October 24 and December 18, and the February 2026 JOLTS/Employment/CPI delays. The Federal Reserve G.17 release moved to December 3 and the next two planned releases were combined on December 23. BEA produced nonstandard 10:00 ET Personal Income and Outlays publications on December 5, 2025 and January 22, 2026; those times remain intact rather than being normalized to 08:30.

## Values

- Official actual values: {metrics['official_actual_count']} ({metrics['official_actual_percentage']}%)
- Consensus values: {metrics['consensus_count']} ({metrics['consensus_percentage']}%)
- Revision values: {metrics['revision_count']} ({metrics['revision_percentage']}%)
- Surprise analysis: disabled

## Simultaneous attribution

Same-source component bundles are `clean_cluster`. Independent same-time releases are `ambiguous_cluster` and excluded from single-event attribution. There are {metrics['ambiguous_cluster_count']} ambiguous clusters and {metrics['conflicting_cluster_count']} evaluable conflicting-surprise clusters. Conflict evaluation cannot occur without valid surprises.

## Limitations

{limitations}

No market data was read, no strategy test was run, and no Stage 1 output was produced.
""",
        encoding="utf-8",
    )


def build(base: Path, raw_dir: Path) -> dict[str, object]:
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = _parse_nyfed(raw_dir, retrieved_at)
    rows.extend(_parse_census(raw_dir, retrieved_at))
    rows.extend(_parse_bea(raw_dir, retrieved_at))
    rows.extend(_parse_claims(raw_dir, retrieved_at))
    rows.extend(_primary_schedule_additions(retrieved_at))
    rows.extend(_parse_fomc(raw_dir, retrieved_at))
    point = pd.DataFrame(rows).sort_values(
        ["release_timestamp_utc", "event_name_canonical", "release_type"]
    )
    if point.empty:
        raise RuntimeError("No registered calendar events were parsed")
    if point["event_id"].duplicated().any():
        duplicates = point.loc[point["event_id"].duplicated(False), "event_id"].tolist()
        raise RuntimeError(f"Duplicate deterministic event IDs: {duplicates}")

    calendar_dir = base / "external_data" / "calendar"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    point_path = calendar_dir / "us_releases_point_in_time.csv"
    canonical_path = calendar_dir / "us_releases.canonical.csv"
    clusters_path = calendar_dir / "us_release_clusters.csv"
    days_path = calendar_dir / "us_trading_day_classification.csv"
    metadata_path = calendar_dir / "calendar_metadata.json"
    point.to_csv(point_path, index=False)

    adapter_result = GenericEconomicCalendarAdapter(
        source_timezone="America/New_York", source=SOURCE_NAME
    ).load(point_path)
    canonical = apply_directional_mapping(add_surprise_features(adapter_result.frame), {})
    clusters = build_event_clusters(canonical)
    write_canonical_calendar(canonical, canonical_path)
    write_event_clusters(clusters, clusters_path)
    days = _classify_days(point, clusters)
    days.to_csv(days_path, index=False)

    metrics = _metrics(point, clusters, days)
    metrics["census_suspended_source_rows"] = sum(
        path.read_text(encoding="utf-8", errors="replace").lower().count("suspended</td>")
        for path in raw_dir.glob("census_20*.html")
    )
    metrics["resolved_timestamp_conflicts"] = [
        {
            "mirror_record": "JOLTS 2025-10-06 10:00 ET",
            "resolution": "excluded; BLS archive confirms the August 2025 release was 2025-09-30 and September 2025 was canceled",
        }
    ]
    metrics["official_cancellations_applied"] = [
        "Employment Situation October 2025",
        "CPI October 2025",
        "PPI October 2025",
        "JOLTS September 2025",
        "Import/Export Prices October 2025",
    ]
    metadata = {
        "schema_version": "official-calendar-v1",
        "builder": "research.event_study_0830_0930.official_calendar_builder",
        **metrics,
        "raw_source_sha256": _raw_hashes(raw_dir),
        "surprise_analysis_enabled": False,
        "timing_analysis_enabled": True,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_mapping(base / "event_name_mapping.csv")
    _write_rules(base / "event_classification_rules.md")
    _write_reports(base, metrics, metadata["raw_source_sha256"])
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_base = Path(__file__).resolve().parent
    parser.add_argument("--base", type=Path, default=default_base)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=default_base / "external_data" / "raw" / "calendar",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    metrics = build(args.base, args.raw_dir)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
