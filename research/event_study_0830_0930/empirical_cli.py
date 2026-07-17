"""Command line entrypoint for isolated empirical-data preparation and Stage 1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .data_validation import (
    DataQualityError,
    ValidationThresholds,
    refuse_on_critical,
    validate_market_data,
    write_quality_reports,
)
from .economic_calendar_adapter import (
    EconomicCalendarError,
    add_surprise_features,
    apply_directional_mapping,
    get_calendar_adapter,
    read_direction_mapping_json,
    write_canonical_calendar,
)
from .event_cluster_builder import build_event_clusters, write_event_clusters
from .market_data_adapter import (
    MarketDataError,
    get_market_adapter,
    read_mapping_json,
    tick_to_minute_bars,
    write_canonical_market,
)
from .stage1 import run_stage1


MARKET_ADAPTERS = ("generic-csv", "broker-csv", "mt5", "dukascopy", "parquet")
CALENDAR_ADAPTERS = ("generic-csv", "broker-csv", "mt5", "parquet")


def _add_market_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True)
    parser.add_argument("--adapter", choices=MARKET_ADAPTERS, required=True)
    parser.add_argument("--mode", choices=("bars", "ticks"), required=True)
    parser.add_argument("--source-timezone")
    parser.add_argument("--source", help="Required when the input has no source column")
    parser.add_argument("--symbol", help="Required when the input has no symbol column")
    parser.add_argument("--column-mapping-json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Isolated XAUUSD high-frequency empirical-data pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    market = subparsers.add_parser("import-market", help="normalize market data to UTC")
    _add_market_source_arguments(market)
    market.add_argument("--output", required=True, help="Canonical one-minute bid/ask output")
    market.add_argument("--ticks-output", help="Optional canonical tick output when mode=ticks")
    market.add_argument("--metadata-output", required=True)

    calendar = subparsers.add_parser("import-calendar", help="normalize release history")
    calendar.add_argument("--input", required=True)
    calendar.add_argument("--adapter", choices=CALENDAR_ADAPTERS, required=True)
    calendar.add_argument("--source-timezone", default="America/New_York")
    calendar.add_argument("--source", help="Required when the input has no source column")
    calendar.add_argument("--column-mapping-json")
    calendar.add_argument("--direction-mapping-json")
    calendar.add_argument("--events-output", required=True)
    calendar.add_argument("--clusters-output", required=True)
    calendar.add_argument("--metadata-output", required=True)

    validate = subparsers.add_parser("validate", help="write reports and fail on critical defects")
    validate.add_argument("--market", required=True, help="Canonical one-minute bid/ask data")
    validate.add_argument("--calendar", required=True, help="Canonical economic releases")
    validate.add_argument("--quality-json", required=True)
    validate.add_argument("--quality-md", required=True)
    validate.add_argument("--thresholds-json")

    stage1 = subparsers.add_parser("stage1", help="run timing/volatility study only")
    stage1.add_argument("--market", required=True, help="Canonical one-minute bid/ask data")
    stage1.add_argument("--calendar", required=True, help="Canonical economic releases")
    stage1.add_argument("--output", required=True)
    stage1.add_argument("--thresholds-json")
    return parser


def _load_canonical_market(path: str):
    suffix = Path(path).suffix.lower()
    adapter_name = "parquet" if suffix == ".parquet" else "generic-csv"
    return get_market_adapter(
        adapter_name,
        mode="bars",
        source_timezone=None,
        source=None,
        symbol=None,
    ).load(path).frame


def _load_canonical_events(path: str):
    suffix = Path(path).suffix.lower()
    adapter_name = "parquet" if suffix == ".parquet" else "generic-csv"
    return get_calendar_adapter(
        adapter_name,
        source_timezone=None,
        source=None,
    ).load(path).frame


def _write_metadata(metadata: dict, path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_thresholds(path: str | None) -> ValidationThresholds:
    if path is None:
        return ValidationThresholds()
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise DataQualityError("Threshold configuration must be a JSON object")
    if "known_closure_intervals_utc" in values:
        values["known_closure_intervals_utc"] = tuple(
            tuple(interval) for interval in values["known_closure_intervals_utc"]
        )
    try:
        return ValidationThresholds(**values)
    except (TypeError, ValueError) as exc:
        raise DataQualityError(f"Invalid validation threshold configuration: {exc}") from exc


def _run_import_market(args: argparse.Namespace) -> None:
    result = get_market_adapter(
        args.adapter,
        mode=args.mode,
        source_timezone=args.source_timezone,
        source=args.source,
        symbol=args.symbol,
        column_mapping=read_mapping_json(args.column_mapping_json),
    ).load(args.input)
    if args.mode == "ticks":
        if args.ticks_output:
            write_canonical_market(result.frame, args.ticks_output)
        aggregate = tick_to_minute_bars(result.frame)
        write_canonical_market(aggregate.frame, args.output)
        metadata = {"adapter": result.metadata, "aggregation": aggregate.metadata}
    else:
        write_canonical_market(result.frame, args.output)
        metadata = {"adapter": result.metadata, "aggregation": None}
    _write_metadata(metadata, args.metadata_output)


def _run_import_calendar(args: argparse.Namespace) -> None:
    mapping = read_mapping_json(args.column_mapping_json)
    result = get_calendar_adapter(
        args.adapter,
        source_timezone=args.source_timezone,
        source=args.source,
        column_mapping=mapping,
    ).load(args.input)
    events = add_surprise_features(result.frame)
    events = apply_directional_mapping(
        events, read_direction_mapping_json(args.direction_mapping_json)
    )
    clusters = build_event_clusters(events)
    write_canonical_calendar(events, args.events_output)
    write_event_clusters(clusters, args.clusters_output)
    total = len(events)
    actual_count = int(events["actual"].notna().sum())
    consensus_count = int(events["consensus"].notna().sum())
    revision_count = int(events["revised_previous"].notna().sum())
    timing_verified = events.get("timing_verified")
    timing_verified_count = (
        int(timing_verified.astype(str).str.lower().isin({"true", "1"}).sum())
        if timing_verified is not None
        else 0
    )
    metadata = {
        **result.metadata,
        "schema_version": "official-calendar-v1",
        "study_start_new_york": events["release_timestamp_new_york"].min().date().isoformat(),
        "study_end_new_york": events["release_timestamp_new_york"].max().date().isoformat(),
        "timing_verified_count": timing_verified_count,
        "official_actual_count": actual_count,
        "official_actual_percentage": round(100 * actual_count / total, 4) if total else 0.0,
        "consensus_count": consensus_count,
        "consensus_percentage": round(100 * consensus_count / total, 4) if total else 0.0,
        "revision_count": revision_count,
        "revision_percentage": round(100 * revision_count / total, 4) if total else 0.0,
        "source_quality_summary": events.get(
            "calendar_reliability_grade", pd.Series(dtype="object")
        ).value_counts().sort_index().to_dict(),
        "research_gate": (
            "READY_FOR_STAGE1"
            if actual_count == total and consensus_count == total and total
            else "READY_FOR_TIMING_ONLY_STAGE1"
        ),
        "surprise_analysis_enabled": bool(actual_count and consensus_count),
        "timing_analysis_enabled": bool(timing_verified_count == total and total),
        "calendar_limitations": [
            "No point-in-time consensus values are present; surprise analysis is disabled."
            if consensus_count == 0
            else "",
            "S&P Global 09:45 PMI is excluded from the registered usable-source calendar.",
        ],
        "surprise_eligible_count": int(events["surprise_eligible"].sum()),
        "event_cluster_count": int(len(clusters)),
        "collision_cluster_count": int(clusters["event_count"].gt(1).sum()),
        "event_specific_exclusion_count": int(
            clusters["exclude_event_specific_analysis"].sum()
        ),
        "direction_mapping_supplied": bool(args.direction_mapping_json),
    }
    _write_metadata(metadata, args.metadata_output)


def _run_validate(args: argparse.Namespace) -> None:
    market = _load_canonical_market(args.market)
    events = _load_canonical_events(args.calendar)
    clusters = build_event_clusters(events)
    report = validate_market_data(
        market, event_clusters=clusters, thresholds=_load_thresholds(args.thresholds_json)
    )
    write_quality_reports(report, args.quality_json, args.quality_md)
    refuse_on_critical(report)


def _run_stage1(args: argparse.Namespace) -> None:
    market = _load_canonical_market(args.market)
    events = _load_canonical_events(args.calendar)
    day_path = Path(args.calendar).with_name("us_trading_day_classification.csv")
    day_classification = pd.read_csv(day_path) if day_path.exists() else None
    run_stage1(
        market,
        events,
        args.output,
        thresholds=(
            _load_thresholds(args.thresholds_json) if args.thresholds_json else None
        ),
        day_classification=day_classification,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import-market":
            _run_import_market(args)
        elif args.command == "import-calendar":
            _run_import_calendar(args)
        elif args.command == "validate":
            _run_validate(args)
        elif args.command == "stage1":
            _run_stage1(args)
        else:  # pragma: no cover
            raise RuntimeError(f"Unhandled command: {args.command}")
    except (MarketDataError, EconomicCalendarError, DataQualityError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
