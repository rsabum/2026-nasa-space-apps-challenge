"""Cache bookkeeping: fetch results, the manifest, and cache-only loading.

Layout (relative to `paths.data_dir`):
    raw/<dataset>/...           untouched downloads
    processed/<name>.parquet    cleaned tables
    processed/<dataset>/...     cleaned rasters / GeoJSON
    manifest.json               one entry per dataset: when, from where, how much
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from field_shift.config import Config

log = logging.getLogger(__name__)


class NotCachedError(FileNotFoundError):
    """Raised by `load()` when a dataset hasn't been fetched yet."""

    def __init__(self, dataset: str, missing: Path) -> None:
        super().__init__(
            f"{dataset} is not cached ({missing} is missing). "
            f"Run: python -m field_shift.data fetch --dataset {dataset}"
        )
        self.dataset = dataset


@dataclass
class FetchResult:
    """Outcome of one `fetch()` call."""

    dataset: str
    status: str  # "fetched" | "cached" | "skipped" | "failed"
    message: str = ""

    def __str__(self) -> str:
        return f"{self.dataset:<8} {self.status:<8} {self.message}"


def manifest_path(config: Config) -> Path:
    return config.data_dir / "manifest.json"


def read_manifest(config: Config) -> dict[str, Any]:
    path = manifest_path(config)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def update_manifest(config: Config, dataset: str, **info: Any) -> None:
    """Record a successful fetch. Never pass secrets here."""
    manifest = read_manifest(config)
    entry = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "mock" if config.is_mock else "real",
        "endpoint_mode": config.mode,
    }
    entry.update(info)
    manifest[dataset] = entry
    path = manifest_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, default=str)


def all_exist(paths: list[Path]) -> bool:
    return all(p.exists() for p in paths)


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def read_table(config: Config, dataset: str, path: Path) -> pd.DataFrame:
    """Read a processed parquet table, or raise `NotCachedError`."""
    if not path.exists():
        raise NotCachedError(dataset, path)
    df = pd.read_parquet(path)
    if "is_synthetic" in df.columns and bool(df["is_synthetic"].any()):
        log.warning("%s: loading SYNTHETIC data from the mock services (not real observations)", dataset)
    return df


def date_range_info(series: pd.Series) -> dict[str, str]:
    """Min/max of a date or year column for the manifest."""
    if series.empty:
        return {"date_min": "", "date_max": ""}
    return {"date_min": str(series.min())[:10], "date_max": str(series.max())[:10]}
