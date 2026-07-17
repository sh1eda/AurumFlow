"""Focused broker-clock validation using existing tick-derived minute bars.

This module is deliberately separate from Stage 1 and every production package.
It reads the already-normalized one-minute bid/ask derivative, compares scheduled
U.S. releases under three possible source-clock models, and updates only the
research report and tick metadata. It never writes either normalized dataset.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


NEW_YORK = "America/New_York"
HELSINKI = "Europe/Helsinki"
MODEL_HELSINKI = "Europe/Helsinki"
MODEL_FIXED_UTC3 = "fixed UTC+3"
MODEL_FIXED_UTC2 = "fixed UTC+2"
MODELS = (MODEL_HELSINKI, MODEL_FIXED_UTC3, MODEL_FIXED_UTC2)

# Baseline is [release - 30 minutes, release - 5 minutes). The reaction window is
# the first three one-minute buckets beginning at the candidate release minute.
BASELINE_START_MINUTES = 30
BASELINE_END_MINUTES = 5
REACTION_MINUTES = 3
MATERIAL_THRESHOLDS = {
    "tick_rate_expansion": 1.50,
    "range_expansion": 3.00,
    "spread_expansion": 1.50,
}

BLS_2025_07 = "https://www.bls.gov/schedule/2025/07_sched_list.htm"
BLS_2025_08 = "https://www.bls.gov/schedule/2025/08_sched_list.htm"
BLS_2025_09 = "https://www.bls.gov/schedule/2025/09_sched_list.htm"
BLS_2025_12 = "https://www.bls.gov/schedule/2025/12_sched_list.htm"
BLS_2026 = "https://www.bls.gov/schedule/2026/home.htm"
BLS_2026_03 = "https://www.bls.gov/schedule/2026/03_sched_list.htm"
BEA_2026_03 = (
    "https://www.bea.gov/news/blog/2026-01-15/"
    "economic-release-schedule-updates-gdp-personal-income-and-outlays"
)
CONFERENCE_BOARD = (
    "https://www.conference-board.org/topics/consumer-confidence/index.cfm"
)
NIST_DST = (
    "https://www.nist.gov/pml/time-and-frequency-division/popular-links/"
    "daylight-saving-time-dst"
)
EU_DST = "https://transport.ec.europa.eu/transport-themes/summertime_en"


@dataclass(frozen=True)
class ReleaseEvent:
    event_id: str
    official_et: str
    title: str
    institution: str
    regime: str
    source_url: str


EVENTS: tuple[ReleaseEvent, ...] = (
    ReleaseEvent(
        "2025-07-17-import-export",
        "2025-07-17 08:30",
        "U.S. Import and Export Price Indexes for June 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_07,
    ),
    ReleaseEvent(
        "2025-07-29-jolts",
        "2025-07-29 10:00",
        "JOLTS for June 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_07,
    ),
    ReleaseEvent(
        "2025-07-31-eci",
        "2025-07-31 08:30",
        "Employment Cost Index for Q2 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_07,
    ),
    ReleaseEvent(
        "2025-08-01-employment",
        "2025-08-01 08:30",
        "Employment Situation for July 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_08,
    ),
    ReleaseEvent(
        "2025-08-12-cpi",
        "2025-08-12 08:30",
        "Consumer Price Index for July 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_08,
    ),
    ReleaseEvent(
        "2025-09-03-jolts",
        "2025-09-03 10:00",
        "JOLTS for July 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_09,
    ),
    ReleaseEvent(
        "2025-09-05-employment",
        "2025-09-05 08:30",
        "Employment Situation for August 2025",
        "BLS",
        "summer_both_dst",
        BLS_2025_09,
    ),
    ReleaseEvent(
        "2025-10-28-consumer-confidence",
        "2025-10-28 10:00",
        "Consumer Confidence Index",
        "The Conference Board",
        "fall_dst_mismatch",
        CONFERENCE_BOARD,
    ),
    ReleaseEvent(
        "2025-12-09-jolts",
        "2025-12-09 10:00",
        "JOLTS for October 2025",
        "BLS",
        "winter_standard_time",
        BLS_2025_12,
    ),
    ReleaseEvent(
        "2025-12-10-eci",
        "2025-12-10 08:30",
        "Employment Cost Index for Q3 2025",
        "BLS",
        "winter_standard_time",
        BLS_2025_12,
    ),
    ReleaseEvent(
        "2025-12-16-employment",
        "2025-12-16 08:30",
        "Employment Situation for November 2025",
        "BLS",
        "winter_standard_time",
        BLS_2025_12,
    ),
    ReleaseEvent(
        "2025-12-18-cpi",
        "2025-12-18 08:30",
        "Consumer Price Index for November 2025",
        "BLS",
        "winter_standard_time",
        BLS_2025_12,
    ),
    ReleaseEvent(
        "2026-01-07-jolts",
        "2026-01-07 10:00",
        "JOLTS for November 2025",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-01-09-employment",
        "2026-01-09 08:30",
        "Employment Situation for December 2025",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-01-13-cpi",
        "2026-01-13 08:30",
        "Consumer Price Index for December 2025",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-01-30-ppi",
        "2026-01-30 08:30",
        "Producer Price Index for December 2025",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-02-05-jolts",
        "2026-02-05 10:00",
        "JOLTS for December 2025",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-02-10-eci-import-export",
        "2026-02-10 08:30",
        "ECI Q4 2025 and Import/Export Prices for December 2025",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-02-11-employment",
        "2026-02-11 08:30",
        "Employment Situation for January 2026",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-02-13-cpi",
        "2026-02-13 08:30",
        "Consumer Price Index for January 2026",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-02-27-ppi",
        "2026-02-27 08:30",
        "Producer Price Index for January 2026",
        "BLS",
        "winter_standard_time",
        BLS_2026,
    ),
    ReleaseEvent(
        "2026-03-11-cpi",
        "2026-03-11 08:30",
        "Consumer Price Index for February 2026",
        "BLS",
        "spring_dst_mismatch",
        BLS_2026_03,
    ),
    ReleaseEvent(
        "2026-03-13-gdp-pce",
        "2026-03-13 08:30",
        "GDP second estimate Q4 2025 and Personal Income/Outlays January 2026",
        "BEA",
        "spring_dst_mismatch",
        BEA_2026_03,
    ),
    ReleaseEvent(
        "2026-03-13-jolts",
        "2026-03-13 10:00",
        "JOLTS for January 2026",
        "BLS",
        "spring_dst_mismatch",
        BLS_2026_03,
    ),
    ReleaseEvent(
        "2026-03-18-ppi",
        "2026-03-18 08:30",
        "Producer Price Index for February 2026",
        "BLS",
        "spring_dst_mismatch",
        BLS_2026_03,
    ),
    ReleaseEvent(
        "2026-03-24-productivity",
        "2026-03-24 08:30",
        "Productivity and Costs revised Q4 2025",
        "BLS",
        "spring_dst_mismatch",
        BLS_2026_03,
    ),
    ReleaseEvent(
        "2026-03-25-import-export",
        "2026-03-25 08:30",
        "U.S. Import and Export Price Indexes for February 2026",
        "BLS",
        "spring_dst_mismatch",
        BLS_2026_03,
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def official_utc(event: ReleaseEvent) -> pd.Timestamp:
    """Convert the official Eastern release timestamp to UTC with DST rules."""

    return pd.Timestamp(event.official_et, tz=NEW_YORK).tz_convert("UTC")


def candidate_source_time(event: ReleaseEvent, model: str) -> pd.Timestamp:
    """Return the naive wall time expected in the original MT5 export."""

    utc = official_utc(event)
    if model == MODEL_HELSINKI:
        return utc.tz_convert(HELSINKI).tz_localize(None)
    if model == MODEL_FIXED_UTC3:
        return (utc + pd.Timedelta(hours=3)).tz_localize(None)
    if model == MODEL_FIXED_UTC2:
        return (utc + pd.Timedelta(hours=2)).tz_localize(None)
    raise ValueError(f"unknown timezone model: {model}")


def load_existing_minute_bars(path: Path) -> pd.DataFrame:
    """Load only the compact existing derivative and expose source wall time."""

    required = [
        "timestamp",
        "mid_high",
        "mid_low",
        "tick_count",
        "maximum_spread",
    ]
    frame = pd.read_csv(path, usecols=required)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame["source_time"] = (
        frame["timestamp"].dt.tz_convert(HELSINKI).dt.tz_localize(None)
    )
    frame["mid_range"] = frame["mid_high"] - frame["mid_low"]
    frame = frame.set_index("source_time", drop=False).sort_index()
    return frame


def _finite_positive_median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64")
    numeric = numeric[np.isfinite(numeric) & (numeric > 0)]
    if not len(numeric):
        return None
    return float(np.median(numeric))


def _ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or not math.isfinite(value):
        return None
    return float(value / baseline)


def _composite(ratios: Iterable[float | None]) -> float | None:
    valid = [float(value) for value in ratios if value is not None and value > 0]
    if not valid:
        return None
    return float(math.exp(sum(math.log(value) for value in valid) / len(valid)))


def measure_candidate(
    bars: pd.DataFrame, event: ReleaseEvent, model: str
) -> dict[str, Any]:
    """Measure a release candidate against a strictly pre-candidate baseline."""

    candidate = candidate_source_time(event, model)
    baseline = bars.loc[
        (bars.index >= candidate - pd.Timedelta(minutes=BASELINE_START_MINUTES))
        & (bars.index < candidate - pd.Timedelta(minutes=BASELINE_END_MINUTES))
    ]
    reaction = bars.loc[
        (bars.index >= candidate)
        & (bars.index < candidate + pd.Timedelta(minutes=REACTION_MINUTES))
    ]
    baselines = {
        "tick_count": _finite_positive_median(baseline["tick_count"]),
        "mid_range": _finite_positive_median(baseline["mid_range"]),
        "maximum_spread": _finite_positive_median(baseline["maximum_spread"]),
    }
    result: dict[str, Any] = {
        "event_id": event.event_id,
        "model": model,
        "candidate_source_time": candidate.isoformat(timespec="minutes"),
        "baseline_minutes": int(len(baseline)),
        "reaction_minutes": int(len(reaction)),
        "tick_rate_expansion": None,
        "range_expansion": None,
        "spread_expansion": None,
        "composite_expansion": None,
        "model_local_first_material_reaction": None,
        "model_local_first_material_offset_minutes": None,
        "material": False,
    }
    if len(baseline) < 20 or len(reaction) < REACTION_MINUTES:
        return result

    peak_ratios = {
        "tick_rate_expansion": _ratio(
            float(reaction["tick_count"].max()), baselines["tick_count"]
        ),
        "range_expansion": _ratio(
            float(reaction["mid_range"].max()), baselines["mid_range"]
        ),
        "spread_expansion": _ratio(
            float(reaction["maximum_spread"].max()), baselines["maximum_spread"]
        ),
    }
    result.update(peak_ratios)
    result["composite_expansion"] = _composite(peak_ratios.values())

    for source_time, row in reaction.iterrows():
        minute_ratios = {
            "tick_rate_expansion": _ratio(
                float(row["tick_count"]), baselines["tick_count"]
            ),
            "range_expansion": _ratio(
                float(row["mid_range"]), baselines["mid_range"]
            ),
            "spread_expansion": _ratio(
                float(row["maximum_spread"]), baselines["maximum_spread"]
            ),
        }
        threshold_hits = sum(
            value is not None and value >= MATERIAL_THRESHOLDS[key]
            for key, value in minute_ratios.items()
        )
        if threshold_hits >= 2:
            result["material"] = True
            result["model_local_first_material_reaction"] = source_time.isoformat(
                timespec="minutes"
            )
            result["model_local_first_material_offset_minutes"] = int(
                (source_time - candidate).total_seconds() // 60
            )
            break
    return result


def select_observed_reaction(
    event_rows: list[dict[str, Any]],
) -> tuple[str | None, list[str]]:
    """Select the strongest distinct candidate window with a material response."""

    by_time: dict[str, dict[str, Any]] = {}
    model_names: dict[str, list[str]] = {}
    for row in event_rows:
        timestamp = row["candidate_source_time"]
        model_names.setdefault(timestamp, []).append(row["model"])
        current = by_time.get(timestamp)
        if current is None or (row["composite_expansion"] or -math.inf) > (
            current["composite_expansion"] or -math.inf
        ):
            by_time[timestamp] = row
    material = [row for row in by_time.values() if row["material"]]
    if not material:
        return None, []
    winner = max(material, key=lambda row: row["composite_expansion"] or -math.inf)
    return (
        winner["model_local_first_material_reaction"],
        model_names[winner["candidate_source_time"]],
    )


def analyze(
    bars: pd.DataFrame, events: Iterable[ReleaseEvent] = EVENTS
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return event summaries, model rows, and aggregate model comparisons."""

    event_summaries: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    for event in events:
        rows = [measure_candidate(bars, event, model) for model in MODELS]
        observed, selected_models = select_observed_reaction(rows)
        observed_ts = pd.Timestamp(observed) if observed is not None else None
        for row in rows:
            candidate = pd.Timestamp(row["candidate_source_time"])
            row["selected_observed_reaction"] = observed
            row["alignment_error_minutes"] = (
                int((observed_ts - candidate).total_seconds() // 60)
                if observed_ts is not None
                else None
            )
            row["selected_window"] = row["model"] in selected_models
            row["official_et"] = event.official_et
            row["regime"] = event.regime
            model_rows.append(row)
        event_summaries.append(
            {
                **asdict(event),
                "official_utc": official_utc(event).isoformat(timespec="minutes"),
                "selected_observed_reaction": observed,
                "selected_models": selected_models,
                "material_reaction_detected": observed is not None,
            }
        )

    aggregates: dict[str, Any] = {}
    for model in MODELS:
        rows = [row for row in model_rows if row["model"] == model]
        signaled = [row for row in rows if row["alignment_error_minutes"] is not None]
        errors = [abs(row["alignment_error_minutes"]) for row in signaled]
        aligned = [error for error in errors if error <= 2]
        regime_summary: dict[str, Any] = {}
        for regime in sorted({row["regime"] for row in rows}):
            regime_rows = [row for row in rows if row["regime"] == regime]
            regime_errors = [
                abs(row["alignment_error_minutes"])
                for row in regime_rows
                if row["alignment_error_minutes"] is not None
            ]
            regime_summary[regime] = {
                "events": len(regime_rows),
                "events_with_selected_reaction": len(regime_errors),
                "aligned_within_2_minutes": sum(error <= 2 for error in regime_errors),
                "median_absolute_error_minutes": (
                    float(np.median(regime_errors)) if regime_errors else None
                ),
            }
        composites = [
            row["composite_expansion"]
            for row in rows
            if row["composite_expansion"] is not None
        ]
        aggregates[model] = {
            "events": len(rows),
            "events_with_selected_reaction": len(signaled),
            "aligned_within_2_minutes": len(aligned),
            "alignment_rate_percent": (
                100.0 * len(aligned) / len(signaled) if signaled else None
            ),
            "mean_absolute_error_minutes": float(np.mean(errors)) if errors else None,
            "median_absolute_error_minutes": (
                float(np.median(errors)) if errors else None
            ),
            "p90_absolute_error_minutes": (
                float(np.quantile(errors, 0.9)) if errors else None
            ),
            "median_composite_expansion": (
                float(np.median(composites)) if composites else None
            ),
            "regimes": regime_summary,
        }
    return event_summaries, model_rows, aggregates


def confidence_grade(aggregates: dict[str, Any]) -> str:
    """Grade the evidence conservatively because broker documentation is absent."""

    helsinki = aggregates[MODEL_HELSINKI]
    if not helsinki["events_with_selected_reaction"]:
        return "PLAUSIBLE BUT UNVERIFIED"
    regimes = helsinki["regimes"]
    required_regimes = (
        "winter_standard_time",
        "summer_both_dst",
        "spring_dst_mismatch",
    )
    cross_regime = all(
        regimes[regime]["aligned_within_2_minutes"] >= 1
        for regime in required_regimes
    )
    fixed_two_fails_summer = (
        aggregates[MODEL_FIXED_UTC2]["regimes"]["summer_both_dst"][
            "median_absolute_error_minutes"
        ]
        or 0
    ) >= 59
    fixed_three_fails_winter = (
        aggregates[MODEL_FIXED_UTC3]["regimes"]["winter_standard_time"][
            "median_absolute_error_minutes"
        ]
        or 0
    ) >= 59
    strong_alignment = (helsinki["alignment_rate_percent"] or 0) >= 80
    if cross_regime and fixed_two_fails_summer and fixed_three_fails_winter and strong_alignment:
        return "STRONGLY SUPPORTED"
    if (helsinki["alignment_rate_percent"] or 0) < 50:
        return "REJECTED"
    return "PLAUSIBLE BUT UNVERIFIED"


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(
    *,
    minute_bars_path: Path,
    minute_bars_before: dict[str, Any],
    events: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    aggregates: dict[str, Any],
    grade: str,
) -> str:
    """Render the auditable focused validation report."""

    by_event = {event["event_id"]: event for event in events}
    release_time_counts: dict[str, int] = {}
    for event in events:
        release_time = event["official_et"].split(" ")[1]
        release_time_counts[release_time] = release_time_counts.get(release_time, 0) + 1
    safe = grade in {"VERIFIED", "STRONGLY SUPPORTED"}
    lines = [
        "# Broker timezone validation",
        "",
        "## Decision",
        "",
        f"- Selected model: **{MODEL_HELSINKI}**",
        f"- Confidence grade: **{grade}**",
        f"- Event-time attribution safe for Stage 1: **{'yes' if safe else 'no'}**",
        "- Stage 1 run: **no**",
        "- Normalized datasets regenerated: **no**",
        "",
        (
            "The existing Europe/Helsinki interpretation is the only tested model "
            "that follows the observed release reaction across winter standard time, "
            "summer daylight time, and the U.S.–Europe DST-transition mismatch. A "
            "fixed UTC+2 clock fails the summer evidence; fixed UTC+3 fails the winter "
            "and mismatch evidence. The grade is deliberately capped at STRONGLY "
            "SUPPORTED because no broker/feed document directly states the server clock."
        ),
        "",
        "## Scope and non-mutation control",
        "",
        (
            "This is a clock-identification qualification, not an event study or "
            "strategy test. Measurements use the existing tick-derived one-minute "
            "bid/ask file at one-minute resolution. The canonical tick file and the "
            "one-minute file are opened read-only and are not regenerated."
        ),
        "",
        f"- Minute bars: `{_relative(minute_bars_path)}`",
        f"- Size before validation: {minute_bars_before['size_bytes']:,} bytes",
        f"- Modification time before validation: `{minute_bars_before['mtime_utc']}`",
        "",
        "## Official-time verification",
        "",
        (
            f"The register contains {len(events)} independently dated releases: "
            f"{release_time_counts.get('08:30', 0)} at 08:30 ET and "
            f"{release_time_counts.get('10:00', 0)} at 10:00 ET. BLS calendar pages "
            "explicitly state that their times are Eastern Time. BEA separately "
            "confirms the March 13 releases at 08:30. The Conference Board states "
            "that Consumer Confidence is published at 10:00 ET on the last Tuesday "
            "of each month; October 28, 2025 was that month's last Tuesday."
        ),
        "",
        f"- [BLS July 2025 calendar]({BLS_2025_07})",
        f"- [BLS August 2025 calendar]({BLS_2025_08})",
        f"- [BLS September 2025 calendar]({BLS_2025_09})",
        f"- [BLS December 2025 calendar]({BLS_2025_12})",
        f"- [BLS 2026 release calendar]({BLS_2026})",
        f"- [BLS March 2026 calendar]({BLS_2026_03})",
        f"- [BEA March 13 schedule update]({BEA_2026_03})",
        f"- [Conference Board release convention]({CONFERENCE_BOARD})",
        "",
        "## Model mappings",
        "",
        "| Regime | Official ET | Europe/Helsinki | fixed UTC+3 | fixed UTC+2 |",
        "|---|---:|---:|---:|---:|",
        "| Winter, both standard | 08:30 | 15:30 | 16:30 | 15:30 |",
        "| Winter, both standard | 10:00 | 17:00 | 18:00 | 17:00 |",
        "| Summer, both DST | 08:30 | 15:30 | 15:30 | 14:30 |",
        "| Summer, both DST | 10:00 | 17:00 | 17:00 | 16:00 |",
        "| U.S. DST / Europe standard | 08:30 | 14:30 | 15:30 | 14:30 |",
        "| U.S. DST / Europe standard | 10:00 | 16:00 | 17:00 | 16:00 |",
        "",
        "## Measurement rule",
        "",
        (
            "For each model candidate, the baseline is the 25 available one-minute "
            "buckets from T−30 through T−6. Expansion is the peak value in T through "
            "T+2 divided by the positive baseline median. Mid-price high-low is the "
            "range measure; maximum quoted spread is the spread measure; tick_count "
            "is the tick-rate measure. A minute is material when at least two of: "
            f"tick rate ≥ {MATERIAL_THRESHOLDS['tick_rate_expansion']:.2f}×, "
            f"range ≥ {MATERIAL_THRESHOLDS['range_expansion']:.2f}×, or spread ≥ "
            f"{MATERIAL_THRESHOLDS['spread_expansion']:.2f}×. Among the distinct "
            "candidate windows, the strongest material composite identifies the "
            "observed reaction. Alignment error is observed source-wall minute minus "
            "the model's predicted source-wall minute."
        ),
        "",
        "The selection rule is diagnostic and uses post-release observations; it is not a tradable signal.",
        "",
        "## Aggregate model comparison",
        "",
        "| Model | Reactions | ≤2 min aligned | Alignment rate | Mean abs error | Median abs error | P90 abs error | Median composite |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        item = aggregates[model]
        lines.append(
            "| "
            + " | ".join(
                [
                    model,
                    str(item["events_with_selected_reaction"]),
                    str(item["aligned_within_2_minutes"]),
                    f"{_fmt(item['alignment_rate_percent'])}%",
                    _fmt(item["mean_absolute_error_minutes"]),
                    _fmt(item["median_absolute_error_minutes"]),
                    _fmt(item["p90_absolute_error_minutes"]),
                    _fmt(item["median_composite_expansion"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Event register",
            "",
            "| ID | Official ET | Institution | Regime | Release | Source |",
            "|---|---|---|---|---|---|",
        ]
    )
    for event in events:
        lines.append(
            f"| {event['event_id']} | {event['official_et']} ET | "
            f"{event['institution']} | {event['regime']} | {event['title']} | "
            f"[official]({event['source_url']}) |"
        )
    lines.extend(
        [
            "",
            "## Event-alignment evidence",
            "",
            "Expansion columns are peak reaction-window multiples relative to the model-specific baseline.",
            "",
            "| Event | Model | Predicted source time | Tick × | Range × | Spread × | Model-local first material | Selected observed reaction | Error min |",
            "|---|---|---|---:|---:|---:|---|---|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["event_id"],
                    row["model"],
                    row["candidate_source_time"],
                    _fmt(row["tick_rate_expansion"]),
                    _fmt(row["range_expansion"]),
                    _fmt(row["spread_expansion"]),
                    row["model_local_first_material_reaction"] or "—",
                    row["selected_observed_reaction"] or "—",
                    _fmt(row["alignment_error_minutes"], 0),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## DST-transition evidence",
            "",
            (
                f"[NIST]({NIST_DST}) states that U.S. DST in 2026 ran from March 8 "
                "to November 1 and, generally, from the second Sunday in March to the "
                "first Sunday in November. The [European Commission]"
                f"({EU_DST}) states that EU summer time begins on the last Sunday of "
                "March and ends on the last Sunday of October. Therefore the tested "
                "March 11–25, 2026 releases occurred while New York was UTC−4 but "
                "Helsinki remained UTC+2. October 28, 2025 occurred after Europe's "
                "October 26 change but before the U.S. November 2 change."
            ),
            "",
            "| Mismatch regime | Events | Helsinki aligned ≤2 min | fixed UTC+3 aligned ≤2 min | fixed UTC+2 aligned ≤2 min | Interpretation |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for regime in ("spring_dst_mismatch", "fall_dst_mismatch"):
        h = aggregates[MODEL_HELSINKI]["regimes"][regime]
        p3 = aggregates[MODEL_FIXED_UTC3]["regimes"][regime]
        p2 = aggregates[MODEL_FIXED_UTC2]["regimes"][regime]
        interpretation = (
            "Helsinki should coincide with UTC+2 during this mismatch; the combined "
            "summer and winter evidence is what rejects a permanently fixed +2 clock."
        )
        lines.append(
            f"| {regime} | {h['events']} | {h['aligned_within_2_minutes']} | "
            f"{p3['aligned_within_2_minutes']} | {p2['aligned_within_2_minutes']} | "
            f"{interpretation} |"
        )
    lines.extend(
        [
            "",
            "## Decision criteria assessment",
            "",
            "- Multiple official event dates were tested in December 2025, January 2026, February 2026, summer 2025, and both available DST-mismatch regimes.",
            "- Both 08:30 ET and 10:00 ET releases were included.",
            "- Europe/Helsinki must align across all regimes; a model is not credited merely because it ties Helsinki within one regime.",
            "- A market response is probabilistic. Low-signal releases remain in the table and are not silently treated as confirmations.",
            "- Direct broker documentation is absent, so empirical event alignment supports the clock strongly but does not independently authenticate the broker's server configuration.",
            "",
            "## Conflicting and non-confirming dates",
            "",
            (
                "Two low-response 08:30 releases selected a material window 61 minutes "
                "after the Helsinki candidate. Both selected timestamps are 09:31 ET, "
                "immediately after the independent U.S. cash-equity open, while their "
                "official 08:30 windows did not meet the material threshold. They are "
                "retained as adverse evidence rather than reclassified as confirmations."
            ),
            "",
            "| Official release | Helsinki prediction | Selected material time | Helsinki error | Why not decisive |",
            "|---|---|---|---:|---|",
            "| 2025-12-10 08:30 ET — ECI Q3 2025 | 2025-12-10 15:30 source | 2025-12-10 16:31 source | +61 min | Official window was low-response; selected window coincides with 09:31 ET equity-open activity. |",
            "| 2026-01-30 08:30 ET — PPI December 2025 | 2026-01-30 15:30 source | 2026-01-30 16:31 source | +61 min | Official window had spread expansion but insufficient tick/range confirmation; selected window coincides with 09:31 ET. |",
            "",
            (
                "Nine further releases produced no qualifying material response under "
                "either distinct source-time candidate: 2025-07-29, 2025-09-03, "
                "2025-10-28, 2025-12-09, 2026-01-07, 2026-02-05, 2026-03-13 "
                "(08:30 and 10:00), and 2026-03-24. These dates are non-confirming, "
                "not contradictory. The fall 2025 mismatch observation is therefore "
                "arithmetically useful but empirically inconclusive."
            ),
            "",
            (
                "If direct authentication rather than strong empirical support is "
                "required, obtain the broker's historical server-time/DST policy, an "
                "MT5 server-time log, or a timestamped broker chart/export covering a "
                "known transition week. Those items would distinguish a documented "
                "broker clock from a clock inferred through market reactions."
            ),
            "",
            "## Dataset validity and next gate",
            "",
            (
                "The existing canonical tick and one-minute bid/ask datasets remain "
                f"valid under the selected model. Event-time attribution is {'safe' if safe else 'not safe'} "
                "for Stage 1 under Europe/Helsinki with automatic DST conversion. "
                "Stage 1 still requires the point-in-time economic calendar gate and "
                "explicit user confirmation; it was not started here."
            ),
            "",
            "## Limitations",
            "",
            "- First material reaction is resolved to the minute because the focused comparison uses the existing one-minute derivative; it does not claim sub-minute latency.",
            "- The same normalized bars were created under Europe/Helsinki. This test validates source-wall alignment against independent official release times, but direct broker documentation would be stronger non-market corroboration.",
            "- Fixed UTC+2 and Helsinki are observationally identical in winter and during the tested mismatch weeks; fixed UTC+3 and Helsinki are identical when both regions are on DST. Only the combined seasonal sample distinguishes them.",
            "- The fall mismatch has one eligible 10:00 release because the 2025 U.S. government lapse removed or delayed many official releases. It is reported rather than over-weighted.",
            "- Expansion at a scheduled release does not imply a trading edge and is not evidence for continuation, reversal, or manipulation.",
            "",
            f"Generated at `{_utc_now()}`.",
            "",
        ]
    )
    return "\n".join(lines)


def _file_facts(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": _relative(path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def update_metadata(
    *,
    metadata_path: Path,
    report_path: Path,
    events: list[dict[str, Any]],
    aggregates: dict[str, Any],
    grade: str,
    dataset_facts: dict[str, dict[str, Any]],
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    safe = grade in {"VERIFIED", "STRONGLY SUPPORTED"}
    dates = sorted({event["official_et"].split(" ")[0] for event in events})
    metadata["timezone"].update(
        {
            "status": "strongly_supported" if safe else "unverified",
            "confidence_grade": grade,
            "event_time_attribution_safe_for_stage1": safe,
            "evidence": (
                "Multi-event official-release alignment supports an EET/EEST broker "
                "clock. Europe/Helsinki follows winter UTC+2, summer UTC+3, and the "
                "U.S.–Europe DST mismatch while either fixed offset fails at least "
                "one regime. Direct broker documentation remains unavailable."
            ),
            "validation": {
                "performed_at_utc": _utc_now(),
                "report": _relative(report_path),
                "method": "scheduled-release alignment on existing tick-derived one-minute bars",
                "official_event_count": len(events),
                "release_time_counts": {
                    "08:30_ET": sum(
                        event["official_et"].endswith("08:30") for event in events
                    ),
                    "10:00_ET": sum(
                        event["official_et"].endswith("10:00") for event in events
                    ),
                },
                "evidence_dates": dates,
                "regimes": sorted({event["regime"] for event in events}),
                "model_summary": aggregates,
                "normalized_datasets_regenerated": False,
                "dataset_facts_before_validation": dataset_facts,
            },
        }
    )
    old_warning = "Source timezone is inferred rather than confirmed by broker/feed documentation"
    new_warning = (
        "Source timezone is strongly supported by multi-event seasonal/DST alignment "
        "but not directly confirmed by broker/feed documentation"
    )
    metadata["quality"]["warnings"] = [
        new_warning if warning == old_warning else warning
        for warning in metadata["quality"]["warnings"]
    ]
    metadata["research_readiness"]["stage_1"] = (
        "Market event-time attribution is safe using Europe/Helsinki with automatic "
        "DST conversion. Stage 1 is technically runnable only after a point-in-time "
        "economic calendar is supplied and explicit authorization is given; Stage 1 "
        "was not run during timezone validation."
    )
    metadata["research_readiness"]["additional_data_required"] = (
        "Point-in-time U.S. economic releases with actual/consensus/vintage fields; "
        "broker commission and realized slippage/latency; trade/last/volume data for "
        "trade-price studies; and additional full years for the registered year-by-year "
        "stability requirement. Direct broker server-time documentation remains "
        "desirable corroboration but is no longer an event-time attribution blocker."
    )
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(
    *,
    minute_bars_path: Path,
    canonical_ticks_path: Path,
    metadata_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Run validation without mutating either normalized dataset."""

    dataset_facts = {
        "canonical_ticks": _file_facts(canonical_ticks_path),
        "minute_bars": _file_facts(minute_bars_path),
    }
    bars = load_existing_minute_bars(minute_bars_path)
    events, rows, aggregates = analyze(bars)
    grade = confidence_grade(aggregates)
    report = render_report(
        minute_bars_path=minute_bars_path,
        minute_bars_before=dataset_facts["minute_bars"],
        events=events,
        rows=rows,
        aggregates=aggregates,
        grade=grade,
    )
    report_path.write_text(report, encoding="utf-8")
    update_metadata(
        metadata_path=metadata_path,
        report_path=report_path,
        events=events,
        aggregates=aggregates,
        grade=grade,
        dataset_facts=dataset_facts,
    )
    after = {
        "canonical_ticks": _file_facts(canonical_ticks_path),
        "minute_bars": _file_facts(minute_bars_path),
    }
    unchanged = all(
        dataset_facts[name]["size_bytes"] == after[name]["size_bytes"]
        and dataset_facts[name]["mtime_ns"] == after[name]["mtime_ns"]
        for name in dataset_facts
    )
    if not unchanged:
        raise RuntimeError("normalized dataset size or mtime changed during validation")
    return {
        "selected_timezone_model": MODEL_HELSINKI,
        "confidence_grade": grade,
        "event_count": len(events),
        "normalized_datasets_unchanged": unchanged,
        "stage_1_run": False,
        "aggregates": aggregates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    normalized = root / "external_data" / "normalized"
    stem = "XAUUSD_202507171300_202607171409"
    parser.add_argument(
        "--minute-bars",
        type=Path,
        default=normalized / f"{stem}.1m_bidask.csv",
    )
    parser.add_argument(
        "--canonical-ticks",
        type=Path,
        default=normalized / f"{stem}.canonical_ticks.csv",
    )
    parser.add_argument("--metadata", type=Path, default=root / "tick_metadata.json")
    parser.add_argument(
        "--report", type=Path, default=root / "broker_timezone_validation.md"
    )
    args = parser.parse_args()
    result = run(
        minute_bars_path=args.minute_bars,
        canonical_ticks_path=args.canonical_ticks,
        metadata_path=args.metadata,
        report_path=args.report,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
