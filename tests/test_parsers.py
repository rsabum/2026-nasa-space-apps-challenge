"""Unit tests for parsing, cleaning and raster helpers (no server)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from field_shift.config import Config
from field_shift.data import checks, http, nass, power, soils, terrain

from conftest import REAL


def test_power_fill_values_become_nan() -> None:
    import json

    payload = json.loads((REAL / "power_daily_point.json").read_text())
    first = next(iter(payload["properties"]["parameter"]["T2M_MAX"]))
    payload["properties"]["parameter"]["T2M_MAX"][first] = -999.0
    df, elevation = power.parse_response(payload)
    assert np.isnan(df.loc[0, "tmax_c"]) and elevation == pytest.approx(310.22)


def test_power_merge_chunks() -> None:
    import json

    payload = json.loads((REAL / "power_daily_point.json").read_text())
    a = json.loads(json.dumps(payload))
    b = json.loads(json.dumps(payload))
    for name in b["properties"]["parameter"]:
        b["properties"]["parameter"][name] = {"20020101": 1.0}
    b["header"]["end"] = "20020101"
    merged = power.merge_chunks([a, b])
    assert len(merged["properties"]["parameter"]["T2M"]) == 6 and merged["header"]["end"] == "20020101"


def test_power_checks_flag_bad_rows(offline_config: Config) -> None:
    dates = pd.date_range("2020-01-01", "2020-01-10")
    df = pd.DataFrame({"date": dates, "tmin_c": 5.0, "tmax_c": 10.0, "precip_mm": 1.0, "et0_mm": 1.0})
    df.loc[3, "tmin_c"] = 12.0
    df.loc[4, "precip_mm"] = -1.0
    df = df.drop(index=6)
    warnings = checks.check_power(df, offline_config)
    assert any("tmin > tmax" in w for w in warnings)
    assert any("negative precipitation" in w for w in warnings)
    assert any("missing dates" in w for w in warnings)


@pytest.mark.parametrize(("text", "expected"), [("185.3", 185.3), ("1,234", 1234.0), ("   (D)", np.nan), ("(Z)", np.nan)])
def test_nass_parse_value(text: str, expected: float) -> None:
    value = nass.parse_value(text)
    assert (np.isnan(value) and np.isnan(expected)) or value == expected


def _nass_row(year: int, value: str, period: str = "YEAR") -> dict:
    return {"year": year, "Value": value, "unit_desc": "$ / BU", "short_desc": "X", "freq_desc": "ANNUAL",
            "reference_period_desc": period}


def test_nass_prices_prefer_marketing_year() -> None:
    rows = [_nass_row(2020, "3.50", "YEAR"), _nass_row(2020, "3.60", "MARKETING YEAR"), _nass_row(2021, "4.00")]
    df = nass.clean_rows(rows, "corn", "price_received", is_synthetic=False)
    assert df.set_index("year")["value"].to_dict() == {2020: 3.6, 2021: 4.0}


def test_nass_suppressed_kept_as_nan() -> None:
    df = nass.clean_rows([_nass_row(2020, "(D)"), _nass_row(2021, "50")], "oats", "yield", is_synthetic=False)
    assert df["value"].isna().sum() == 1 and len(df) == 2


def test_soils_horizon_weighting_by_hand() -> None:
    horizons = pd.DataFrame({
        "cokey": ["1", "1", "1"], "hzdept_r": [0, 20, 80], "hzdepb_r": [20, 80, 150],
        "awc_r": [0.20, 0.15, 0.10], "om_r": [4.0, 1.0, 0.5], "sandtotal_r": [40, 40, 40],
        "silttotal_r": [35, 35, 35], "claytotal_r": [25, 25, 25], "kwfact": [0.24, 0.28, 0.32],
    })
    out = soils.aggregate_horizons(horizons).iloc[0]
    # 0-100 cm: 20 cm @0.20, 60 cm @0.15, 20 cm @0.10 (third horizon clipped at 100)
    assert out["awc_cm_cm"] == pytest.approx((20 * 0.20 + 60 * 0.15 + 20 * 0.10) / 100)
    assert out["aws_0_100_mm"] == pytest.approx((20 * 0.20 + 60 * 0.15 + 20 * 0.10) * 10)
    assert out["kwfact_surface"] == pytest.approx(0.24)


def test_soils_component_weighting() -> None:
    components = pd.DataFrame({"mukey": ["9", "9"], "cokey": ["a", "b"], "compname": ["Major", "Minor"],
                               "comppct_r": [80, 20], "majcompflag": ["Yes", "No"], "drainagecl": ["W", "P"],
                               "hydgrp": ["B", "C/D"], "slope_l": [2, 0], "slope_r": [3, 1], "slope_h": [5, 2]})
    props = pd.DataFrame({"cokey": ["a", "b"], "awc_cm_cm": [0.2, 0.1], "om_pct": [3.0, 6.0], "sand_pct": [40, 30],
                          "silt_pct": [35, 40], "clay_pct": [25, 30], "aws_0_100_mm": [200, 100],
                          "kwfact_surface": [0.3, 0.2]})
    out = soils.aggregate_mapunits(components, props).iloc[0]
    assert out["awc_cm_cm"] == pytest.approx(0.18)
    assert out["om_pct"] == pytest.approx(3.6)
    assert out["compname"] == "Major" and out["hydgrp"] == "B" and out["slope_h_pct"] == 5


def test_soils_in_list_is_injection_safe() -> None:
    with pytest.raises(ValueError):
        soils.sql_mapunits(["1'); DROP TABLE mapunit; --"])


def test_slope_of_a_plane() -> None:
    res = 10.0
    y, x = np.mgrid[0:50, 0:50] * res
    dem = 0.03 * x + 0.04 * y  # 3 % east, 4 % north -> 5 %
    slope = terrain.slope_percent(dem, res)
    assert np.allclose(slope, 5.0)


def test_slope_zones() -> None:
    slope = np.array([[0.5, 2.0, 4.9], [7.0, 20.0, np.nan]], dtype="float32")
    zones = terrain.slope_zones(slope, [2, 5, 9, 14])
    assert zones.tolist() == [[1, 2, 2], [3, 5, 0]]


def test_utm_zone() -> None:
    assert terrain.utm_crs(-93.47, 42.03) == "EPSG:32615"


def test_redact_hides_secrets() -> None:
    text = "https://x/api?key=abc123&short_desc=CORN&token=zzz"
    assert http.redact(text) == "https://x/api?key=***&short_desc=CORN&token=***"


def test_config_bbox_is_about_2km(offline_config: Config) -> None:
    from pyproj import Geod

    w, s, e, n = offline_config.bbox.as_tuple()
    geod = Geod(ellps="WGS84")
    assert geod.inv(w, offline_config.lat, e, offline_config.lat)[2] == pytest.approx(2000, rel=0.01)
    assert geod.inv(offline_config.lon, s, offline_config.lon, n)[2] == pytest.approx(2000, rel=0.01)
    assert offline_config.endpoint("power") == "http://127.0.0.1:8765/power"
