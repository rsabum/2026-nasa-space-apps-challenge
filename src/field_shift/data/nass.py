"""USDA NASS QuickStats: county yields and state "price received" (free API key).

API docs: https://quickstats.nass.usda.gov/api
Key: `NASS_API_KEY` in `.env`. Without it this dataset is skipped, not crashed.

Processed table `nass.parquet` (tidy):
    year, crop, metric, value, unit, short_desc, reference_period_desc, is_synthetic
`metric` is "yield" (county) or "price_received" (state, annual).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from field_shift.config import Config
from field_shift.data import cache, checks, credentials, http

log = logging.getLogger(__name__)

DATASET = "nass"
MAX_ROWS = 50_000  # QuickStats rejects queries returning more than this

# QuickStats `short_desc` for each MVP cash crop. Cereal rye is a cover crop: no series.
SERIES: dict[str, dict[str, str]] = {
    "corn": {
        "yield": "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE",
        "price_received": "CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU",
    },
    "soybeans": {
        "yield": "SOYBEANS - YIELD, MEASURED IN BU / ACRE",
        "price_received": "SOYBEANS - PRICE RECEIVED, MEASURED IN $ / BU",
    },
    "oats": {
        "yield": "OATS - YIELD, MEASURED IN BU / ACRE",
        "price_received": "OATS - PRICE RECEIVED, MEASURED IN $ / BU",
    },
    "winter_wheat": {
        "yield": "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE",
        # NASS publishes the state price for all wheat, not winter wheat alone.
        "price_received": "WHEAT - PRICE RECEIVED, MEASURED IN $ / BU",
    },
    "alfalfa": {
        "yield": "HAY, ALFALFA - YIELD, MEASURED IN TONS / ACRE",
        "price_received": "HAY, ALFALFA - PRICE RECEIVED, MEASURED IN $ / TON",
    },
}
# Preferred price reference period (annual marketing-year average), then calendar year.
PRICE_PERIOD_PREFERENCE = ("MARKETING YEAR", "YEAR")


def processed_path(config: Config) -> Path:
    return config.processed_path(DATASET)


def county_fips(config: Config) -> str:
    """County FIPS from config, else from the Census geocoder."""
    if config.county_fips:
        return config.county_fips
    url = config.endpoint("census") + "/geocoder/geographies/coordinates"
    params = {
        "x": config.lon, "y": config.lat, "benchmark": "Public_AR_Current",
        "vintage": "Current_Current", "layers": "Counties", "format": "json",
    }
    county = http.get(config, url, params=params).json()["result"]["geographies"]["Counties"][0]
    if county["STATE"] != config.state_fips:
        raise ValueError(f"site is in state {county['STATE']}, config says {config.state_fips}")
    log.info("nass: site is in %s (county FIPS %s)", county["NAME"], county["COUNTY"])
    return str(county["COUNTY"])


def query_params(config: Config, crop: str, metric: str, county: str) -> dict[str, str]:
    """QuickStats filter parameters (without the key)."""
    params = {
        "short_desc": SERIES[crop][metric],
        "source_desc": "SURVEY",
        "domain_desc": "TOTAL",
        "state_fips_code": config.state_fips,
        "year__GE": str(config.start_year),
        "year__LE": str(config.end_year),
        "format": "JSON",
    }
    if metric == "yield":
        params.update(agg_level_desc="COUNTY", county_code=county, reference_period_desc="YEAR")
    else:
        params.update(agg_level_desc="STATE", freq_desc="ANNUAL")
    return params


def download_series(config: Config, key: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """`get_counts` first (to respect the row limit and skip empty series), then `api_get`."""
    base = config.endpoint("nass") + "/api"
    count = int(http.get(config, f"{base}/get_counts/", params={"key": key, **params}).json()["count"])
    http.polite_sleep(config)
    if count == 0:
        return []
    if count > MAX_ROWS:
        raise ValueError(f"QuickStats query would return {count} rows (> {MAX_ROWS}); narrow it")
    rows = http.get(config, f"{base}/api_get/", params={"key": key, **params}).json()["data"]
    http.polite_sleep(config)
    return rows


def parse_value(text: Any) -> float:
    """QuickStats values are strings like '1,234.5' or codes like '(D)' (suppressed)."""
    cleaned = str(text).strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return np.nan


def clean_rows(rows: list[dict[str, Any]], crop: str, metric: str, is_synthetic: bool) -> pd.DataFrame:
    """Raw QuickStats records -> tidy rows. Suppressed values become NaN (never filled)."""
    columns = ["year", "crop", "metric", "value", "unit", "short_desc", "reference_period_desc", "is_synthetic"]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows)
    df = df[df["freq_desc"] == "ANNUAL"] if "freq_desc" in df else df
    out = pd.DataFrame({
        "year": df["year"].astype(int),
        "crop": crop,
        "metric": metric,
        "value": df["Value"].map(parse_value),
        "unit": df["unit_desc"],
        "short_desc": df["short_desc"],
        "reference_period_desc": df["reference_period_desc"],
        "is_synthetic": is_synthetic,
    })
    suppressed = df.loc[out["value"].isna(), "Value"].str.strip().unique().tolist()
    if suppressed:
        log.warning("nass: %s %s has %d non-numeric values %s (kept as NaN)",
                    crop, metric, int(out["value"].isna().sum()), suppressed)
    if metric == "price_received":
        out = _prefer_period(out)
    return out[columns].sort_values("year").reset_index(drop=True)


def _prefer_period(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one price per year, preferring the marketing-year average."""
    rank = {p: i for i, p in enumerate(PRICE_PERIOD_PREFERENCE)}
    df = df[df["reference_period_desc"].isin(rank)].copy()
    df["_rank"] = df["reference_period_desc"].map(rank)
    return df.sort_values(["year", "_rank"]).drop_duplicates("year").drop(columns="_rank")


def fetch(config: Config, force: bool = False) -> cache.FetchResult:
    out_path = processed_path(config)
    if out_path.exists() and not force:
        return cache.FetchResult(DATASET, "cached", str(out_path))
    key = credentials.nass_api_key()
    if key is None:
        return cache.FetchResult(
            DATASET, "skipped",
            "NASS_API_KEY is not set. Get a free key at https://quickstats.nass.usda.gov/api "
            "and add it to .env (mock mode accepts any value, e.g. NASS_API_KEY=mock-key).",
        )
    county = county_fips(config)
    tables = []
    for crop in config.cash_crops:
        if crop not in SERIES:
            log.warning("nass: no QuickStats series defined for %s; skipping", crop)
            continue
        for metric in SERIES[crop]:
            raw = config.raw_dir(DATASET) / f"{metric}_{crop}.json"
            if raw.exists() and not force:
                rows = json.loads(raw.read_text(encoding="utf-8"))
            else:
                rows = download_series(config, key, query_params(config, crop, metric, county))
                raw.write_text(json.dumps(rows), encoding="utf-8")
            tables.append(clean_rows(rows, crop, metric, is_synthetic=config.is_mock))
    df = pd.concat(tables, ignore_index=True)
    cache.write_table(df, out_path)
    warnings = checks.check_nass(df, config)
    cache.update_manifest(
        config, DATASET, rows=len(df), county_fips=county, state_fips=config.state_fips,
        date_min=str(df["year"].min()), date_max=str(df["year"].max()), warnings=len(warnings),
    )
    return cache.FetchResult(DATASET, "fetched", f"{len(df)} rows for {df['crop'].nunique()} crops")


def load(config: Config) -> pd.DataFrame:
    return cache.read_table(config, DATASET, processed_path(config))
