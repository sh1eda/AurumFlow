"""Canonical future D007 command boundary; empirical execution is deferred."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_CONTRACT, OUTPUT_DIRECTORY, HistoricalExecutionContract
from .preflight import ContractPreflightResult, run_contract_preflight


class HistoricalPipelineDeferred(RuntimeError):
    """The contract is valid, but this milestone cannot execute outcomes."""


@dataclass(frozen=True)
class AuthorizedExecution:
    root: Path
    output: Path
    preflight: ContractPreflightResult


def prepare_historical_execution(
    repository_root: Path,
    *,
    authorization: str,
    contract: HistoricalExecutionContract = DEFAULT_CONTRACT,
) -> AuthorizedExecution:
    root = repository_root.resolve()
    result = run_contract_preflight(
        root,
        authorization=authorization,
        output_relative=OUTPUT_DIRECTORY,
        contract=contract,
    )
    return AuthorizedExecution(
        root=root,
        output=(root / OUTPUT_DIRECTORY).resolve(),
        preflight=result,
    )


def run_historical_execution(
    repository_root: Path,
    *,
    authorization: str,
    contract: HistoricalExecutionContract = DEFAULT_CONTRACT,
) -> Path:
    """Preserve the canonical API while forbidding outcomes in this milestone."""

    prepare_historical_execution(
        repository_root,
        authorization=authorization,
        contract=contract,
    )
    raise HistoricalPipelineDeferred(
        "HISTORICAL_PIPELINE_DEFERRED: contract milestone cannot access D007 outcomes"
    )


__all__ = [
    "AuthorizedExecution",
    "HistoricalPipelineDeferred",
    "prepare_historical_execution",
    "run_historical_execution",
]
