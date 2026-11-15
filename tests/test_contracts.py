"""Contract tests: the same parser must accept a REAL response (captured once by
scripts/capture_fixtures.py) and the mock's response, with the same output shape.
This catches the mock drifting away from the real API formats."""

from __future__ import annotations

import json

import requests
from shapely.geometry import box as shapely_box

from field_shift.config import Config
from field_shift.data import cdl, nass, power, soils, terrain
from field_shift.data.cdl_legend import crop_name

from conftest import REAL


def _real(name: str):
    text = (REAL / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


def test_power_real_and_mock_parse_identically(config: Config) -> None:
    real_df, real_elev = power.parse_response(_real("power_daily_point.json"))
    params = power.request_params(config, "20010101", "20010105")
    mock_payload = requests.get(config.endpoint("power") + power.API_PATH, params=params, timeout=30).json()
    mock_df, mock_elev = power.parse_response(mock_payload)
    assert list(real_df.columns) == list(mock_df.columns)
    assert dict(real_df.dtypes) == dict(mock_df.dtypes)
    assert len(real_df) == len(mock_df) == 5
    assert not real_df["is_synthetic"].any() and mock_df["is_synthetic"].all()
    assert real_elev == mock_elev  # mock reports the POWER site elevation
    assert set(_real("power_daily_point.json")["parameters"]) == set(mock_payload["parameters"])
    for name, meta in _real("power_daily_point.json")["parameters"].items():
        assert mock_payload["parameters"][name]["units"] == meta["units"]


def test_cdl_point_real_and_mock(config: Config) -> None:
    code, category = cdl.parse_point_response(_real("cdl_point_2025.xml"))
    assert crop_name(code) == category  # embedded legend agrees with the live service
    x, y = cdl.to_albers(config.lon, config.lat)
    xml = requests.get(config.endpoint("cdl_point") + cdl.POINT_PATH,
                       params={"year": 2025, "x": x, "y": y}, timeout=30).text
    mock_code, mock_category = cdl.parse_point_response(xml)
    assert crop_name(mock_code) == mock_category
    assert xml.startswith('<ns1:GetCDLValueResponse xmlns:ns1="http://cropscape.csiss.gmu.edu/CDLService/">')


def test_cdl_catalog_real_and_mock(config: Config) -> None:
    real = cdl.parse_catalog(_real("cdl_catalog.json"))
    mock = cdl.parse_catalog(requests.get(config.endpoint("cdl_image") + cdl.IMAGE_SERVICE_PATH + "/query",
                                          timeout=30).json())
    assert real[2025]["pixel_m"] == mock[2025]["pixel_m"] == 10
    assert real[2015]["pixel_m"] == mock[2015]["pixel_m"] == 30
    for year in range(2008, 2026):
        assert real[year]["object_id"] == mock[year]["object_id"]


def _sda_tables(source) -> tuple:
    return tuple(soils.parse_table(source(name)) for name in ("mupolygon", "mapunit", "component", "chorizon"))


def test_sda_real_and_mock_build_same_table(config: Config) -> None:
    box_wkt = shapely_box(*config.bbox.as_tuple()).wkt
    real = _sda_tables(lambda name: _real(f"sda_{name}.json"))
    real_df, real_geo = soils.build_table(*real, box_wkt, is_synthetic=False)

    polygons = soils.run_query(config, soils.sql_polygons(box_wkt))
    mukeys = sorted({row[0] for row in polygons["Table"][1:]})
    components = soils.run_query(config, soils.sql_components(mukeys))
    cokeys = sorted({row[1] for row in components["Table"][1:]})
    mock = (soils.parse_table(polygons), soils.parse_table(soils.run_query(config, soils.sql_mapunits(mukeys))),
            soils.parse_table(components), soils.parse_table(soils.run_query(config, soils.sql_horizons(cokeys))))
    mock_df, mock_geo = soils.build_table(*mock, box_wkt, is_synthetic=True)

    for real_t, mock_t in zip(real, mock):
        assert list(real_t.columns) == list(mock_t.columns)
    assert list(real_df.columns) == list(mock_df.columns)
    assert real_df["awc_cm_cm"].notna().all() and mock_df["awc_cm_cm"].notna().all()
    assert real_geo["type"] == mock_geo["type"] == "FeatureCollection"


def test_sda_mock_rejects_declare_like_real(config: Config) -> None:
    response = requests.post(config.endpoint("sda") + soils.SDA_PATH,
                             json={"query": "DECLARE @x int; SELECT 1", "format": "JSON"}, timeout=30)
    assert response.text.lstrip().startswith("<")
    assert "declare" in response.text.lower()


def test_cmr_real_and_mock(config: Config) -> None:
    real = terrain.parse_cmr_granule_links(_real("cmr_srtmgl1_granules.json"))
    w, s, e, n = terrain.read_bounds(config)
    payload = requests.get(config.endpoint("cmr") + "/search/granules.json",
                           params={"short_name": "SRTMGL1", "bounding_box": f"{w},{s},{e},{n}"}, timeout=30).json()
    mock = terrain.parse_cmr_granule_links(payload)
    assert len(real) == len(mock) == 1
    assert real[0].rsplit("/", 1)[-1] == mock[0].rsplit("/", 1)[-1] == "N42W094.SRTMGL1.hgt.zip"


def test_tnm_real_and_mock(config: Config) -> None:
    real = terrain.parse_tnm_items(_real("tnm_products.json"))
    assert len(real) == 1 and real[0].endswith("_20221218.tif")  # latest of 3 historical tiles
    w, s, e, n = terrain.read_bounds(config)
    payload = requests.get(config.endpoint("tnm") + "/api/v1/products",
                           params={"datasets": terrain.TNM_DATASET, "bbox": f"{w},{s},{e},{n}"}, timeout=30).json()
    mock = terrain.parse_tnm_items(payload)
    assert len(mock) == 1 and "n43w094" in mock[0]


def test_nass_mock_uses_quickstats_fields(config: Config) -> None:
    """No real NASS fixture yet (needs an API key); check the documented field names instead."""
    params = nass.query_params(config, "corn", "yield", "169")
    rows = requests.get(config.endpoint("nass") + "/api/api_get/", params={"key": "x", **params}, timeout=30).json()["data"]
    documented = {"source_desc", "commodity_desc", "class_desc", "statisticcat_desc", "unit_desc", "short_desc",
                  "agg_level_desc", "state_fips_code", "county_code", "year", "freq_desc",
                  "reference_period_desc", "Value", "CV (%)"}
    assert documented <= set(rows[0])
    df = nass.clean_rows(rows, "corn", "yield", is_synthetic=True)
    assert (df["unit"] == "BU / ACRE").all()
    assert requests.get(config.endpoint("nass") + "/api/get_counts/", params=params, timeout=30).status_code == 401
