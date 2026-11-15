"""Synthetic Cropland Data Layer: fields on a PLSS-like grid with Markov rotations.

Layout (in EPSG:5070 metres): 1-mile sections bounded by roads; each section has
four quarter-section fields, some split in half; some sections have a farmstead
(buildings + windbreak trees). Each field's main crop follows a Markov chain over
the MVP crops. A small, deterministic per-pixel noise imitates CDL
misclassification. Pixels are 30 m up to 2023 and 10 m from 2024, as in the real CDL.
All probabilities are PLACEHOLDERs (params YAML).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from field_shift.data.cdl_legend import MVP_CROP_CODES

HALF_SIZE_M = 3_000.0
GRASS, TREES, ROAD, BUILDINGS = 176, 141, 121, 122
FARMSTEAD_M, BUILDINGS_M = 120.0, 60.0


def pixel_size_m(year: int) -> float:
    return 10.0 if year >= 2024 else 30.0


@dataclass
class FieldWorld:
    origin: tuple[float, float]
    section_m: float
    road_m: float
    n_sections: int
    split: np.ndarray  # (nsx, nsy, 2, 2) 0 none, 1 split along x, 2 split along y
    farmstead: np.ndarray  # (nsx, nsy) bool
    codes: np.ndarray  # (n_fields, n_years) CDL code per field and year
    start_year: int
    misclass_prob: float

    def classify(self, x: np.ndarray, y: np.ndarray, year: int) -> np.ndarray:
        """CDL code at EPSG:5070 points (pixel centres) for one year."""
        s, n = self.section_m, self.n_sections
        u, v = np.asarray(x) - self.origin[0], np.asarray(y) - self.origin[1]
        sx = np.clip(np.floor(u / s).astype(int), 0, n - 1)
        sy = np.clip(np.floor(v / s).astype(int), 0, n - 1)
        lu, lv = u - sx * s, v - sy * s
        qx, qy = (lu >= s / 2).astype(int), (lv >= s / 2).astype(int)
        wu, wv = lu - qx * s / 2, lv - qy * s / 2
        split = self.split[sx, sy, qx, qy]
        half = np.where(split == 1, wu >= s / 4, np.where(split == 2, wv >= s / 4, False)).astype(int)
        field = (((sx * n + sy) * 2 + qx) * 2 + qy) * 2 + half
        year_index = int(np.clip(year - self.start_year, 0, self.codes.shape[1] - 1))
        out = self.codes[field, year_index].copy()

        # Farmstead in the NW quarter of a section: trees around a building block.
        r = self.road_m
        in_farm = (self.farmstead[sx, sy] & (qx == 0) & (qy == 1)
                   & (wu >= r) & (wu < r + FARMSTEAD_M) & (wv <= s / 2 - r) & (wv > s / 2 - r - FARMSTEAD_M))
        cu, cv = wu - (r + FARMSTEAD_M / 2), wv - (s / 2 - r - FARMSTEAD_M / 2)
        in_buildings = in_farm & (np.abs(cu) < BUILDINGS_M / 2) & (np.abs(cv) < BUILDINGS_M / 2)
        out = np.where(in_farm, TREES, out)
        out = np.where(in_buildings, BUILDINGS, out)
        on_road = (lu < r / 2) | (lu > s - r / 2) | (lv < r / 2) | (lv > s - r / 2)
        out = np.where(on_road, ROAD, out)
        return self._noise(out, x, y, year)

    def _noise(self, codes: np.ndarray, x: np.ndarray, y: np.ndarray, year: int) -> np.ndarray:
        """Deterministic misclassification: same pixel + year -> same answer."""
        res = pixel_size_m(year)
        ix = np.floor(np.asarray(x) / res).astype(np.int64)
        iy = np.floor(np.asarray(y) / res).astype(np.int64)
        h = (ix * 73856093) ^ (iy * 19349663) ^ (year * 83492791)
        u01 = ((h * 2654435761) % 4294967296) / 4294967296.0
        flip = u01 < self.misclass_prob
        corn, soy = MVP_CROP_CODES["corn"], MVP_CROP_CODES["soybeans"]
        confused = np.where(codes == corn, soy, np.where(codes == soy, corn, GRASS))
        is_crop = np.isin(codes, list(MVP_CROP_CODES.values()))
        return np.where(flip & is_crop, confused, codes).astype("uint8")

    def site_code(self, x: float, y: float, year: int) -> int:
        """Value of the pixel containing (x, y), like GetCDLValue."""
        res = pixel_size_m(year)
        cx, cy = (np.floor(x / res) + 0.5) * res, (np.floor(y / res) + 0.5) * res
        return int(self.classify(np.array([cx]), np.array([cy]), year)[0])


def _rotations(params: dict[str, Any], n_fields: int, n_years: int, rng: np.random.Generator) -> np.ndarray:
    crops = list(params["rotation"])
    matrix = np.array([[params["rotation"][a][b] for b in crops] for a in crops], dtype=float)
    matrix /= matrix.sum(axis=1, keepdims=True)
    codes = np.empty((n_fields, n_years), dtype="uint8")
    for f in range(n_fields):
        if rng.random() < params["grass_field_prob"]:
            codes[f] = GRASS
            continue
        state = crops.index("corn") if rng.random() < 0.5 else crops.index("soybeans")
        for t in range(n_years):
            codes[f, t] = MVP_CROP_CODES[crops[state]]
            state = int(rng.choice(len(crops), p=matrix[state]))
    return codes


def build_fields(params: dict[str, Any], site_xy: tuple[float, float], end_year: int,
                 rng: np.random.Generator) -> FieldWorld:
    s = float(params["section_m"])
    n = int(np.ceil(2 * HALF_SIZE_M / s)) + 1
    start_year = int(params["start_year"])
    n_years = end_year - start_year + 1
    for _ in range(100):  # re-draw until the site pixel is inside a crop field
        offset = rng.uniform(0, s, 2)
        origin = (site_xy[0] - HALF_SIZE_M - offset[0], site_xy[1] - HALF_SIZE_M - offset[1])
        split_draw = rng.random((n, n, 2, 2))
        split = np.where(split_draw < params["half_split_prob"], rng.integers(1, 3, (n, n, 2, 2)), 0)
        farmstead = rng.random((n, n)) < params["farmstead_prob"]
        codes = _rotations(params, n * n * 8, n_years, rng)
        world = FieldWorld(origin, s, float(params["road_width_m"]), n, split, farmstead, codes,
                           start_year, float(params["misclass_prob"]))
        clean = FieldWorld(origin, s, world.road_m, n, split, farmstead, codes, start_year, 0.0)
        site_codes = [clean.site_code(*site_xy, y) for y in range(start_year, end_year + 1)]
        if all(c in MVP_CROP_CODES.values() for c in site_codes):
            return world
    raise RuntimeError("could not place the site inside a crop field; check the fields params")
