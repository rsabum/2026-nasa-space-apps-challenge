"""Run the whole data layer against the in-process mock services."""

from __future__ import annotations

import pandas as pd
import pytest
import rasterio

from field_shift.config import Config
from field_shift.data import DATASETS, cache, cdl, nass, power, soils, terrain
from field_shift.data.__main__ import main, run_fetch


@pytest.fixture
def with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NASS_API_KEY", "mock-key")
    monkeypatch.setenv("MOCK_EARTHDATA_TOKEN", "mock-token")


def test_fetch_all_then_load_everything(config: Config, with_keys: None) -> None:
    results = {r.dataset: r for r in run_fetch(config, list(DATASETS), force=False)}
    assert {name: r.status for name, r in results.items()} == {name: "fetched" for name in DATASETS}

    weather = power.load(config)
    assert len(weather) == 9131 and weather["is_synthetic"].all()
    assert {"et0_mm", "gdd10", "precip_mm", "gwetroot_frac"} <= set(weather.columns)
    assert len(power.frost_dates(config)) == 25
    assert len(power.scenario_years(config)) == 25
    assert power.elevation_m(config) == pytest.approx(310.22)

    yields = nass.load(config)
    assert set(yields["crop"]) == set(config.cash_crops)
    assert set(yields["metric"]) == {"yield", "price_received"}
    assert yields.loc[yields["crop"] == "alfalfa", "unit"].isin(["TONS / ACRE", "$ / TON"]).all()

    site = cdl.load(config)
    assert list(site["year"]) == list(range(2008, 2026))
    assert site["cdl_code"].isin([1, 5]).mean() > 0.6
    fractions = cdl.load_box_fractions(config)
    assert fractions.groupby("year")["fraction"].sum().round(6).eq(1).all()
    with rasterio.open(config.processed_dir() / "cdl" / "box_2025.tif") as src:
        assert src.crs.to_epsg() == 5070 and abs(src.transform.a) == 10

    soil = soils.load(config)
    assert soil["pct_of_box"].sum() == pytest.approx(100, abs=0.5)
    assert soil[["awc_cm_cm", "om_pct", "kwfact_surface", "aws_0_100_mm"]].notna().all().all()
    assert len(soils.load_polygons(config)["features"]) == len(soil)

    summary = terrain.load(config).iloc[0]
    assert summary["source"] == "srtm"
    assert 0 < summary["slope_mean_pct"] < summary["slope_p90_pct"] <= summary["slope_max_pct"] < 20
    with rasterio.open(terrain.raster_path(config, "slope_zones")) as src:
        assert set(pd.unique(src.read(1).ravel())) <= {0, 1, 2, 3, 4, 5}

    # A second run uses the cache for everything.
    again = run_fetch(config, list(DATASETS), force=False)
    assert all(r.status == "cached" for r in again)


def test_terrain_falls_back_to_3dep_without_earthdata(config: Config) -> None:
    result = terrain.fetch(config)
    assert result.status == "fetched"
    summary = terrain.load(config).iloc[0]
    assert summary["source"] == "3dep" and summary["resolution_m"] == 10
    assert cache.read_manifest(config)["terrain"]["skipped_sources"][0].startswith("srtm: no Earthdata login")


def test_nass_skipped_without_key(config: Config) -> None:
    result = nass.fetch(config)
    assert result.status == "skipped" and "NASS_API_KEY" in result.message
    with pytest.raises(cache.NotCachedError):
        nass.load(config)


def test_force_refetches(config: Config) -> None:
    assert power.fetch(config).status == "fetched"
    assert power.fetch(config).status == "cached"
    assert power.fetch(config, force=True).status == "fetched"


def test_load_before_fetch_says_how_to_fix(offline_config: Config) -> None:
    with pytest.raises(cache.NotCachedError, match="fetch --dataset soils"):
        soils.load(offline_config)


def test_status_command(config: Config, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    power.fetch(config)
    monkeypatch.setattr("field_shift.data.__main__.load_config", lambda path=None: config)
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "MOCK" in out and "MISSING NASS_API_KEY" in out
    assert "crops.csv" in out and "blank cells" in out


def test_fetch_refuses_when_mock_server_is_down(offline_config: Config) -> None:
    config = offline_config
    config.raw["endpoints"]["mock_base_url"] = "http://127.0.0.1:9"  # nothing listens on the discard port
    with pytest.raises(SystemExit):
        run_fetch(config, ["power"], force=False)
