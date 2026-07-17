from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import StudyConfig
from .features import build_five_minute_heatmap_data, build_session_features
from .event_tests import run_registered_event_tests
from .io import DataRequirementError, classify_event_days, load_calendar, load_prices
from .lifecycle import classify_lifecycles
from .metrics import grouped_performance, session_bootstrap_expectancy
from .reporting import (
    write_event_study_report,
    write_heatmap_svg,
    write_quality_report,
    write_run_metadata,
)
from .strategies import generate_candidate_orders, simulate_orders


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated XAUUSD 08:30–10:30 ET event study")
    parser.add_argument("--prices", required=True, help="One-minute-or-finer OHLC CSV")
    parser.add_argument("--calendar", required=True, help="Point-in-time economic calendar CSV")
    parser.add_argument("--output", required=True, help="New or existing research-output directory")
    parser.add_argument(
        "--source-timezone",
        help="IANA timezone for naive price timestamps; omit for timezone-aware timestamps",
    )
    parser.add_argument(
        "--calendar-timezone",
        default="America/New_York",
        help="IANA timezone for naive release timestamps",
    )
    parser.add_argument("--run-strategies", action="store_true", help="Run registered standalone families after event features")
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    return parser


def run(args: argparse.Namespace) -> Path:
    cfg = StudyConfig()
    prices = load_prices(args.prices, source_timezone=args.source_timezone, config=cfg)
    calendar = load_calendar(args.calendar, source_timezone=args.calendar_timezone, config=cfg)
    event_days = classify_event_days(prices["session_date"], calendar)
    features = build_session_features(prices, event_days, config=cfg)
    lifecycle_1m = classify_lifecycles(prices, features, structure_minutes=1, config=cfg)
    lifecycle_3m = classify_lifecycles(prices, features, structure_minutes=3, config=cfg)
    features = lifecycle_1m.copy()
    features["lifecycle_state_3m"] = lifecycle_3m["lifecycle_state_3m"]
    features["opposite_mss_time_3m"] = lifecycle_3m["opposite_mss_time_3m"]
    heatmap = build_five_minute_heatmap_data(prices, event_days, config=cfg)
    test_panel, event_tests = run_registered_event_tests(
        prices,
        features,
        iterations=args.bootstrap_iterations,
        minimum_sample=cfg.minimum_report_sample,
        config=cfg,
    )

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    features.reset_index().to_csv(output / "session_features.csv", index=False)
    heatmap.to_csv(output / "heatmap_5m.csv", index=False)
    test_panel.to_csv(output / "event_test_panel.csv", index=False)
    event_tests.to_csv(output / "hypothesis_test_results.csv", index=False)
    write_heatmap_svg(
        heatmap,
        output / "heatmap_absolute_movement.svg",
        value_column="average_absolute_return_bp",
        title="Average absolute XAUUSD movement",
        diverging=False,
    )
    write_heatmap_svg(
        heatmap,
        output / "heatmap_directional_movement.svg",
        value_column="average_directional_return_bp",
        title="Average directional XAUUSD movement",
        diverging=True,
    )
    write_quality_report(output / "data_quality_report.md", prices, features, calendar)
    write_run_metadata(
        output / "run_metadata.json",
        config=cfg,
        price_path=args.prices,
        calendar_path=args.calendar,
        strategies_run=args.run_strategies,
    )

    performance: pd.DataFrame | None = None
    bootstrap: pd.DataFrame | None = None
    if args.run_strategies:
        order_frames = [
            generate_candidate_orders(prices, features, structure_minutes=minutes, config=cfg)
            for minutes in (1, 3)
        ]
        nonempty_orders = [frame for frame in order_frames if not frame.empty]
        orders = pd.concat(nonempty_orders, ignore_index=True) if nonempty_orders else pd.DataFrame()
        orders.to_csv(output / "candidate_orders.csv", index=False)
        simulations: list[pd.DataFrame] = []
        if not orders.empty:
            for spread, slippage in (
                (cfg.normal_spread_price, cfg.normal_slippage_price_per_side),
                (cfg.stressed_spread_price, cfg.stressed_slippage_price_per_side),
            ):
                for close_before in (False, True):
                    simulations.append(
                        simulate_orders(
                            prices,
                            orders,
                            assumed_spread_price=spread,
                            assumed_slippage_price_per_side=slippage,
                            close_before_important_1000=close_before,
                            config=cfg,
                        )
                    )
        trades = pd.concat(simulations, ignore_index=True) if simulations else pd.DataFrame()
        trades.to_csv(output / "trade_outcomes.csv", index=False)
        performance = grouped_performance(trades, minimum_sample=cfg.minimum_report_sample)
        performance.to_csv(output / "strategy_performance.csv", index=False)
        bootstrap_records: list[dict] = []
        if not trades.empty:
            bootstrap_keys = [
                "family",
                "geometry",
                "structure_scale",
                "cost_scenario_spread_price",
                "cost_scenario_slippage_per_side",
                "exit_policy",
            ]
            for values, group in trades.groupby(bootstrap_keys, dropna=False):
                bootstrap_records.append(
                    {
                        "breakdown": "+".join(bootstrap_keys),
                        **{key: value for key, value in zip(bootstrap_keys, values)},
                        **session_bootstrap_expectancy(
                            group, iterations=args.bootstrap_iterations
                        ),
                    }
                )
        bootstrap = pd.DataFrame.from_records(bootstrap_records)
        bootstrap.to_csv(output / "bootstrap_confidence_intervals.csv", index=False)

    write_event_study_report(
        output / "event_study_report.md",
        features=features,
        performance=performance,
        bootstrap=bootstrap,
        minimum_sample=cfg.minimum_report_sample,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = run(args)
    except (DataRequirementError, ValueError) as exc:
        print(f"DATA GATE FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"Research outputs written to {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
