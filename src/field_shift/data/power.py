"""NASA POWER daily point weather (agroclimatology community, no auth).

API docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
Used for: weather, frost dates, crop water use (ET0), past years as scenarios.

Processed table `power.parquet`, one row per day:
    date, tmean_c, tmax_c, tmin_c, precip_mm, rs_mj_m2, rh2m_pct, wind2m_m_s,
    gwettop_frac, gwetroot_frac, et0_mm, gdd10, is_synthetic
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from field_shift import agro
from field_shift.config import Config
from field_shift.data import cache, checks, http

log = logging.getLogger(__name__)

DATASET = "power"
API_PATH = "/api/temporal/daily/point"
FILL_VALUE = -999.0

# POWER parameter -> our column name (units in the name).
PARAMETERS: dict[str, str] = {
    "T2M": "tmean_c",
    "T2M_MAX": "tmax_c",
    "T2M_MIN": "tmin_c",
    "PRECTOTCORR": "precip_mm",
    "ALLSKY_SFC_SW_DWN": "rs_mj_m2",
    "RH2M": "rh2m_pct",
    "WS2M": "wind2m_m_s",
    "GWETTOP": "gwettop_frac",
    "GWETROOT": "gwetroot_frac",
}
# The POWER units we expect for each parameter; a mismatch means the API changed.
EXPECTED_UNITS: dict[str, str] = {
    "T2M": "C", "T2M_MAX": "C", "T2M_MIN": "C", "PRECTOTCORR": "mm/day",
    "ALLSKY_SFC_SW_DWN": "MJ/m^2/day", "RH2M": "%", "WS2M": "m/s",
    "GWETTOP": "1", "GWETROOT": "1",
}


def raw_path(config: Config) -> Path:
    return config.raw_dir(DATASET) / f"power_daily_{config.start_year}_{config.end_year}.json"


def processed_path(config: Config) -> Path:
    return config.processed_path(DATASET)


def request_params(config: Config, start: str, end: str) -> dict[str, str]:
    return {
        "parameters": ",".join(PARAMETERS),
        "community": "AG",
        "longitude": f"{config.lon:.4f}",
        "latitude": f"{config.lat:.4f}",
        "start": start,
        "end": end,
        "format": "JSON",
    }


def download(config: Config) -> dict[str, Any]:
    """Fetch the configured range; falls back to one request per year if the
    single request is rejected (POWER has changed its range limits before)."""
    url = config.endpoint("power") + API_PATH
    start, end = f"{config.start_year}0101", f"{config.end_year}1231"
    try:
        return http.get(config, url, params=request_params(config, start, end)).json()
    except http.HttpError as exc:
        if exc.status_code not in (413, 422):
            raise
        log.info("power: full-range request rejected (%s); requesting year by year", exc.status_code)
    chunks = []
    for year in range(config.start_year, config.end_year + 1):
        chunks.append(http.get(config, url, params=request_params(config, f"{year}0101", f"{year}1231")).json())
        http.polite_sleep(config)
    return merge_chunks(chunks)


def merge_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge year-by-year POWER responses into one response-shaped dict."""
    merged = json.loads(json.dumps(chunks[0]))
    for chunk in chunks[1:]:
        for name, values in chunk["properties"]["parameter"].items():
            merged["properties"]["parameter"][name].update(values)
    merged["header"]["end"] = chunks[-1]["header"]["end"]
    return merged


def parse_response(payload: dict[str, Any]) -> tuple[pd.DataFrame, float]:
    """Turn a POWER JSON response into a daily table and the site elevation (m).

    Fill values (-999) become NaN. Units are checked against `EXPECTED_UNITS`.
    """
    for name, meta in payload.get("parameters", {}).items():
        expected = EXPECTED_UNITS.get(name)
        if expected and meta.get("units") != expected:
            log.warning("power: %s units are %r, expected %r", name, meta.get("units"), expected)
    params = payload["properties"]["parameter"]
    missing = [p for p in PARAMETERS if p not in params]
    if missing:
        raise ValueError(f"POWER response is missing parameters: {missing}")
    df = pd.DataFrame({PARAMETERS[name]: pd.Series(params[name], dtype=float) for name in PARAMETERS})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.sort_index().rename_axis("date").reset_index()
    fill = float(payload.get("header", {}).get("fill_value", FILL_VALUE))
    df = df.replace(fill, np.nan)
    elevation_m = float(payload["geometry"]["coordinates"][2])
    sources = [str(s).upper() for s in payload.get("header", {}).get("sources", [])]
    df["is_synthetic"] = "SYNTHETIC" in sources
    return df, elevation_m


def add_derived(df: pd.DataFrame, latitude_deg: float, elevation_m: float) -> pd.DataFrame:
    """Add `et0_mm` (FAO-56 Penman-Monteith) and `gdd10` (base 10 °C, cap 30 °C)."""
    out = df.copy()
    ea = agro.actual_vapour_pressure_from_rh_mean_kpa(out["tmax_c"], out["tmin_c"], out["rh2m_pct"])
    out["et0_mm"] = agro.et0_fao56(
        tmax_c=out["tmax_c"],
        tmin_c=out["tmin_c"],
        rs_mj_m2=out["rs_mj_m2"],
        wind2m_m_s=out["wind2m_m_s"],
        ea_kpa=ea,
        latitude_deg=latitude_deg,
        elevation_m=elevation_m,
        day_of_year=out["date"].dt.day_of_year,
    )
    out["gdd10"] = agro.gdd(out["tmax_c"], out["tmin_c"], base_c=10.0, cap_c=30.0)
    columns = [c for c in out.columns if c != "is_synthetic"] + ["is_synthetic"]
    return out[columns]


def fetch(config: Config, force: bool = False) -> cache.FetchResult:
    """Download (or reuse) the raw JSON, clean it, add ET0/GDD, run checks."""
    out_path = processed_path(config)
    if out_path.exists() and not force:
        return cache.FetchResult(DATASET, "cached", str(out_path))
    raw = raw_path(config)
    if raw.exists() and not force:
        payload = json.loads(raw.read_text(encoding="utf-8"))
    else:
        payload = download(config)
        raw.write_text(json.dumps(payload), encoding="utf-8")
    df, elevation_m = parse_response(payload)
    df = add_derived(df, config.lat, elevation_m)
    cache.write_table(df, out_path)
    warnings = checks.check_power(df, config)
    cache.update_manifest(
        config, DATASET, rows=len(df), elevation_m=elevation_m,
        files=[str(raw), str(out_path)], warnings=len(warnings),
        **cache.date_range_info(df["date"]),
    )
    return cache.FetchResult(DATASET, "fetched", f"{len(df)} days, elevation {elevation_m:.0f} m")


def load(config: Config) -> pd.DataFrame:
    """The cleaned daily table (cache only, no network)."""
    return cache.read_table(config, DATASET, processed_path(config))


def elevation_m(config: Config) -> float:
    """Site elevation reported by POWER (from the manifest)."""
    entry = cache.read_manifest(config).get(DATASET)
    if not entry:
        raise cache.NotCachedError(DATASET, processed_path(config))
    return float(entry["elevation_m"])


def frost_dates(config: Config) -> pd.DataFrame:
    """Last spring / first fall frost per year (tmin <= 0 °C) from cached POWER."""
    return agro.frost_dates(load(config))


def scenario_years(config: Config) -> dict[int, pd.DataFrame]:
    """Past years as weather scenarios: {year: daily table}."""
    return agro.scenario_years(load(config))
