"""Data loader utilities with local CSV caching."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests


CACHE_DIR = Path("data/cache")


def _cache_path(name: str, cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{name}.csv"


def fetch_nasa_power_daily(lat: float, lon: float, start: str, end: str, cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Fetch NASA POWER daily data for a point and cache to CSV.

    TODO: Validate parameter names and add robust error handling for API schema changes.
    """
    key = f"power_{lat:.3f}_{lon:.3f}_{start}_{end}".replace("-", "")
    target = _cache_path(key, cache_dir)
    if target.exists():
        return pd.read_csv(target)

    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "parameters": "PRECTOTCORR,T2M_MIN,T2M_MAX,ALLSKY_SFC_SW_DWN",
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    frame = pd.DataFrame(payload.get("properties", {}).get("parameter", {}))
    frame.to_csv(target, index=False)
    return frame


def load_csv_cache(name: str, cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Load a cached CSV by cache key."""
    return pd.read_csv(_cache_path(name, cache_dir))


def load_smap(cache_name: str = "smap") -> pd.DataFrame:
    """Load cached SMAP-derived CSV.

    TODO: Replace with real SMAP extraction pipeline and documented schema.
    """
    return load_csv_cache(cache_name)


def load_ssurgo(cache_name: str = "ssurgo") -> pd.DataFrame:
    """Load cached SSURGO attributes.

    TODO: Confirm field mapping for available water capacity and erodibility.
    """
    return load_csv_cache(cache_name)


def load_srtm_slope(cache_name: str = "srtm_slope") -> pd.DataFrame:
    """Load cached SRTM slope products.

    TODO: Confirm resolution and slope derivation method for production use.
    """
    return load_csv_cache(cache_name)


def load_cropscape_history(cache_name: str = "cropscape_history") -> pd.DataFrame:
    """Load cached CropScape crop history.

    TODO: Add harmonization for class labels across years.
    """
    return load_csv_cache(cache_name)


def load_nass_yields(cache_name: str = "nass_yields") -> pd.DataFrame:
    """Load cached NASS yields.

    TODO: Add county-to-farm mapping and unit conversion checks.
    """
    return load_csv_cache(cache_name)


def load_prices(cache_name: str = "prices") -> pd.DataFrame:
    """Load cached crop prices.

    TODO: Add source metadata and date normalization.
    """
    return load_csv_cache(cache_name)
