"""Synthetic POWER soil wetness (GWETTOP, GWETROOT) from synthetic rain and ET0.

A two-layer linear bucket gives the *timing* (wetting after rain, drying in
summer). Its output is then mapped onto the seasonal mean and SD fitted from the
real POWER sample, so the level and spread match the site.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from field_shift.mock.generators.weather import eval_harmonic, eval_sd, fit_mean_sd


def bucket(precip_mm: np.ndarray, et0_mm: np.ndarray, params: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Relative wetness (0-1) of a top and a root-zone layer."""
    cap_top, cap_root = params["top_capacity_mm"], params["root_capacity_mm"]
    k_top, k_root = params["top_drainage_per_day"], params["root_drainage_per_day"]
    w_top, w_root = cap_top / 2, cap_root / 2
    top, root = np.empty(len(precip_mm)), np.empty(len(precip_mm))
    for t, (p, e) in enumerate(zip(precip_mm, et0_mm)):
        w_top += p - e * 0.5 * w_top / cap_top
        drain = k_top * w_top + max(w_top - cap_top, 0.0)
        w_top = min(max(w_top - drain, 0.0), cap_top)
        w_root += drain - e * 0.5 * w_root / cap_root
        w_root -= k_root * w_root + max(w_root - cap_root, 0.0)
        w_root = min(max(w_root, 0.0), cap_root)
        top[t], root[t] = w_top / cap_top, w_root / cap_root
    return top, root


def rescale(values: np.ndarray, doy: np.ndarray, target: dict[str, Any]) -> np.ndarray:
    """Map a series onto the target seasonal mean/SD, then clip to the observed range."""
    mu, sd = fit_mean_sd(doy, values)
    z = (values - eval_harmonic(mu, doy)) / eval_sd(sd, doy)
    out = eval_harmonic(target["mean_coef"], doy) + eval_sd(target["sd_coef"], doy) * z
    return np.clip(out, target["min"], target["max"]).round(2)


def generate(weather: pd.DataFrame, et0_mm: np.ndarray, bucket_params: dict[str, Any],
             gwet_params: dict[str, Any]) -> pd.DataFrame:
    """Return `gwettop_frac` and `gwetroot_frac` aligned with `weather`."""
    top, root = bucket(weather["precip_mm"].to_numpy(), np.asarray(et0_mm), bucket_params)
    doy = pd.to_datetime(weather["date"]).dt.day_of_year.to_numpy()
    return pd.DataFrame({
        "gwettop_frac": rescale(top, doy, gwet_params["gwettop_frac"]),
        "gwetroot_frac": rescale(root, doy, gwet_params["gwetroot_frac"]),
    })
