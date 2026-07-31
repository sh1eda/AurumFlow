from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .data import DataValidationError, load_ohlcv_csv
from .data_quality import inspect_ohlcv_csv
from .diagnostics import run_rule_funnel
from .paper import PaperLedger
from .strategy import StrategyConfig, evaluate_signal
from .types import EntryModel, HtfBias, OperatingMode
from .validation import run_walk_forward


def _strategy_config(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        operating_mode=OperatingMode(args.mode),
        htf_bias=HtfBias(args.htf_bias),
        min_risk_reward=args.min_rr,
        min_confidence=args.min_confidence,
        spread_buffer=args.spread_buffer,
        min_stop_distance=args.min_stop_distance,
        entry_model=EntryModel(args.entry_model),
        max_entry_wait_bars=args.max_entry_wait_bars,
        invalidate_on_structural_break=args.invalidate_on_structural_break,
        invalidate_on_stop_level_breach=args.invalidate_on_stop_level_breach,
        invalidate_on_fvg_close_through=args.invalidate_on_fvg_close_through,
    )


def _utc_boundary(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise DataValidationError(f"Invalid UTC date boundary: {value}") from exc
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _load_tail(
    path: str,
    bars: int | None,
    source_timezone: str | None,
    start: str | None,
    end: str | None,
):
    df = load_ohlcv_csv(path, source_timezone=source_timezone)
    start_at = _utc_boundary(start)
    end_at = _utc_boundary(end)
    if start_at is not None and end_at is not None and start_at >= end_at:
        raise DataValidationError("--start must be earlier than --end")
    if start_at is not None:
        df = df[df["timestamp"] >= start_at]
    if end_at is not None:
        df = df[df["timestamp"] < end_at]
    df = df.reset_index(drop=True)
    if bars:
        return df.tail(bars).reset_index(drop=True)
    return df


def cmd_signal(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars, args.source_timezone, args.start, args.end)
    signal = evaluate_signal(df, _strategy_config(args))
    return signal.to_dict()


def cmd_backtest(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars, args.source_timezone, args.start, args.end)
    strategy = _strategy_config(args)
    backtest_config = BacktestConfig(
        strategy=strategy,
        spread_cost=args.spread_cost,
        slippage=args.slippage,
        commission_r=args.commission_r,
        max_holding_bars=args.max_holding_bars,
    )
    result = run_backtest(
        df,
        backtest_config,
    )
    pending_orders = len(result.orders)

    def outcome_rate(code: str) -> float:
        if not pending_orders:
            return 0.0
        return result.outcome_counts.get(code, 0) / pending_orders

    return {
        "closed_trades": result.closed_trades,
        "expectancy": result.expectancy,
        "average_r": result.expectancy,
        "profit_factor": result.profit_factor,
        "max_drawdown_r": result.max_drawdown_r,
        "pending_orders": pending_orders,
        "fill_rate": outcome_rate("entry_filled"),
        "expiration_rate": outcome_rate("entry_expired"),
        "invalidation_rate": outcome_rate("setup_invalidated"),
        "rejection_counts": result.rejection_counts,
        "outcome_counts": result.outcome_counts,
        "configuration": {
            "mode": strategy.operating_mode.value,
            "htf_bias": strategy.htf_bias.value,
            "min_risk_reward": strategy.min_risk_reward,
            "stop_buffer": strategy.spread_buffer,
            "max_entry_wait_bars": strategy.max_entry_wait_bars,
            "max_holding_bars": backtest_config.max_holding_bars,
            "spread_cost": backtest_config.spread_cost,
            "slippage": backtest_config.slippage,
            "commission_r": backtest_config.commission_r,
        },
    }


def cmd_validate(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars, args.source_timezone, args.start, args.end)
    report = run_walk_forward(
        df,
        BacktestConfig(
            strategy=_strategy_config(args),
            spread_cost=args.spread_cost,
            slippage=args.slippage,
            commission_r=args.commission_r,
            max_holding_bars=args.max_holding_bars,
        ),
        folds=args.folds,
    )
    return report.to_dict()


def cmd_paper(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars, args.source_timezone, args.start, args.end)
    signal = evaluate_signal(df, _strategy_config(args))
    ledger = PaperLedger(Path(args.ledger))
    ledger.record_signal(signal)
    return {"ledger": str(ledger.path), "recorded": signal.to_dict()}


def cmd_diagnose(args: argparse.Namespace) -> dict | str:
    df = _load_tail(args.csv, args.bars, args.source_timezone, args.start, args.end)
    report = run_rule_funnel(
        df,
        BacktestConfig(
            strategy=_strategy_config(args),
            spread_cost=args.spread_cost,
            slippage=args.slippage,
            commission_r=args.commission_r,
            max_holding_bars=args.max_holding_bars,
        ),
    )
    return report.to_dict() if args.format == "json" else report.to_text()


def cmd_data_check(args: argparse.Namespace) -> dict | str:
    result = inspect_ohlcv_csv(
        args.csv,
        source_timezone=args.source_timezone,
        expected_frequency=args.expected_frequency,
        large_gap_multiple=args.large_gap_multiple,
        minimum_history_days=args.minimum_history_days,
        source=args.source,
        symbol=args.symbol,
        broker=args.broker,
        price_type=args.price_type,
    )
    normalized_output = ""
    if args.normalized_output:
        normalized_output = str(result.write_normalized_csv(args.normalized_output))
    if args.format == "json":
        payload = result.report.to_dict()
        payload["normalized_output"] = normalized_output
        return payload
    output = result.report.to_text()
    if normalized_output:
        output += f"\n\nNormalized output: {normalized_output}"
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aurumflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--csv", required=True)
        subparser.add_argument(
            "--source-timezone",
            default=None,
            help="Required for naive timestamps; IANA name such as UTC or America/New_York.",
        )
        subparser.add_argument(
            "--mode",
            choices=[mode.value for mode in OperatingMode],
            default=OperatingMode.RULE_ONLY.value,
        )
        subparser.add_argument(
            "--htf-bias",
            choices=[bias.value for bias in HtfBias],
            default=HtfBias.NEUTRAL.value,
        )
        subparser.add_argument("--bars", type=int, default=None)
        subparser.add_argument(
            "--start",
            default=None,
            help="Inclusive UTC timestamp/date boundary.",
        )
        subparser.add_argument(
            "--end",
            default=None,
            help="Exclusive UTC timestamp/date boundary.",
        )
        subparser.add_argument("--min-rr", type=float, default=2.0)
        subparser.add_argument("--min-confidence", type=float, default=0.70)
        subparser.add_argument("--spread-buffer", type=float, default=0.10)
        subparser.add_argument("--min-stop-distance", type=float, default=0.50)
        subparser.add_argument(
            "--entry-model",
            choices=[model.value for model in EntryModel],
            default=EntryModel.FVG_MIDPOINT.value,
        )
        subparser.add_argument("--max-entry-wait-bars", type=int, default=8)
        subparser.add_argument(
            "--invalidate-on-structural-break",
            action=argparse.BooleanOptionalAction,
            default=True,
        )
        subparser.add_argument(
            "--invalidate-on-stop-level-breach",
            action=argparse.BooleanOptionalAction,
            default=True,
        )
        subparser.add_argument(
            "--invalidate-on-fvg-close-through",
            action=argparse.BooleanOptionalAction,
            default=True,
        )

    signal = subparsers.add_parser("signal")
    add_common(signal)
    signal.set_defaults(func=cmd_signal)

    backtest = subparsers.add_parser("backtest")
    add_common(backtest)
    backtest.add_argument("--spread-cost", type=float, default=0.0)
    backtest.add_argument("--slippage", type=float, default=0.0)
    backtest.add_argument("--commission-r", type=float, default=0.0)
    backtest.add_argument("--max-holding-bars", type=int, default=48)
    backtest.set_defaults(func=cmd_backtest)

    validate = subparsers.add_parser("validate")
    add_common(validate)
    validate.add_argument("--spread-cost", type=float, default=0.0)
    validate.add_argument("--slippage", type=float, default=0.0)
    validate.add_argument("--commission-r", type=float, default=0.0)
    validate.add_argument("--max-holding-bars", type=int, default=48)
    validate.add_argument("--folds", type=int, default=5)
    validate.set_defaults(func=cmd_validate)

    paper = subparsers.add_parser("paper")
    add_common(paper)
    paper.add_argument("--ledger", required=True)
    paper.set_defaults(func=cmd_paper)

    diagnose = subparsers.add_parser("diagnose")
    add_common(diagnose)
    diagnose.add_argument("--spread-cost", type=float, default=0.0)
    diagnose.add_argument("--slippage", type=float, default=0.0)
    diagnose.add_argument("--commission-r", type=float, default=0.0)
    diagnose.add_argument("--max-holding-bars", type=int, default=48)
    diagnose.add_argument("--format", choices=["text", "json"], default="text")
    diagnose.set_defaults(func=cmd_diagnose)

    data_check = subparsers.add_parser("data-check")
    data_check.add_argument("--csv", required=True)
    data_check.add_argument("--source-timezone", default=None)
    data_check.add_argument("--expected-frequency", default="15min")
    data_check.add_argument("--large-gap-multiple", type=int, default=4)
    data_check.add_argument("--minimum-history-days", type=int, default=365)
    data_check.add_argument("--source", default="unknown")
    data_check.add_argument("--symbol", default="XAUUSD")
    data_check.add_argument("--broker", default="unknown")
    data_check.add_argument(
        "--price-type",
        choices=["bid", "ask", "midpoint", "unknown"],
        default="unknown",
    )
    data_check.add_argument("--normalized-output", default=None)
    data_check.add_argument("--format", choices=["text", "json"], default="text")
    data_check.set_defaults(func=cmd_data_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = args.func(args)
    except DataValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if isinstance(output, str):
        print(output)
    else:
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
