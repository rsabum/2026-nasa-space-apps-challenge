"""FAO-56 ET0 against the worked example, plus GDD and frost-date helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from field_shift import agro

# FAO-56 Chapter 4, Example 18: Brussels (50°48'N, 100 m), 6 July.
TMAX, TMIN, RHMAX, RHMIN = 21.5, 12.3, 84.0, 63.0
U10_KMH, ELEV, LAT, DOY = 10.0, 100.0, 50.0 + 48.0 / 60.0, 187
RS = 22.07  # MJ m-2 day-1, from n = 9.25 h in the example


def test_example18_intermediates() -> None:
    u2 = agro.wind_speed_2m(U10_KMH / 3.6, 10.0)
    assert u2 == pytest.approx(2.078, abs=0.002)
    es = agro.mean_saturation_vapour_pressure_kpa(TMAX, TMIN)
    assert es == pytest.approx(1.997, abs=0.002)
    ea = agro.actual_vapour_pressure_from_rh_minmax_kpa(TMAX, TMIN, RHMAX, RHMIN)
    assert ea == pytest.approx(1.409, abs=0.002)
    assert agro.slope_vapour_pressure_curve_kpa_c((TMAX + TMIN) / 2) == pytest.approx(0.122, abs=0.001)
    assert agro.psychrometric_constant_kpa_c(ELEV) == pytest.approx(0.0666, abs=0.0001)
    ra = agro.extraterrestrial_radiation_mj_m2(LAT, DOY)
    assert ra == pytest.approx(41.09, abs=0.05)
    assert agro.clear_sky_radiation_mj_m2(ra, ELEV) == pytest.approx(30.90, abs=0.05)
    rn = agro.net_radiation_mj_m2(RS, TMAX, TMIN, ea, LAT, ELEV, DOY)
    assert rn == pytest.approx(13.28, abs=0.03)


def test_example18_et0() -> None:
    u2 = agro.wind_speed_2m(U10_KMH / 3.6, 10.0)
    ea = agro.actual_vapour_pressure_from_rh_minmax_kpa(TMAX, TMIN, RHMAX, RHMIN)
    et0 = agro.et0_fao56(TMAX, TMIN, RS, u2, ea, LAT, ELEV, DOY)
    assert et0 == pytest.approx(3.9, abs=0.05)


def test_et0_vectorised_and_non_negative() -> None:
    et0 = agro.et0_fao56(np.array([TMAX, -10.0]), np.array([TMIN, -20.0]), np.array([RS, 1.0]),
                         np.array([2.0, 2.0]), np.array([1.409, 0.1]), LAT, ELEV, np.array([DOY, 10]))
    assert et0.shape == (2,)
    assert (et0 >= 0).all()


@pytest.mark.parametrize(("tmax", "tmin", "expected"), [
    (25.0, 15.0, 10.0),   # plain average minus base
    (35.0, 15.0, 12.5),   # tmax capped at 30
    (8.0, 2.0, 0.0),      # cold day: both clipped to base
    (40.0, 32.0, 20.0),   # hot day: max possible = cap - base
])
def test_gdd(tmax: float, tmin: float, expected: float) -> None:
    assert agro.gdd(tmax, tmin) == pytest.approx(expected)


def _daily(year: int, frost_days: list[str]) -> pd.DataFrame:
    dates = pd.date_range(f"{year}-01-01", f"{year}-12-31")
    tmin = pd.Series(5.0, index=dates)
    tmin[pd.to_datetime(frost_days)] = -1.0
    return pd.DataFrame({"date": dates, "tmin_c": tmin.to_numpy()})


def test_frost_dates() -> None:
    df = _daily(2020, ["2020-01-10", "2020-04-28", "2020-10-05", "2020-11-20"])
    out = agro.frost_dates(df).iloc[0]
    assert out["last_spring_frost"] == pd.Timestamp("2020-04-28")
    assert out["first_fall_frost"] == pd.Timestamp("2020-10-05")
    assert out["frost_free_days"] == 159


def test_frost_dates_threshold_inclusive_and_missing_half() -> None:
    df = _daily(2021, ["2021-03-01"])
    df.loc[df["date"] == "2021-03-02", "tmin_c"] = 0.0  # exactly 0 counts as frost
    out = agro.frost_dates(df).iloc[0]
    assert out["last_spring_frost"] == pd.Timestamp("2021-03-02")
    assert pd.isna(out["first_fall_frost"])


def test_scenario_years_only_complete_years() -> None:
    dates = pd.date_range("2019-06-01", "2021-12-31")
    df = pd.DataFrame({"date": dates, "tmin_c": 1.0})
    years = agro.scenario_years(df)
    assert sorted(years) == [2020, 2021]
    assert len(years[2020]) == 366
