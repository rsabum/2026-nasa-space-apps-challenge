"""One coherent synthetic world per (site, seed, params).

Weather drives soil wetness and yields; terrain drives soils; fields carry the
CDL rotation. Each component uses its own seeded random stream, so changing one
generator does not reshuffle the others. Expensive pieces are cached in memory
and under `<data_dir>/mock/`.
"""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.transform import from_origin

from field_shift import agro
from field_shift.config import Config
from field_shift.data.cdl import to_albers
from field_shift.mock.generators import fields, soils, soilwater, terrain, weather, yields

log = logging.getLogger(__name__)

PARAMS_DIR = Path(__file__).resolve().parent / "params"
STREAMS = {"weather": 1, "terrain": 2, "soils": 3, "fields": 4, "yields": 5, "prices": 6}
SRTM_SIZE = 3601  # 1 arc-second tile incl. the shared edge row/column
TNM_STEP_DEG = 1.0 / 10800.0  # 1/3 arc-second


class World:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.seed = int(config.section("mock")["seed"])
        base = PARAMS_DIR / str(config.section("mock")["params"])
        weather_file = base.with_name(base.stem + ".weather.yaml")
        self.params_text = base.read_text(encoding="utf-8") + weather_file.read_text(encoding="utf-8")
        self.params: dict[str, Any] = yaml.safe_load(base.read_text(encoding="utf-8"))
        self.params.update(yaml.safe_load(weather_file.read_text(encoding="utf-8")))
        self.lon, self.lat = config.lon, config.lat
        key = f"{self.params_text}|{self.seed}|{self.lon:.5f}|{self.lat:.5f}"
        self.key = hashlib.sha256(key.encode()).hexdigest()[:12]
        self.cache_dir = config.data_dir / "mock"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def rng(self, stream: str) -> np.random.Generator:
        return np.random.default_rng([self.seed, STREAMS[stream]])

    @property
    def elevation_m(self) -> float:
        return float(self.params["weather"]["elevation_m"])

    @property
    def years(self) -> tuple[int, int]:
        return int(self.params["world"]["start_year"]), int(self.params["world"]["end_year"])

    # --- weather ---------------------------------------------------------------------
    @cached_property
    def weather(self) -> pd.DataFrame:
        """Daily synthetic weather with all POWER variables plus et0_mm."""
        path = self.cache_dir / f"world_{self.key}_weather.parquet"
        if path.exists():
            return pd.read_parquet(path)
        start, end = self.years
        log.info("mock: generating synthetic weather %d-%d (seed %d)", start, end, self.seed)
        daily = weather.generate(self.params["weather"], f"{start}-01-01", f"{end}-12-31",
                                 self.lat, self.elevation_m, self.rng("weather"))
        ea = agro.actual_vapour_pressure_from_rh_mean_kpa(daily["tmax_c"], daily["tmin_c"], daily["rh2m_pct"])
        daily["et0_mm"] = agro.et0_fao56(daily["tmax_c"], daily["tmin_c"], daily["rs_mj_m2"],
                                         daily["wind2m_m_s"], ea, self.lat, self.elevation_m,
                                         daily["date"].dt.day_of_year)
        wet = soilwater.generate(daily, daily["et0_mm"].to_numpy(), self.params["soilwater"],
                                 self.params["weather"]["gwet"])
        daily = pd.concat([daily, wet], axis=1)
        daily.to_parquet(path, index=False)
        return daily

    # --- terrain / soils / fields ------------------------------------------------------------
    @cached_property
    def surface(self) -> terrain.Surface:
        return terrain.build_surface(self.params["terrain"], self.lon, self.lat, self.elevation_m,
                                     self.rng("terrain"))

    @cached_property
    def soils(self) -> soils.SoilWorld:
        return soils.build_soils(self.params["soils"], self.surface, self.rng("soils"))

    @cached_property
    def site_albers(self) -> tuple[float, float]:
        return to_albers(self.lon, self.lat)

    @cached_property
    def fields(self) -> fields.FieldWorld:
        return fields.build_fields(self.params["fields"], self.site_albers, self.years[1], self.rng("fields"))

    # --- NASS ----------------------------------------------------------------------------------
    @cached_property
    def county_yields(self) -> pd.DataFrame:
        indices = yields.weather_indices(self.weather)
        return yields.county_yields(self.params["yields"], indices, self.rng("yields"))

    @cached_property
    def state_prices(self) -> pd.DataFrame:
        start, end = self.years
        return yields.state_prices(self.params["prices"], list(range(start, end + 1)), self.rng("prices"))

    # --- elevation files -------------------------------------------------------------------------
    def srtm_tile_name(self) -> str:
        """SRTM tiles are named by their south-west corner, e.g. N42W094."""
        lat_c, lon_c = int(np.floor(self.lat)), int(np.floor(self.lon))
        return f"{'N' if lat_c >= 0 else 'S'}{abs(lat_c):02d}{'E' if lon_c >= 0 else 'W'}{abs(lon_c):03d}"

    def srtm_zip(self) -> Path:
        """A `<tile>.SRTMGL1.hgt.zip` like LP DAAC serves (int16 big-endian, 3601x3601)."""
        name = self.srtm_tile_name()
        path = self.cache_dir / f"world_{self.key}_{name}.SRTMGL1.hgt.zip"
        if path.exists():
            return path
        log.info("mock: generating synthetic SRTM tile %s", name)
        lat_c, lon_c = int(np.floor(self.lat)), int(np.floor(self.lon))
        step = 1.0 / 3600.0
        dem = terrain.grid(self.surface, lon_c, lat_c + 1, step, SRTM_SIZE, SRTM_SIZE)
        data = np.round(dem).astype(">i2").tobytes()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{name}.hgt", data)
        path.write_bytes(buffer.getvalue())
        return path

    def tnm_tile_name(self) -> str:
        """3DEP tiles are named by their north-west corner, e.g. USGS_13_n43w094.tif."""
        lat_c, lon_c = int(np.ceil(self.lat)), int(np.ceil(abs(self.lon)))
        return f"USGS_13_n{lat_c:02d}w{lon_c:03d}.tif"

    def tnm_tile(self) -> Path:
        """A tiled float32 GeoTIFF (EPSG:4269) around the site; a subset of a real 1x1 degree tile."""
        path = self.cache_dir / f"world_{self.key}_{self.tnm_tile_name()}"
        if path.exists():
            return path
        half = float(self.params["terrain"]["tnm_tile_half_size_deg"])
        west = np.floor((self.lon - half) / TNM_STEP_DEG) * TNM_STEP_DEG
        north = np.ceil((self.lat + half) / TNM_STEP_DEG) * TNM_STEP_DEG
        size = int(round(2 * half / TNM_STEP_DEG))
        dem = terrain.grid(self.surface, west + TNM_STEP_DEG / 2, north - TNM_STEP_DEG / 2,
                           TNM_STEP_DEG, size, size)
        profile = {"driver": "GTiff", "height": size, "width": size, "count": 1, "dtype": "float32",
                   "crs": "EPSG:4269", "transform": from_origin(west, north, TNM_STEP_DEG, TNM_STEP_DEG),
                   "nodata": -999999.0, "tiled": True, "blockxsize": 256, "blockysize": 256,
                   "compress": "deflate"}
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(dem, 1)
        return path
