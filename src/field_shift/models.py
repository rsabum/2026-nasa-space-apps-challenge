"""Domain models for Field Shift."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Crop:
    family: str
    season_days: int
    base_temp_c: float
    kc: float
    ky: float
    n_fixing: bool
    root_depth_m: float


@dataclass(frozen=True)
class Zone:
    area_ha: float
    slope_pct: float
    awc_mm: float
    erodibility: float


@dataclass(frozen=True)
class WeatherYear:
    rain_mm: Sequence[float]
    et0_mm: Sequence[float]
    tmin_c: Sequence[float]
    tmax_c: Sequence[float]


@dataclass(frozen=True)
class Problem:
    zones: Mapping[str, Zone]
    crops: Mapping[str, Crop]
    weather_years: Sequence[WeatherYear]
    prices: Mapping[str, float]
    weights: Mapping[str, float]
    settings: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Rotation:
    assignments: Mapping[str, Sequence[str]]


@dataclass(frozen=True)
class Violation:
    constraint: str
    scope: str
    message: str


@dataclass(frozen=True)
class Report:
    total_score: float
    violations: list[Violation]
    profit: float
    soil_score: float
    erosion_score: float
    weather_year_results: list[dict[str, float]]
