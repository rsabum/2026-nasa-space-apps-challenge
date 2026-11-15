"""Post-fetch sanity checks. They print warnings and never raise.

Each `check_*` returns the list of warning strings (handy for tests) and logs
each one at WARNING level.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from field_shift.config import Config

log = logging.getLogger(__name__)


def _emit(dataset: str, messages: list[str]) -> list[str]:
    for message in messages:
        log.warning("%s check: %s", dataset, message)
    return messages


def check_power(df: pd.DataFrame, config: Config) -> list[str]:
    out: list[str] = []
    dates = pd.to_datetime(df["date"])
    expected = pd.date_range(dates.min(), dates.max(), freq="D")
    if len(expected) != len(dates) or not dates.is_monotonic_increasing:
        out.append(f"{len(expected) - dates.nunique()} missing dates between {dates.min():%Y-%m-%d} and {dates.max():%Y-%m-%d}")
    nan_counts = df.drop(columns=["date"]).isna().sum()
    for column, count in nan_counts[nan_counts > 0].items():
        out.append(f"{count} missing (fill-value) days in {column}")
    bad_t = int((df["tmin_c"] > df["tmax_c"]).sum())
    if bad_t:
        out.append(f"{bad_t} days with tmin > tmax")
    neg_p = int((df["precip_mm"] < 0).sum())
    if neg_p:
        out.append(f"{neg_p} days with negative precipitation")
    lo_p, hi_p = config.section("checks")["annual_precip_mm"]
    lo_e, hi_e = config.section("checks")["annual_et0_mm"]
    years = df.assign(year=dates.dt.year).groupby("year")
    full_years = years.size()[years.size() >= 365].index
    totals = years[["precip_mm", "et0_mm"]].sum().loc[full_years]
    for year, row in totals.iterrows():
        if not lo_p <= row["precip_mm"] <= hi_p:
            out.append(f"{year}: annual precipitation {row['precip_mm']:.0f} mm outside [{lo_p}, {hi_p}]")
        if not lo_e <= row["et0_mm"] <= hi_e:
            out.append(f"{year}: annual ET0 {row['et0_mm']:.0f} mm outside [{lo_e}, {hi_e}]")
    return _emit("power", out)


def check_nass(df: pd.DataFrame, config: Config) -> list[str]:
    out: list[str] = []
    years = set(range(config.start_year, config.end_year + 1))
    for crop in config.cash_crops:
        yields = df[(df["crop"] == crop) & (df["metric"] == "yield") & df["value"].notna()]
        if yields.empty:
            out.append(f"no county yield values for {crop}")
            continue
        missing = sorted(years - set(yields["year"]))
        if missing:
            out.append(f"{crop} yield missing for {len(missing)} years: {_short_list(missing)}")
        prices = df[(df["crop"] == crop) & (df["metric"] == "price_received") & df["value"].notna()]
        if prices.empty:
            out.append(f"no state price-received values for {crop}")
    return _emit("nass", out)


def check_cdl(df: pd.DataFrame) -> list[str]:
    """Central Iowa reality check: the site should be mostly corn and soybeans."""
    out: list[str] = []
    if df.empty:
        return _emit("cdl", ["no CDL years at the site"])
    share = df["cdl_code"].isin([1, 5]).mean()
    if share < 0.6:
        out.append(f"only {share:.0%} of site-years are corn/soybeans; unusual for central Iowa")
    return _emit("cdl", out)


def check_soils(df: pd.DataFrame) -> list[str]:
    out: list[str] = []
    if df.empty:
        return _emit("soils", ["no map units in the box"])
    dominant = df.sort_values("pct_of_box", ascending=False).iloc[0]
    for column in ("awc_cm_cm", "om_pct"):
        if pd.isna(dominant[column]):
            out.append(f"{column} is null for the dominant map unit {dominant['mukey']}")
    total = df["pct_of_box"].sum()
    if not 95 <= total <= 100.5:
        out.append(f"map units cover {total:.1f}% of the box (expected ~100%)")
    return _emit("soils", out)


def check_terrain(summary: pd.DataFrame) -> list[str]:
    out: list[str] = []
    row = summary.iloc[0]
    for column in ("slope_mean_pct", "slope_p90_pct", "slope_max_pct"):
        if not np.isfinite(row[column]):
            out.append(f"{column} is not finite")
    if row["slope_max_pct"] > 60:
        out.append(f"max slope {row['slope_max_pct']:.0f}% is implausible for this landscape; check the DEM")
    return _emit("terrain", out)


def _short_list(values: list[int], limit: int = 8) -> str:
    text = ", ".join(str(v) for v in values[:limit])
    return text + (", ..." if len(values) > limit else "")
