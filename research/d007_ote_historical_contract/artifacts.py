"""Deterministic D007 artifact construction and atomic publication."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import OUTPUT_DIRECTORY, PUBLICATION_LOCK, STAGING_PREFIX
from .preflight import ContractPreflightError, assert_authorized_output_path
from .schemas import ALL_ARTIFACTS, JSON_ARTIFACTS, REPORT_ARTIFACT, TABLE_SCHEMAS


class ArtifactError(RuntimeError):
    """Raised when a result package cannot satisfy the frozen contract."""


_ARROW_TYPES: Mapping[str, pa.DataType] = {
    "string": pa.string(),
    "bool": pa.bool_(),
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int64": pa.int64(),
    "float64": pa.float64(),
    "timestamp_utc": pa.timestamp("us", tz="UTC"),
    "date32": pa.date32(),
    "list<string>": pa.list_(pa.string()),
}


def arrow_schema(name: str) -> pa.Schema:
    try:
        fields = TABLE_SCHEMAS[name]
    except KeyError as exc:
        raise ArtifactError(f"unregistered D007 table: {name}") from exc
    return pa.schema(
        [pa.field(column, _ARROW_TYPES[logical], nullable=nullable) for column, logical, nullable in fields]
    )


def _coerce_table(name: str, frame: pd.DataFrame) -> pa.Table:
    schema = arrow_schema(name)
    expected = schema.names
    if list(frame.columns) != expected:
        raise ArtifactError(f"{name} columns do not match the frozen schema")
    work = frame.copy(deep=True)
    for field in schema:
        if not field.nullable and work[field.name].isna().any():
            raise ArtifactError(f"{name}.{field.name} is non-nullable")
    try:
        table = pa.Table.from_pandas(work, schema=schema, preserve_index=False, safe=True)
    except (pa.ArrowException, TypeError, ValueError) as exc:
        raise ArtifactError(f"{name} values do not match the frozen schema") from exc
    if not table.schema.equals(schema, check_metadata=False):
        raise ArtifactError(f"{name} Arrow schema drift")
    return table


def empty_table_frame(name: str) -> pd.DataFrame:
    return arrow_schema(name).empty_table().to_pandas()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass(frozen=True)
class ArtifactPackage:
    json_objects: Mapping[str, object]
    report: str
    tables: Mapping[str, pd.DataFrame]

    def validate_membership(self) -> None:
        expected_json = set(JSON_ARTIFACTS) - {"artifact_manifest.json"}
        if set(self.json_objects) != expected_json:
            raise ArtifactError("D007 JSON artifact membership mismatch")
        if set(self.tables) != set(TABLE_SCHEMAS):
            raise ArtifactError("D007 Parquet artifact membership mismatch")
        if not isinstance(self.report, str) or not self.report.strip():
            raise ArtifactError("D007 report must be non-empty")


def stage_package(package: ArtifactPackage, staging: Path) -> dict[str, object]:
    """Write and verify a complete package inside an already isolated staging path."""

    package.validate_membership()
    if staging.exists() or staging.is_symlink():
        raise ArtifactError("staging directory must not pre-exist")
    staging.mkdir(parents=False)
    try:
        for name, value in sorted(package.json_objects.items()):
            (staging / name).write_bytes(_canonical_json(value))
        (staging / REPORT_ARTIFACT).write_text(package.report, encoding="utf-8", newline="\n")
        for name, frame in sorted(package.tables.items()):
            table = _coerce_table(name, frame)
            pq.write_table(table, staging / name, compression="zstd", use_dictionary=False)
        records = []
        for name in sorted(set(ALL_ARTIFACTS) - {"artifact_manifest.json"}):
            path = staging / name
            if not path.is_file() or path.is_symlink():
                raise ArtifactError(f"missing staged artifact: {name}")
            records.append({"path": name, "bytes": path.stat().st_size, "sha256": _digest(path)})
        manifest = {"schema": "d007-ote-artifact-manifest-v1", "artifacts": records}
        (staging / "artifact_manifest.json").write_bytes(_canonical_json(manifest))
        verify_staged_package(staging)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_staged_package(staging: Path) -> dict[str, object]:
    if staging.is_symlink() or not staging.is_dir():
        raise ArtifactError("unsafe D007 staging directory")
    actual = {path.name for path in staging.iterdir() if path.is_file() and not path.is_symlink()}
    if actual != set(ALL_ARTIFACTS):
        raise ArtifactError("staged artifact membership mismatch")
    manifest_path = staging / "artifact_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("invalid D007 artifact manifest") from exc
    if manifest.get("schema") != "d007-ote-artifact-manifest-v1":
        raise ArtifactError("artifact manifest schema mismatch")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ArtifactError("artifact manifest records are invalid")
    expected = set(ALL_ARTIFACTS) - {"artifact_manifest.json"}
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("path") in seen:
            raise ArtifactError("duplicate or invalid artifact manifest record")
        name = record.get("path")
        if name not in expected:
            raise ArtifactError("unregistered artifact manifest member")
        seen.add(name)
        path = staging / name
        if path.is_symlink() or path.stat().st_size != record.get("bytes") or _digest(path) != record.get("sha256"):
            raise ArtifactError(f"artifact checksum mismatch: {name}")
        if name.endswith(".parquet"):
            observed = pq.ParquetFile(path).schema_arrow
            if not observed.equals(arrow_schema(name), check_metadata=False):
                raise ArtifactError(f"artifact schema mismatch: {name}")
    if seen != expected:
        raise ArtifactError("artifact manifest membership mismatch")
    return manifest


@contextmanager
def _publication_lock(path: Path):
    """Hold an exclusive filesystem lock for the entire stage-and-rename window."""

    if path.is_symlink():
        raise ArtifactError("D007 publication lock cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ArtifactError("D007 publication lock parent cannot be a symlink")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        created = True
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    except FileExistsError as exc:
        raise ArtifactError("D007 publication lock already exists") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _atomic_publish(output: Path, package: ArtifactPackage, lock: Path) -> Path:
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise ArtifactError("D007 publication parent cannot be a symlink")
    with _publication_lock(lock):
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=parent))
        staging.rmdir()
        try:
            stage_package(package, staging)
            if output.exists() or output.is_symlink():
                raise ArtifactError("D007 output already exists; overwrite is forbidden")
            os.rename(staging, output)
            return output
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def publish_package(
    repository_root: Path,
    package: ArtifactPackage,
    *,
    output_relative: Path = OUTPUT_DIRECTORY,
) -> Path:
    """Publish only to the contract-frozen historical destination."""

    root = repository_root.resolve()
    try:
        output = assert_authorized_output_path(root, output_relative)
    except ContractPreflightError as exc:
        raise ArtifactError(str(exc)) from exc
    return _atomic_publish(output, package, root / PUBLICATION_LOCK)


def publish_synthetic_package(root: Path, relative: Path, package: ArtifactPackage) -> Path:
    """Test-only publication under an isolated temporary root, never a repository root."""

    root = root.resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ArtifactError("unsafe synthetic D007 output path")
    output = root / relative
    if root not in output.resolve().parents:
        raise ArtifactError("synthetic D007 output escaped its temporary root")
    cursor = output
    while cursor != root:
        if cursor.is_symlink():
            raise ArtifactError("D007 output path cannot contain symlinks")
        cursor = cursor.parent
    if output.exists() or output.is_symlink():
        raise ArtifactError("D007 output already exists; overwrite is forbidden")
    return _atomic_publish(output, package, root / ".d007-synthetic.publish.lock")


__all__ = [
    "ArtifactError",
    "ArtifactPackage",
    "arrow_schema",
    "empty_table_frame",
    "publish_package",
    "publish_synthetic_package",
    "stage_package",
    "verify_staged_package",
]
