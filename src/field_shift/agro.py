"""Agro-meteorology helpers: FAO-56 reference ET, growing-degree days, frost dates.

Equation numbers refer to FAO Irrigation and Drainage Paper 56 (Allen et al., 1998),
https://www.fao.org/3/x0490e/x0490e00.htm. All functions accept scalars or numpy /
pandas arrays.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ArrayLike = float | np.ndarray | pd.Series

SOLAR_CONSTANT_MJ_M2_MIN = 0.0820  # Gsc
STEFAN_BOLTZMANN_MJ_K4_M2_DAY = 4.903e-9  # sigma
ALBEDO_GRASS = 0.23  # reference grass albedo


def saturation_vapour_pressure_kpa(t_c: ArrayLike) -> ArrayLike:
    """e°(T), eq. 11."""
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def slope_vapour_pressure_curve_kpa_c(t_mean_c: ArrayLike) -> ArrayLike:
    """Δ, eq. 13."""
    return 4098.0 * saturation_vapour_pressure_kpa(t_mean_c) / (t_mean_c + 237.3) ** 2


def atmospheric_pressure_kpa(elevation_m: float) -> float:
    """P, eq. 7."""
    return 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26


def psychrometric_constant_kpa_c(elevation_m: float) -> float:
    """γ, eq. 8."""
    return 0.000665 * atmospheric_pressure_kpa(elevation_m)


def mean_saturation_vapour_pressure_kpa(tmax_c: ArrayLike, tmin_c: ArrayLike) -> ArrayLike:
    """es, eq. 12."""
    return (saturation_vapour_pressure_kpa(tmax_c) + saturation_vapour_pressure_kpa(tmin_c)) / 2.0


def actual_vapour_pressure_from_rh_mean_kpa(
    tmax_c: ArrayLike, tmin_c: ArrayLike, rh_mean_pct: ArrayLike
) -> ArrayLike:
    """ea from mean relative humidity, eq. 19 (used with POWER's RH2M)."""
    return rh_mean_pct / 100.0 * mean_saturation_vapour_pressure_kpa(tmax_c, tmin_c)


def actual_vapour_pressure_from_rh_minmax_kpa(
    tmax_c: ArrayLike, tmin_c: ArrayLike, rh_max_pct: ArrayLike, rh_min_pct: ArrayLike
) -> ArrayLike:
    """ea from RHmax and RHmin, eq. 17."""
    return (
        saturation_vapour_pressure_kpa(tmin_c) * rh_max_pct / 100.0
        + saturation_vapour_pressure_kpa(tmax_c) * rh_min_pct / 100.0
    ) / 2.0


def extraterrestrial_radiation_mj_m2(latitude_deg: float, day_of_year: ArrayLike) -> ArrayLike:
    """Ra, eq. 21 (with eqs. 22-25)."""
    phi = np.radians(latitude_deg)
    j = np.asarray(day_of_year, dtype=float)
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)
    delta = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))
    return (
        24.0 * 60.0 / np.pi * SOLAR_CONSTANT_MJ_M2_MIN * dr
        * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))
    )


def clear_sky_radiation_mj_m2(ra_mj_m2: ArrayLike, elevation_m: float) -> ArrayLike:
    """Rso, eq. 37."""
    return (0.75 + 2e-5 * elevation_m) * ra_mj_m2


def net_radiation_mj_m2(
    rs_mj_m2: ArrayLike,
    tmax_c: ArrayLike,
    tmin_c: ArrayLike,
    ea_kpa: ArrayLike,
    latitude_deg: float,
    elevation_m: float,
    day_of_year: ArrayLike,
) -> ArrayLike:
    """Rn = Rns - Rnl, eqs. 38-40."""
    ra = extraterrestrial_radiation_mj_m2(latitude_deg, day_of_year)
    rso = clear_sky_radiation_mj_m2(ra, elevation_m)
    rns = (1.0 - ALBEDO_GRASS) * rs_mj_m2
    rs_rso = np.clip(np.divide(rs_mj_m2, rso), 0.0, 1.0)
    tmax_k4 = (np.asarray(tmax_c) + 273.16) ** 4
    tmin_k4 = (np.asarray(tmin_c) + 273.16) ** 4
    rnl = (
        STEFAN_BOLTZMANN_MJ_K4_M2_DAY * (tmax_k4 + tmin_k4) / 2.0
        * (0.34 - 0.14 * np.sqrt(ea_kpa))
        * (1.35 * rs_rso - 0.35)
    )
    return rns - rnl


def wind_speed_2m(u_z_m_s: ArrayLike, height_m: float) -> ArrayLike:
    """Convert wind speed measured at `height_m` to 2 m, eq. 47."""
    return u_z_m_s * 4.87 / np.log(67.8 * height_m - 5.42)


def et0_fao56(
    tmax_c: ArrayLike,
    tmin_c: ArrayLike,
    rs_mj_m2: ArrayLike,
    wind2m_m_s: ArrayLike,
    ea_kpa: ArrayLike,
    latitude_deg: float,
    elevation_m: float,
    day_of_year: ArrayLike,
) -> ArrayLike:
    """Daily FAO-56 Penman-Monteith reference evapotranspiration ET0 in mm/day, eq. 6.

    Soil heat flux G is taken as 0 for daily steps (eq. 42). The mean temperature is
    (Tmax + Tmin) / 2 as FAO-56 prescribes, not a 24-hour mean.
    """
    t_mean = (np.asarray(tmax_c) + np.asarray(tmin_c)) / 2.0
    delta = slope_vapour_pressure_curve_kpa_c(t_mean)
    gamma = psychrometric_constant_kpa_c(elevation_m)
    es = mean_saturation_vapour_pressure_kpa(tmax_c, tmin_c)
    rn = net_radiation_mj_m2(rs_mj_m2, tmax_c, tmin_c, ea_kpa, latitude_deg, elevation_m, day_of_year)
    g = 0.0
    numerator = 0.408 * delta * (rn - g) + gamma * 900.0 / (t_mean + 273.0) * wind2m_m_s * (es - ea_kpa)
    denominator = delta + gamma * (1.0 + 0.34 * np.asarray(wind2m_m_s))
    return np.maximum(numerator / denominator, 0.0)


def gdd(tmax_c: ArrayLike, tmin_c: ArrayLike, base_c: float = 10.0, cap_c: float = 30.0) -> ArrayLike:
    """Growing-degree days, modified method (e.g. the 86/50 °F corn GDD).

    Tmax and Tmin are both clipped to [base, cap] before averaging, so a day never
    contributes less than 0 or more than (cap - base).
    """
    tmax = np.clip(tmax_c, base_c, cap_c)
    tmin = np.clip(tmin_c, base_c, cap_c)
    return (tmax + tmin) / 2.0 - base_c


def frost_dates(daily: pd.DataFrame, threshold_c: float = 0.0, split_month: int = 7) -> pd.DataFrame:
    """Last spring frost and first fall frost per year.

    `daily` needs columns `date` (datetime) and `tmin_c`. A frost day has
    tmin <= `threshold_c`. Spring is Jan 1 up to the first day of `split_month`;
    fall is from then to Dec 31. Years without a frost in a half get NaT.

    Returns columns: year, last_spring_frost, first_fall_frost, frost_free_days.
    """
    df = daily[["date", "tmin_c"]].dropna().copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    frost = df[df["tmin_c"] <= threshold_c]
    is_spring = frost["date"].dt.month < split_month
    spring = frost[is_spring].groupby("year")["date"].max().rename("last_spring_frost")
    fall = frost[~is_spring].groupby("year")["date"].min().rename("first_fall_frost")
    out = pd.DataFrame({"year": sorted(df["year"].unique())}).set_index("year")
    out = out.join(spring).join(fall).reset_index()
    out["frost_free_days"] = (out["first_fall_frost"] - out["last_spring_frost"]).dt.days - 1
    return out


def scenario_years(daily: pd.DataFrame) -> dict[int, pd.DataFrame]:
    """Split a daily weather table into one table per calendar year.

    Each past year becomes a weather scenario the evaluator can replay.
    Only complete years (365 or 366 days) are returned.
    """
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    out: dict[int, pd.DataFrame] = {}
    for year, group in df.groupby(df["date"].dt.year):
        expected = 366 if pd.Timestamp(year=int(year), month=12, day=31).day_of_year == 366 else 365
        if len(group) == expected:
            out[int(year)] = group.reset_index(drop=True)
    return out
