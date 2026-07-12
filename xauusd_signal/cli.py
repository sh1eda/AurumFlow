from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import BacktestConfig, run_backtest
from .data import load_ohlcv_csv
from .paper import PaperLedger
from .strategy import StrategyConfig, evaluate_signal
from .types import HtfBias, OperatingMode
from .validation import run_walk_forward


def _strategy_config(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        operating_mode=OperatingMode(args.mode),
        htf_bias=HtfBias(args.htf_bias),
        min_risk_reward=args.min_rr,
        min_confidence=args.min_confidence,
        spread_buffer=args.spread_buffer,
        min_stop_distance=args.min_stop_distance,
    )


def _load_tail(path: str, bars: int | None):
    df = load_ohlcv_csv(path)
    if bars:
        return df.tail(bars).reset_index(drop=True)
    return df


def cmd_signal(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars)
    signal = evaluate_signal(df, _strategy_config(args))
    return signal.to_dict()


def cmd_backtest(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars)
    result = run_backtest(
        df,
        BacktestConfig(
            strategy=_strategy_config(args),
            spread_cost=args.spread_cost,
            slippage=args.slippage,
            commission_r=args.commission_r,
        ),
    )
    return {
        "closed_trades": result.closed_trades,
        "expectancy": result.expectancy,
        "profit_factor": result.profit_factor,
        "max_drawdown_r": result.max_drawdown_r,
        "rejection_counts": result.rejection_counts,
    }


def cmd_validate(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars)
    report = run_walk_forward(
        df,
        BacktestConfig(
            strategy=_strategy_config(args),
            spread_cost=args.spread_cost,
            slippage=args.slippage,
            commission_r=args.commission_r,
        ),
        folds=args.folds,
    )
    return report.to_dict()


def cmd_paper(args: argparse.Namespace) -> dict:
    df = _load_tail(args.csv, args.bars)
    signal = evaluate_signal(df, _strategy_config(args))
    ledger = PaperLedger(Path(args.ledger))
    ledger.record_signal(signal)
    return {"ledger": str(ledger.path), "recorded": signal.to_dict()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xauusd-signal")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--csv", required=True)
        subparser.add_argument("--mode", choices=[mode.value for mode in OperatingMode], default=OperatingMode.RULE_ONLY.value)
        subparser.add_argument("--htf-bias", choices=[bias.value for bias in HtfBias], default=HtfBias.NEUTRAL.value)
        subparser.add_argument("--bars", type=int, default=None)
        subparser.add_argument("--min-rr", type=float, default=2.0)
        subparser.add_argument("--min-confidence", type=float, default=0.70)
        subparser.add_argument("--spread-buffer", type=float, default=0.10)
        subparser.add_argument("--min-stop-distance", type=float, default=0.50)

    signal = subparsers.add_parser("signal")
    add_common(signal)
    signal.set_defaults(func=cmd_signal)

    backtest = subparsers.add_parser("backtest")
    add_common(backtest)
    backtest.add_argument("--spread-cost", type=float, default=0.0)
    backtest.add_argument("--slippage", type=float, default=0.0)
    backtest.add_argument("--commission-r", type=float, default=0.0)
    backtest.set_defaults(func=cmd_backtest)

    validate = subparsers.add_parser("validate")
    add_common(validate)
    validate.add_argument("--spread-cost", type=float, default=0.0)
    validate.add_argument("--slippage", type=float, default=0.0)
    validate.add_argument("--commission-r", type=float, default=0.0)
    validate.add_argument("--folds", type=int, default=5)
    validate.set_defaults(func=cmd_validate)

    paper = subparsers.add_parser("paper")
    add_common(paper)
    paper.add_argument("--ledger", required=True)
    paper.set_defaults(func=cmd_paper)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output = args.func(args)
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
