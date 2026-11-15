"""The synthetic world: deterministic, physically bounded, close to the fitted statistics."""

from __future__ import annotations

import numpy as np
import pytest

from field_shift import agro
from field_shift.config import load_config
from field_shift.data.cdl_legend import MVP_CROP_CODES
from field_shift.mock.world import World


def test_same_seed_same_world(mock_world: World, tmp_path) -> None:
    other = World(load_config(paths={"data_dir": str(tmp_path)}))
    assert other.weather.equals(mock_world.weather)
    assert other.county_yields.equals(mock_world.county_yields)


def test_different_seed_different_weather(mock_world: World, tmp_path) -> None:
    other = World(load_config(paths={"data_dir": str(tmp_path)}, mock={"seed": 7, "params": "story_county_ia.yaml"}))
    assert not np.allclose(other.weather["precip_mm"].head(365), mock_world.weather["precip_mm"].head(365))


def test_weather_is_physically_bounded(mock_world: World) -> None:
    d = mock_world.weather
    assert (d["tmin_c"] <= d["tmax_c"]).all()
    assert (d["precip_mm"] >= 0).all()
    assert d["rh2m_pct"].between(0, 100).all()
    assert (d["wind2m_m_s"] > 0).all()
    ra = agro.extraterrestrial_radiation_mj_m2(mock_world.lat, d["date"].dt.day_of_year)
    assert (d["rs_mj_m2"] <= agro.clear_sky_radiation_mj_m2(ra, mock_world.elevation_m) + 0.006).all()  # 2-decimal rounding
    assert d[["gwettop_frac", "gwetroot_frac"]].stack().between(0, 1).all()


def test_weather_matches_fitted_targets(mock_world: World) -> None:
    targets = mock_world.params["weather"]["fit_targets"]
    d = mock_world.weather
    years = d.groupby(d["date"].dt.year)
    assert years["precip_mm"].sum().mean() == pytest.approx(targets["annual_precip_mm_mean"], rel=0.1)
    assert years["et0_mm"].sum().mean() == pytest.approx(targets["annual_et0_mm_mean"], rel=0.1)
    assert d["tmax_c"].mean() == pytest.approx(targets["tmax_c_mean"], abs=0.7)
    assert d["tmin_c"].mean() == pytest.approx(targets["tmin_c_mean"], abs=0.7)
    assert (d["precip_mm"] >= 0.5).mean() == pytest.approx(targets["wet_day_fraction"], abs=0.02)


def test_soil_wetness_follows_rain(mock_world: World) -> None:
    d = mock_world.weather
    rainy = d["precip_mm"] > 20
    change = d["gwettop_frac"].diff()
    assert change[rainy].mean() > 0.02 > change[~rainy].mean()


def test_site_is_inside_a_crop_field(mock_world: World) -> None:
    x, y = mock_world.site_albers
    codes = [mock_world.fields.site_code(x, y, year) for year in range(2008, 2026)]
    assert np.isin(codes, list(MVP_CROP_CODES.values())).mean() > 0.8


def test_soils_tile_the_region_and_follow_terrain(mock_world: World) -> None:
    soils = mock_world.soils
    assert len(soils.mapunits) == 5
    assert {c["cokey"] for c in soils.components} == {h["cokey"] for h in soils.horizons}
    centroids = {}
    for mukey, poly in soils.polygons:
        centroids.setdefault(mukey, []).append(poly.centroid)
    relief = {mukey: np.mean([mock_world.surface.relative_elevation(c.x, c.y) for c in pts])
              for mukey, pts in centroids.items()}
    names = {m["mukey"]: m["muname"] for m in soils.mapunits}
    lowest, highest = min(relief, key=relief.get), max(relief, key=relief.get)
    assert names[lowest].startswith("Canisteo") and names[highest].startswith("Clarion")


def test_yields_respond_to_weather(mock_world: World) -> None:
    from field_shift.mock.generators.yields import weather_indices

    idx = weather_indices(mock_world.weather)
    corn = mock_world.county_yields.query("crop == 'corn'").set_index("year")["value"]
    detrended = corn - np.polyval(np.polyfit(corn.index, corn.values, 1), corn.index)
    assert np.corrcoef(detrended, idx.loc[corn.index, "water"])[0, 1] > 0.2
