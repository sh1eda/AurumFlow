"""Extensible market-data access with immutable provenance records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd


class DataSourceError(RuntimeError):
    """Raised when a configured data source cannot satisfy a request."""


@dataclass(frozen=True)
class MarketDataRequest:
    dataset: str
    symbol: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.dataset, str) or not self.dataset.strip():
            raise ValueError("dataset must be a non-empty string")
        if not isinstance(self.options, Mapping):
            raise ValueError("options must be a mapping")
        for name, value in (("symbol", self.symbol), ("timeframe", self.timeframe)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")
        for name, value in (("start", self.start), ("end", self.end)):
            if value is not None:
                if not isinstance(value, datetime):
                    raise ValueError(f"{name} must be a datetime when supplied")
                if value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must be earlier than or equal to end")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "options": dict(self.options),
        }


@dataclass(frozen=True)
class DataProvenance:
    source: str
    dataset: str
    fingerprint_algorithm: str
    fingerprint: str
    loaded_at: str
    row_count: int
    columns: tuple[str, ...]
    request: Mapping[str, Any]
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "dataset": self.dataset,
            "fingerprint_algorithm": self.fingerprint_algorithm,
            "fingerprint": self.fingerprint,
            "loaded_at": self.loaded_at,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "request": dict(self.request),
            "source_metadata": dict(self.source_metadata),
        }


@dataclass(frozen=True)
class MarketData:
    frame: pd.DataFrame
    provenance: DataProvenance


class MarketDataSource(Protocol):
    def load(self, request: MarketDataRequest) -> MarketData:
        """Load one requested dataset without changing the source data."""


def _import_attribute(reference: str) -> Any:
    module_name, separator, attribute_name = reference.partition(":")
    if not separator or not module_name or not attribute_name:
        raise DataSourceError(f"driver must use 'module:attribute' syntax: {reference!r}")
    try:
        module = import_module(module_name)
        return getattr(module, attribute_name)
    except (ImportError, AttributeError) as exc:
        raise DataSourceError(f"could not import data driver {reference!r}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CSVMarketDataSource:
    """Raw CSV adapter; interpretation and validation belong to experiments."""

    def __init__(
        self,
        *,
        name: str,
        root: Path,
        timestamp_column: str | None = None,
        read_csv_options: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.root = root.resolve()
        self.timestamp_column = timestamp_column
        self.read_csv_options = dict(read_csv_options or {})

    @classmethod
    def from_config(
        cls,
        *,
        name: str,
        project_root: Path,
        config: Mapping[str, Any],
    ) -> "CSVMarketDataSource":
        root_value = config.get("root", "data")
        if not isinstance(root_value, str):
            raise DataSourceError(f"data source {name!r} root must be a string")
        root = Path(root_value).expanduser()
        if not root.is_absolute():
            root = project_root / root
        timestamp_column = config.get("timestamp_column")
        if timestamp_column is not None and not isinstance(timestamp_column, str):
            raise DataSourceError(
                f"data source {name!r} timestamp_column must be a string"
            )
        options = config.get("read_csv_options", {})
        if not isinstance(options, Mapping):
            raise DataSourceError(
                f"data source {name!r} read_csv_options must be a table"
            )
        return cls(
            name=name,
            root=root,
            timestamp_column=timestamp_column,
            read_csv_options=options,
        )

    def _resolve_dataset(self, dataset: str) -> Path:
        if not dataset.strip():
            raise DataSourceError("dataset must be a non-empty relative path")
        relative = Path(dataset)
        if relative.is_absolute():
            raise DataSourceError("CSV dataset paths must be relative to the source root")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise DataSourceError("CSV dataset path escapes the configured source root")
        if not path.is_file():
            raise DataSourceError(f"CSV dataset does not exist: {path}")
        return path

    def load(self, request: MarketDataRequest) -> MarketData:
        path = self._resolve_dataset(request.dataset)
        request_options = request.options.get("read_csv", {})
        if not isinstance(request_options, Mapping):
            raise DataSourceError("request.options.read_csv must be a mapping")
        read_options = {**self.read_csv_options, **dict(request_options)}
        frame = pd.read_csv(path, **read_options)

        if request.start or request.end:
            if not self.timestamp_column:
                raise DataSourceError(
                    "start/end filtering requires timestamp_column in the source configuration"
                )
            if self.timestamp_column not in frame.columns:
                raise DataSourceError(
                    f"configured timestamp column {self.timestamp_column!r} is absent"
                )
            timestamps = pd.to_datetime(frame[self.timestamp_column], utc=True, errors="raise")
            mask = pd.Series(True, index=frame.index)
            if request.start:
                mask &= timestamps >= pd.Timestamp(request.start)
            if request.end:
                mask &= timestamps <= pd.Timestamp(request.end)
            frame = frame.loc[mask].copy()

        stat = path.stat()
        provenance = DataProvenance(
            source=self.name,
            dataset=request.dataset,
            fingerprint_algorithm="sha256",
            fingerprint=_sha256(path),
            loaded_at=datetime.now(timezone.utc).isoformat(),
            row_count=len(frame),
            columns=tuple(str(column) for column in frame.columns),
            request=request.to_dict(),
            source_metadata={
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_time_ns": stat.st_mtime_ns,
            },
        )
        return MarketData(frame=frame, provenance=provenance)


class DataCatalog:
    """Named source registry used by experiments instead of concrete adapters."""

    def __init__(self) -> None:
        self._sources: dict[str, MarketDataSource] = {}

    @classmethod
    def from_config(
        cls,
        *,
        project_root: Path,
        definitions: Mapping[str, Mapping[str, Any]],
    ) -> "DataCatalog":
        catalog = cls()
        for name, definition in definitions.items():
            settings = dict(definition)
            driver_reference = settings.pop("driver", None)
            if not isinstance(driver_reference, str):
                raise DataSourceError(f"data source {name!r} has no valid driver")
            driver = _import_attribute(driver_reference)
            if hasattr(driver, "from_config"):
                source = driver.from_config(
                    name=name, project_root=project_root, config=settings
                )
            else:
                source = driver(name=name, project_root=project_root, **settings)
            catalog.register(name, source)
        return catalog

    def register(self, name: str, source: MarketDataSource) -> None:
        if not name or name in self._sources:
            raise DataSourceError(f"duplicate or empty data source name: {name!r}")
        if not callable(getattr(source, "load", None)):
            raise DataSourceError(f"data source {name!r} must provide load(request)")
        self._sources[name] = source

    def load(self, source_name: str, request: MarketDataRequest) -> MarketData:
        try:
            source = self._sources[source_name]
        except KeyError as exc:
            raise DataSourceError(f"unknown data source: {source_name!r}") from exc
        result = source.load(request)
        if not isinstance(result, MarketData):
            raise DataSourceError(
                f"data source {source_name!r} returned {type(result).__name__}, not MarketData"
            )
        return result

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))


class RecordingDataAccess:
    """Run-scoped facade that records every dataset an experiment reads."""

    def __init__(self, catalog: DataCatalog) -> None:
        self._catalog = catalog
        self._inputs: list[dict[str, Any]] = []

    def load(self, source_name: str, request: MarketDataRequest) -> MarketData:
        result = self._catalog.load(source_name, request)
        self._inputs.append(result.provenance.to_dict())
        return result

    @property
    def inputs(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._inputs)
