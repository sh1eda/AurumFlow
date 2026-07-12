from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .types import ValidationStatus


@dataclass(frozen=True)
class ValidationGate:
    min_folds: int = 5
    min_closed_trades: int = 100


@dataclass(frozen=True)
class FoldMetrics:
    fold: int
    closed_trades: int
    expectancy: float
    profit_factor: float | None
    max_drawdown_r: float


@dataclass(frozen=True)
class ValidationReport:
    status: ValidationStatus
    baseline_expectancy: float
    candidate_expectancy: float
    fold_count: int
    closed_trades: int
    primary_metric: str = "after_cost_out_of_sample_expectancy"
    secondary_metrics: list[str] = field(
        default_factory=lambda: ["max_drawdown", "profit_factor", "average_r", "stability"]
    )
    reason: str = ""
    folds: list[FoldMetrics] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "primary_metric": self.primary_metric,
            "baseline_expectancy": self.baseline_expectancy,
            "candidate_expectancy": self.candidate_expectancy,
            "fold_count": self.fold_count,
            "closed_trades": self.closed_trades,
            "secondary_metrics": self.secondary_metrics,
            "reason": self.reason,
            "folds": [fold.__dict__ for fold in self.folds],
        }


def chronological_splits(length: int, folds: int, warmup: int = 20) -> list[tuple[int, int]]:
    if folds <= 0 or length <= warmup:
        return []
    validation_size = max(1, (length - warmup) // folds)
    splits: list[tuple[int, int]] = []
    start = warmup
    for fold in range(folds):
        end = length if fold == folds - 1 else min(length, start + validation_size)
        if start < end:
            splits.append((start, end))
        start = end
    return splits


def run_walk_forward(df: pd.DataFrame, config: BacktestConfig, folds: int = 5) -> ValidationReport:
    metrics: list[FoldMetrics] = []
    total_trades = 0
    total_r = 0.0
    splits = chronological_splits(len(df), folds)
    for fold_number, (start, end) in enumerate(splits, start=1):
        context_start = max(0, start - 20)
        fold_df = df.iloc[context_start:end].reset_index(drop=True)
        result = run_backtest(fold_df, config)
        fold_trades = [trade for trade in result.trades if trade.entry_index >= start - context_start]
        fold_result = BacktestResult(trades=fold_trades)
        total_trades += fold_result.closed_trades
        total_r += sum(trade.r_multiple for trade in fold_trades)
        metrics.append(
            FoldMetrics(
                fold=fold_number,
                closed_trades=fold_result.closed_trades,
                expectancy=fold_result.expectancy,
                profit_factor=fold_result.profit_factor,
                max_drawdown_r=fold_result.max_drawdown_r,
            )
        )
    expectancy = total_r / total_trades if total_trades else 0.0
    return ValidationReport(
        status=ValidationStatus.NOT_EVALUATED,
        baseline_expectancy=expectancy,
        candidate_expectancy=expectancy,
        fold_count=len(metrics),
        closed_trades=total_trades,
        reason="RULE_ONLY walk-forward baseline; no ML approval attempted.",
        folds=metrics,
    )


def evaluate_hybrid_validated_gate(
    baseline: BacktestResult,
    candidate: BacktestResult,
    fold_count: int,
    gate: ValidationGate | None = None,
) -> ValidationReport:
    gate = gate or ValidationGate()
    if fold_count < gate.min_folds or candidate.closed_trades < gate.min_closed_trades:
        return ValidationReport(
            status=ValidationStatus.INSUFFICIENT_EVIDENCE,
            baseline_expectancy=baseline.expectancy,
            candidate_expectancy=candidate.expectancy,
            fold_count=fold_count,
            closed_trades=candidate.closed_trades,
            reason="Minimum chronological folds or closed OOS trade count not met.",
        )
    if candidate.expectancy <= 0:
        return ValidationReport(
            status=ValidationStatus.REJECTED,
            baseline_expectancy=baseline.expectancy,
            candidate_expectancy=candidate.expectancy,
            fold_count=fold_count,
            closed_trades=candidate.closed_trades,
            reason="Primary expectancy is not positive.",
        )
    if candidate.expectancy <= baseline.expectancy:
        return ValidationReport(
            status=ValidationStatus.REJECTED,
            baseline_expectancy=baseline.expectancy,
            candidate_expectancy=candidate.expectancy,
            fold_count=fold_count,
            closed_trades=candidate.closed_trades,
            reason="Primary expectancy does not improve over RULE_ONLY.",
        )
    return ValidationReport(
        status=ValidationStatus.APPROVED,
        baseline_expectancy=baseline.expectancy,
        candidate_expectancy=candidate.expectancy,
        fold_count=fold_count,
        closed_trades=candidate.closed_trades,
        reason="Primary expectancy and evidence gates passed.",
    )
