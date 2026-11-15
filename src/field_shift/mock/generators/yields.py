"""Synthetic NASS county yields (weather-driven) and state prices received.

yield = (base + trend * (year - trend_start)) * (1 + water * z_water - heat * z_heat) + noise
- z_water: standardized May-Aug sum of (precip - ET0) from the synthetic weather
- z_heat:  standardized count of Jun-Aug days with tmax > 32 C
Prices: log-price AR(1) around a level. All coefficients are PLACEHOLDERs.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

HEAT_DAY_C = 32.0


def weather_indices(daily: pd.DataFrame) -> pd.DataFrame:
    """Per-year standardized water-balance and heat indices."""
    df = daily.assign(year=daily["date"].dt.year, month=daily["date"].dt.month)
    season = df[df["month"].between(5, 8)]
    water = (season["precip_mm"] - season["et0_mm"]).groupby(season["year"]).sum()
    summer = df[df["month"].between(6, 8)]
    heat = (summer["tmax_c"] > HEAT_DAY_C).groupby(summer["year"]).sum().astype(float)
    out = pd.DataFrame({"water": water, "heat": heat})
    return (out - out.mean()) / out.std(ddof=0).replace(0, 1)


def county_yields(params: dict[str, Any], indices: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Rows: year, crop, value (NaN = suppressed '(D)'); missing years are dropped."""
    rows = []
    start = int(params["trend_start_year"])
    for crop, p in params["crops"].items():
        for year, idx in indices.iterrows():
            if rng.random() < p["missing_year_prob"]:
                continue
            mean = (p["base"] + p["trend_per_year"] * (year - start)) * (1 + p["water"] * idx["water"] - p["heat"] * idx["heat"])
            value = max(mean + rng.normal(0, p["noise_sd"]), 0.0)
            suppressed = rng.random() < p["suppressed_prob"]
            rows.append({"year": int(year), "crop": crop, "value": np.nan if suppressed else round(value, 1)})
    return pd.DataFrame(rows)


def state_prices(params: dict[str, Any], years: list[int], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for crop, p in params["crops"].items():
        x = 0.0
        for year in years:
            x = p["phi"] * x + p["sigma"] * rng.standard_normal()
            rows.append({"year": year, "crop": crop, "value": round(p["level"] * float(np.exp(x)), 2)})
    return pd.DataFrame(rows)
