"""Synthetic elevation surface: a gently rolling, Des Moines Lobe-like landscape.

elevation(lon, lat) = base + regional tilt + swales (Gaussian troughs along line
segments) + knolls (Gaussian bumps) + low-amplitude smooth noise. All
parameters are PLACEHOLDERs (see params YAML); base = POWER site elevation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQ = 111_320.0
EXTENT_M = 2_500.0  # features are placed within +/- this distance of the site


@dataclass
class Surface:
    lon0: float
    lat0: float
    base_m: float
    tilt: tuple[float, float]  # m per km, east and north
    swales: np.ndarray  # rows: x1, y1, x2, y2, depth, width
    knolls: np.ndarray  # rows: x, y, height, radius
    noise: np.ndarray  # rows: kx, ky, phase, amplitude

    def to_local_m(self, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = (np.asarray(lon) - self.lon0) * M_PER_DEG_LON_EQ * np.cos(np.radians(self.lat0))
        y = (np.asarray(lat) - self.lat0) * M_PER_DEG_LAT
        return x, y

    def elevation(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Elevation in metres for arrays of lon/lat (any shape)."""
        x, y = self.to_local_m(lon, lat)
        z = self.base_m + (self.tilt[0] * x + self.tilt[1] * y) / 1000.0
        for x1, y1, x2, y2, depth, width in self.swales:
            z -= depth * np.exp(-_segment_distance2(x, y, x1, y1, x2, y2) / (2.0 * width ** 2))
        for kx, ky, height, radius in self.knolls:
            z += height * np.exp(-((x - kx) ** 2 + (y - ky) ** 2) / (2.0 * radius ** 2))
        for kx, ky, phase, amplitude in self.noise:
            z += amplitude * np.sin(kx * x + ky * y + phase)
        return z

    def relative_elevation(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Elevation minus base and tilt: negative in swales, positive on knolls."""
        x, y = self.to_local_m(lon, lat)
        return self.elevation(lon, lat) - self.base_m - (self.tilt[0] * x + self.tilt[1] * y) / 1000.0


def _segment_distance2(x: np.ndarray, y: np.ndarray, x1: float, y1: float, x2: float, y2: float) -> np.ndarray:
    dx, dy = x2 - x1, y2 - y1
    t = np.clip(((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy), 0.0, 1.0)
    return (x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2


def build_surface(params: dict[str, Any], lon0: float, lat0: float, base_m: float,
                  rng: np.random.Generator) -> Surface:
    swales = []
    for _ in range(int(params["n_swales"])):
        cx, cy = rng.uniform(-EXTENT_M, EXTENT_M, 2)
        length = rng.uniform(*params["swale_length_m"])
        angle = rng.uniform(0, np.pi)
        dx, dy = np.cos(angle) * length / 2, np.sin(angle) * length / 2
        swales.append([cx - dx, cy - dy, cx + dx, cy + dy,
                       rng.uniform(*params["swale_depth_m"]), rng.uniform(*params["swale_width_m"])])
    knolls = [[*rng.uniform(-EXTENT_M, EXTENT_M, 2), rng.uniform(*params["knoll_height_m"]),
               rng.uniform(*params["knoll_radius_m"])] for _ in range(int(params["n_knolls"]))]
    noise = []
    for _ in range(6):
        wavelength, angle = rng.uniform(200.0, 700.0), rng.uniform(0, 2 * np.pi)
        k = 2 * np.pi / wavelength
        noise.append([k * np.cos(angle), k * np.sin(angle), rng.uniform(0, 2 * np.pi),
                      params["noise_amplitude_m"] / 2.0])
    return Surface(lon0, lat0, base_m, tuple(params["tilt_m_per_km"]), np.asarray(swales),
                   np.asarray(knolls), np.asarray(noise))


def grid(surface: Surface, west: float, north: float, step_deg: float, nrows: int, ncols: int,
         block_rows: int = 400) -> np.ndarray:
    """Elevation on a north-up grid of pixel *centres* starting at (west, north)."""
    out = np.empty((nrows, ncols), dtype="float32")
    lons = west + step_deg * np.arange(ncols)
    for start in range(0, nrows, block_rows):
        rows = np.arange(start, min(start + block_rows, nrows))
        lats = north - step_deg * rows
        lon2d, lat2d = np.meshgrid(lons, lats)
        out[rows] = surface.elevation(lon2d, lat2d).astype("float32")
    return out
