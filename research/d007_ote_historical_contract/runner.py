"""Canonical D007 command boundary for the frozen empirical pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_CONTRACT, OUTPUT_DIRECTORY, HistoricalExecutionContract
from .preflight import ContractPreflightResult, run_contract_preflight


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
    """Authorize once, then enter the parameter-free authenticated pipeline."""

    prepared = prepare_historical_execution(
        repository_root,
        authorization=authorization,
        contract=contract,
    )
    from .pipeline import run_authenticated_historical_pipeline

    output = run_authenticated_historical_pipeline(prepared.root)
    if output.resolve() != prepared.output:
        raise RuntimeError("D007 historical pipeline returned an unauthorized output path")
    return output


__all__ = [
    "AuthorizedExecution",
    "prepare_historical_execution",
    "run_historical_execution",
]
