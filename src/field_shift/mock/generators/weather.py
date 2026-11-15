"""Stochastic daily weather generator (Richardson / WGEN style).

Richardson, C. W. (1981), "Stochastic simulation of daily precipitation,
temperature, and solar radiation", Water Resources Research 17(1).

- Precipitation occurrence: first-order Markov chain per calendar month.
- Wet-day amounts: threshold + gamma distribution per month.
- Tmax, Tmin, Rs, RH, log(wind): smooth seasonal mean and SD (two harmonics),
  separately for dry and wet days, plus lag-1 cross-correlated residuals.

`fit()` estimates every parameter from a daily table (used once, by
`scripts/fit_weather_params.py`, on one real POWER response); `generate()`
produces any number of synthetic years from those parameters and a seed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from field_shift import agro

VARIABLES = ["tmax_c", "tmin_c", "rs_mj_m2", "rh2m_pct", "log_wind2m"]
WET_THRESHOLD_MM = 0.5


def harmonics(day_of_year: np.ndarray) -> np.ndarray:
    """Design matrix [1, cos w, sin w, cos 2w, sin 2w] for day-of-year."""
    w = 2.0 * np.pi * np.asarray(day_of_year, dtype=float) / 365.25
    return np.column_stack([np.ones_like(w), np.cos(w), np.sin(w), np.cos(2 * w), np.sin(2 * w)])


def fit_harmonic(day_of_year: np.ndarray, values: np.ndarray) -> list[float]:
    coef, *_ = np.linalg.lstsq(harmonics(day_of_year), np.asarray(values, dtype=float), rcond=None)
    return [float(c) for c in coef]


def eval_harmonic(coef: list[float], day_of_year: np.ndarray) -> np.ndarray:
    return harmonics(day_of_year) @ np.asarray(coef)


def fit_mean_sd(doy: np.ndarray, values: np.ndarray) -> tuple[list[float], list[float]]:
    """Seasonal mean, then seasonal SD from the squared residuals."""
    mean = fit_harmonic(doy, values)
    resid = values - eval_harmonic(mean, doy)
    sd = fit_harmonic(doy, resid ** 2)
    return mean, sd


def eval_sd(coef: list[float], doy: np.ndarray, floor: float = 1e-3) -> np.ndarray:
    return np.sqrt(np.maximum(eval_harmonic(coef, doy), floor ** 2))


def _prepare(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["doy"] = df["date"].dt.day_of_year
    df["month"] = df["date"].dt.month
    df["wet"] = df["precip_mm"] >= WET_THRESHOLD_MM
    df["log_wind2m"] = np.log(df["wind2m_m_s"].clip(lower=0.1))
    return df


def fit(daily: pd.DataFrame) -> dict[str, Any]:
    """Estimate generator parameters from a daily table with POWER column names."""
    df = _prepare(daily)
    wet, month = df["wet"].to_numpy(), df["month"].to_numpy()
    p_wd, p_ww, shape, scale = [], [], [], []
    for m in range(1, 13):
        today = month[1:] == m
        prev_dry, prev_wet = today & ~wet[:-1], today & wet[:-1]
        p_wd.append(float(wet[1:][prev_dry].mean()))
        p_ww.append(float(wet[1:][prev_wet].mean()))
        amounts = df.loc[(df["month"] == m) & df["wet"], "precip_mm"].to_numpy() - WET_THRESHOLD_MM
        mean, var = amounts.mean(), amounts.var()
        shape.append(float(mean ** 2 / var))
        scale.append(float(var / mean))

    mean_coef: dict[str, dict[str, list[float]]] = {"dry": {}, "wet": {}}
    sd_coef: dict[str, dict[str, list[float]]] = {"dry": {}, "wet": {}}
    z = np.zeros((len(df), len(VARIABLES)))
    for state, mask in (("dry", ~df["wet"]), ("wet", df["wet"])):
        doy = df.loc[mask, "doy"].to_numpy()
        for j, var in enumerate(VARIABLES):
            values = df.loc[mask, var].to_numpy()
            mu, sd = fit_mean_sd(doy, values)
            mean_coef[state][var], sd_coef[state][var] = mu, sd
            z[mask.to_numpy(), j] = (values - eval_harmonic(mu, doy)) / eval_sd(sd, doy)
    m0 = np.corrcoef(z, rowvar=False)
    m1 = (z[1:].T @ z[:-1]) / (len(z) - 1)
    a = m1 @ np.linalg.inv(m0)
    bbt = m0 - a @ m1.T
    eigval, eigvec = np.linalg.eigh((bbt + bbt.T) / 2)
    b = eigvec @ np.diag(np.sqrt(np.clip(eigval, 1e-6, None)))

    midpoint = (df["tmax_c"] + df["tmin_c"]) / 2
    gwet = {}
    for column in ("gwettop_frac", "gwetroot_frac"):
        mu, sd = fit_mean_sd(df["doy"].to_numpy(), df[column].to_numpy())
        gwet[column] = {"mean_coef": mu, "sd_coef": sd,
                        "min": float(df[column].min()), "max": float(df[column].max())}
    return {
        "wet_threshold_mm": WET_THRESHOLD_MM,
        "p_wet_given_dry": p_wd, "p_wet_given_wet": p_ww,
        "gamma_shape": shape, "gamma_scale_mm": scale,
        "variables": VARIABLES, "mean_coef": mean_coef, "sd_coef": sd_coef,
        "ar1_a": a.tolist(), "ar1_b": b.tolist(),
        "tmean_offset_coef": fit_harmonic(df["doy"].to_numpy(), (df["tmean_c"] - midpoint).to_numpy()),
        "gwet": gwet,
        "observed_ranges": {v: [float(df[v].min()), float(df[v].max())]
                            for v in ("rh2m_pct", "wind2m_m_s", "rs_mj_m2")},
    }


def generate(params: dict[str, Any], start: str, end: str, latitude_deg: float,
             elevation_m: float, rng: np.random.Generator) -> pd.DataFrame:
    """Synthetic daily weather from `start` to `end` (inclusive), POWER column names.

    GWETTOP/GWETROOT are *not* produced here (see `soilwater.py`).
    """
    dates = pd.date_range(start, end, freq="D")
    n, doy, month = len(dates), dates.day_of_year.to_numpy(), dates.month.to_numpy() - 1
    p_wd, p_ww = np.asarray(params["p_wet_given_dry"]), np.asarray(params["p_wet_given_wet"])
    shape, scale = np.asarray(params["gamma_shape"]), np.asarray(params["gamma_scale_mm"])
    a, b = np.asarray(params["ar1_a"]), np.asarray(params["ar1_b"])
    wet = np.zeros(n, dtype=bool)
    precip = np.zeros(n)
    z = np.zeros((n, len(params["variables"])))
    uniform = rng.random(n)
    eps = rng.standard_normal(z.shape)
    for t in range(n):
        p = p_ww[month[t]] if t > 0 and wet[t - 1] else p_wd[month[t]]
        wet[t] = uniform[t] < p
        z[t] = (a @ z[t - 1] if t > 0 else 0.0) + b @ eps[t]
    n_wet = int(wet.sum())
    precip[wet] = params["wet_threshold_mm"] + rng.gamma(shape[month[wet]], scale[month[wet]], n_wet)

    out = pd.DataFrame({"date": dates, "precip_mm": precip})
    for j, var in enumerate(params["variables"]):
        values = np.empty(n)
        for state, mask in (("dry", ~wet), ("wet", wet)):
            mu = eval_harmonic(params["mean_coef"][state][var], doy[mask])
            sd = eval_sd(params["sd_coef"][state][var], doy[mask])
            values[mask] = mu + sd * z[mask, j]
        out[var] = values
    out["wind2m_m_s"] = np.exp(out.pop("log_wind2m"))
    _apply_physical_limits(out, params, latitude_deg, elevation_m, doy)
    out["tmean_c"] = (out["tmax_c"] + out["tmin_c"]) / 2 + eval_harmonic(params["tmean_offset_coef"], doy)
    return out[["date", "tmean_c", "tmax_c", "tmin_c", "precip_mm", "rs_mj_m2", "rh2m_pct", "wind2m_m_s"]]


def _apply_physical_limits(df: pd.DataFrame, params: dict[str, Any], latitude_deg: float,
                           elevation_m: float, doy: np.ndarray) -> None:
    """Keep generated values physically possible (in place)."""
    swap = df["tmin_c"] > df["tmax_c"] - 0.5
    df.loc[swap, "tmin_c"] = df.loc[swap, "tmax_c"] - 0.5
    rso = agro.clear_sky_radiation_mj_m2(agro.extraterrestrial_radiation_mj_m2(latitude_deg, doy), elevation_m)
    df["rs_mj_m2"] = np.clip(df["rs_mj_m2"], 0.05 * rso, rso)
    lo, hi = params["observed_ranges"]["rh2m_pct"]
    df["rh2m_pct"] = df["rh2m_pct"].clip(max(lo - 5, 5), min(hi, 100))
    lo, hi = params["observed_ranges"]["wind2m_m_s"]
    df["wind2m_m_s"] = df["wind2m_m_s"].clip(max(lo * 0.8, 0.1), hi * 1.2)
    for column in ("tmax_c", "tmin_c", "rs_mj_m2", "rh2m_pct", "wind2m_m_s"):
        df[column] = df[column].round(2)
    df["precip_mm"] = df["precip_mm"].round(2)
