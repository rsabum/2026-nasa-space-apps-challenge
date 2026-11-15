"""Load `config.yaml` into a typed object with small helpers.

Everything location- or endpoint-specific comes from here, so data modules never
hard-code a site, a URL or a path.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"

# Earth radius-based degree lengths, good enough for a ~2 km box.
_M_PER_DEG_LAT = 110_574.0
_M_PER_DEG_LON_EQUATOR = 111_320.0


@dataclass(frozen=True)
class BBox:
    """A lon/lat bounding box in WGS84 (EPSG:4326)."""

    west: float
    south: float
    east: float
    north: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    def wkt(self) -> str:
        w, s, e, n = self.as_tuple()
        return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


@dataclass
class Config:
    """Parsed configuration. Use `load_config()` to build one."""

    raw: dict[str, Any]
    root: Path = field(default=REPO_ROOT)

    # --- site -----------------------------------------------------------------
    @property
    def site_name(self) -> str:
        return str(self.raw["site"]["name"])

    @property
    def lat(self) -> float:
        return float(self.raw["site"]["lat"])

    @property
    def lon(self) -> float:
        return float(self.raw["site"]["lon"])

    @property
    def bbox(self) -> BBox:
        """Square box of side `bbox_km` centred on the site."""
        half_m = float(self.raw["site"]["bbox_km"]) * 1000.0 / 2.0
        dlat = half_m / _M_PER_DEG_LAT
        dlon = half_m / (_M_PER_DEG_LON_EQUATOR * math.cos(math.radians(self.lat)))
        return BBox(self.lon - dlon, self.lat - dlat, self.lon + dlon, self.lat + dlat)

    @property
    def state_alpha(self) -> str:
        return str(self.raw["site"]["state_alpha"])

    @property
    def state_fips(self) -> str:
        return str(self.raw["site"]["state_fips"]).zfill(2)

    @property
    def county_fips(self) -> str | None:
        value = str(self.raw["site"].get("county_fips") or "").strip()
        return value.zfill(3) if value else None

    # --- time -----------------------------------------------------------------
    @property
    def start_year(self) -> int:
        return int(self.raw["years"]["start"])

    @property
    def end_year(self) -> int:
        return int(self.raw["years"]["end"])

    # --- crops ----------------------------------------------------------------
    @property
    def cash_crops(self) -> list[str]:
        return list(self.raw["crops"]["cash"])

    @property
    def cover_crops(self) -> list[str]:
        return list(self.raw["crops"]["cover"])

    @property
    def all_crops(self) -> list[str]:
        return self.cash_crops + self.cover_crops

    # --- endpoints --------------------------------------------------------------
    @property
    def mode(self) -> str:
        mode = str(self.raw["endpoints"]["mode"]).lower()
        if mode not in {"mock", "real"}:
            raise ValueError(f"endpoints.mode must be 'mock' or 'real', got {mode!r}")
        return mode

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    @property
    def mock_base_url(self) -> str:
        return str(self.raw["endpoints"]["mock_base_url"]).rstrip("/")

    def endpoint(self, service: str) -> str:
        """Base URL for a service in the current mode, without trailing slash.

        In mock mode every service lives under `<mock_base_url>/<service>`, and the
        rest of the path is identical to the real API.
        """
        if service not in self.raw["endpoints"]["real"]:
            raise KeyError(f"unknown service {service!r}")
        if self.is_mock:
            return f"{self.mock_base_url}/{service}"
        return str(self.raw["endpoints"]["real"][service]).rstrip("/")

    # --- http -------------------------------------------------------------------
    @property
    def timeout_s(self) -> float:
        return float(self.raw["http"]["timeout_s"])

    @property
    def sleep_between_requests_s(self) -> float:
        if self.is_mock:
            return float(self.raw["mock"].get("sleep_between_requests_s", 0.0))
        return float(self.raw["http"]["sleep_between_requests_s"])

    # --- paths ------------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self._resolve(self.raw["paths"]["data_dir"])

    @property
    def reference_dir(self) -> Path:
        return self._resolve(self.raw["paths"]["reference_dir"])

    def raw_dir(self, dataset: str) -> Path:
        path = self.data_dir / "raw" / dataset
        path.mkdir(parents=True, exist_ok=True)
        return path

    def processed_dir(self) -> Path:
        path = self.data_dir / "processed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def processed_path(self, name: str) -> Path:
        """Path of a processed table, e.g. `processed_path("power")` -> power.parquet."""
        return self.processed_dir() / f"{name}.parquet"

    def _resolve(self, value: str | os.PathLike[str]) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    # --- misc ---------------------------------------------------------------------
    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name, {}))


def load_config(path: str | os.PathLike[str] | None = None, **overrides: Any) -> Config:
    """Read the YAML config.

    `path` defaults to `$FIELD_SHIFT_CONFIG` or the repo's `config.yaml`.
    `overrides` are shallow-merged per top-level section, e.g.
    `load_config(paths={"data_dir": "/tmp/x"})` (used by tests).
    """
    path = Path(path or os.environ.get("FIELD_SHIFT_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(path, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    for section, values in overrides.items():
        if isinstance(values, dict):
            merged = dict(raw.get(section, {}))
            merged.update(values)
            raw[section] = merged
        else:
            raw[section] = values
    return Config(raw=raw, root=path.resolve().parent)
