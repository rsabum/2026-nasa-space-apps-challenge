"""Scoring engine used by evaluate and optimize."""

from __future__ import annotations

from typing import Iterable

from .models import Crop, Problem, Rotation, WeatherYear


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def daily_soil_water_bucket(zone_awc_mm: float, crop: Crop, weather: WeatherYear) -> tuple[float, float, float]:
    """Simulate a simple daily soil-water bucket and return ETa, ETc, and irrigation need (mm)."""
    storage = zone_awc_mm * 0.5
    eta_total = 0.0
    etc_total = 0.0
    irrigation_need = 0.0
    ndays = min(crop.season_days, len(weather.rain_mm), len(weather.et0_mm))
    for day in range(ndays):
        etc = crop.kc * weather.et0_mm[day]
        rain_eff = max(0.0, weather.rain_mm[day] * 0.8)
        available = storage + rain_eff
        eta = min(etc, available)
        deficit = max(0.0, etc - available)
        storage = _clamp(available - eta, 0.0, zone_awc_mm)
        eta_total += eta
        etc_total += etc
        irrigation_need += deficit
    return eta_total, etc_total, irrigation_need


def water_stress_yield_ratio(crop: Crop, eta: float, etc: float) -> float:
    """FAO-33 style yield ratio based on ET deficit."""
    if etc <= 0:
        return 0.0
    ratio = 1.0 - crop.ky * (1.0 - (eta / etc))
    return _clamp(ratio)


def _potential_yield_t_ha(problem: Problem, crop_name: str) -> float:
    yields = problem.settings.get("potential_yield_t_ha", {})
    if isinstance(yields, dict):
        return float(yields.get(crop_name, 1.0))
    return 1.0


def score_rotation(problem: Problem, rotation: Rotation) -> dict[str, float | list[dict[str, float]]]:
    """Compute objective components and weather-year details."""
    total_profit = 0.0
    soil_score = 0.0
    erosion_score = 0.0
    weather_results: list[dict[str, float]] = []

    for y_index, weather in enumerate(problem.weather_years):
        year_profit = 0.0
        year_eta = 0.0
        year_etc = 0.0
        for zone_name, sequence in rotation.assignments.items():
            if y_index >= len(sequence):
                continue
            crop_name = sequence[y_index]
            crop = problem.crops[crop_name]
            zone = problem.zones[zone_name]
            eta, etc, _irr_mm = daily_soil_water_bucket(zone.awc_mm, crop, weather)
            yr = water_stress_yield_ratio(crop, eta, etc)
            yield_t_ha = _potential_yield_t_ha(problem, crop_name) * yr
            price = float(problem.prices.get(crop_name, 0.0))
            year_profit += yield_t_ha * zone.area_ha * price
            year_eta += eta * zone.area_ha
            year_etc += etc * zone.area_ha
            soil_score += 2.0 if crop.n_fixing else 0.5
            soil_score += crop.root_depth_m
            erosion_score += 1.0 if crop_name in set(problem.settings.get("cover_crops", [])) else 0.2
        weather_results.append(
            {
                "year": float(y_index),
                "profit": year_profit,
                "eta": year_eta,
                "etc": year_etc,
            }
        )
        total_profit += year_profit

    weights = problem.weights
    total_score = (
        float(weights.get("profit", 1.0)) * total_profit
        + float(weights.get("soil", 1.0)) * soil_score
        + float(weights.get("erosion", 1.0)) * erosion_score
    )
    return {
        "total_score": total_score,
        "profit": total_profit,
        "soil_score": soil_score,
        "erosion_score": erosion_score,
        "weather_year_results": weather_results,
    }


def estimate_rotation_water_m3(problem: Problem, rotation: Rotation) -> float:
    """Estimate irrigation water demand volume (m^3) over full horizon."""
    total_m3 = 0.0
    for y_index, weather in enumerate(problem.weather_years):
        for zone_name, sequence in rotation.assignments.items():
            if y_index >= len(sequence):
                continue
            crop = problem.crops[sequence[y_index]]
            zone = problem.zones[zone_name]
            _eta, _etc, irr_mm = daily_soil_water_bucket(zone.awc_mm, crop, weather)
            total_m3 += irr_mm * zone.area_ha * 10.0
    return total_m3


def sequence_water_m3(problem: Problem, zone_name: str, sequence: Iterable[str]) -> float:
    """Estimate sequence irrigation demand volume for one zone."""
    zone = problem.zones[zone_name]
    total = 0.0
    for y_index, crop_name in enumerate(sequence):
        if y_index >= len(problem.weather_years):
            break
        crop = problem.crops[crop_name]
        weather = problem.weather_years[y_index]
        _eta, _etc, irr_mm = daily_soil_water_bucket(zone.awc_mm, crop, weather)
        total += irr_mm * zone.area_ha * 10.0
    return total
