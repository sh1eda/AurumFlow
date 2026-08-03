"""Metadata-only exposure-boundary evidence for D005_E6."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Iterable

from .config import E4_END_EXCLUSIVE, E4_START, PROPOSED_START, parse_utc


E4_RUN_MANIFEST = Path("research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION/run_manifest.json")
MARKET_METADATA_ROOTS = (
    Path("data/canonical/xauusd_ticks_d003-v2"),
    Path("data/processed/dukascopy/XAUUSD"),
)
DATE_IN_NAME = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")


class BoundaryAuditError(RuntimeError):
    """Raised when accepted metadata contradicts the frozen exposure record."""


@dataclass(frozen=True)
class MarketFileMetadata:
    path: str
    date_from_name: str | None
    byte_size: int


def _assert_contained_non_symlink(path: Path, repository_root: Path) -> Path:
    root = repository_root.resolve(strict=True)
    if path.is_symlink():
        raise BoundaryAuditError("symlinked metadata paths are forbidden")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BoundaryAuditError(f"missing metadata path: {path.name}") from error
    if resolved != root and root not in resolved.parents:
        raise BoundaryAuditError("metadata path escapes the repository root")
    return resolved


def _safe_json_metadata(path: Path, repository_root: Path) -> object:
    if path.suffix.lower() == ".parquet":
        raise BoundaryAuditError("Parquet payload access is forbidden")
    resolved = _assert_contained_non_symlink(path, repository_root)
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BoundaryAuditError(f"invalid accepted metadata: {path.name}") from error


def _date_from_name(name: str) -> date | None:
    match = DATE_IN_NAME.search(name)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def inspect_market_file_metadata(repository_root: Path) -> tuple[MarketFileMetadata, ...]:
    """Inspect only directory entries and stat metadata; never open payloads."""

    found: list[MarketFileMetadata] = []
    for relative_root in MARKET_METADATA_ROOTS:
        root = repository_root / relative_root
        if not root.is_dir():
            continue
        _assert_contained_non_symlink(root, repository_root)
        for path in sorted(root.rglob("*.parquet")):
            resolved = _assert_contained_non_symlink(path, repository_root)
            relative = path.relative_to(repository_root).as_posix()
            stamp = _date_from_name(path.name)
            found.append(
                MarketFileMetadata(
                    path=relative,
                    date_from_name=stamp.isoformat() if stamp else None,
                    byte_size=resolved.stat().st_size,
                )
            )
    return tuple(found)


def candidate_blind_start_is_proven(value: str) -> bool:
    """Fail closed: the exact exposure boundary is not registered in evidence."""

    candidate = parse_utc(value)
    if candidate <= parse_utc(E4_END_EXCLUSIVE):
        return False
    return False


def _later_files(records: Iterable[MarketFileMetadata]) -> list[dict[str, object]]:
    end_date = parse_utc(E4_END_EXCLUSIVE).date()
    return [
        asdict(record)
        for record in records
        if record.date_from_name is not None
        and date.fromisoformat(record.date_from_name) >= end_date
    ]


def audit_blind_boundary(repository_root: Path) -> dict[str, object]:
    manifest = _safe_json_metadata(repository_root / E4_RUN_MANIFEST, repository_root)
    if not isinstance(manifest, dict):
        raise BoundaryAuditError("accepted E4 run manifest must be an object")
    interval = manifest.get("accepted_interval")
    if interval != {"start": E4_START, "end_exclusive": E4_END_EXCLUSIVE}:
        raise BoundaryAuditError("accepted E4 interval metadata does not match the frozen record")

    records = inspect_market_file_metadata(repository_root)
    return {
        "audit_mode": "METADATA_ONLY",
        "accepted_non_blind_interval": interval,
        "frozen_canonical_end_exclusive": E4_END_EXCLUSIVE,
        "latest_exact_outcome_timestamp": "UNPROVEN",
        "earliest_proven_blind_start": "UNPROVEN",
        "blind_boundary_proven": False,
        "proposed_start_proven_blind": candidate_blind_start_is_proven(PROPOSED_START),
        "later_local_market_file_metadata": _later_files(records),
        "parquet_payload_opened": False,
        "market_row_decoded": False,
        "future_anchor_count_observed": False,
        "fail_closed_reason": "EXACT_LAST_ACCESSED_MARKET_TIMESTAMP_NOT_RECORDED",
    }
