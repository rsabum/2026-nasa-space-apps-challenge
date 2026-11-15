"""Live smoke tests against the REAL APIs. Deselected by default; run with:

    pytest -m network
"""

from __future__ import annotations

import pytest

from field_shift.config import REPO_ROOT, load_config
from field_shift.data import cdl, http, power, soils

pytestmark = pytest.mark.network


@pytest.fixture
def real_config(tmp_path):
    return load_config(paths={"data_dir": str(tmp_path), "reference_dir": str(REPO_ROOT / "data/reference")},
                       endpoints={"mode": "real"})


def test_power_live(real_config) -> None:
    params = power.request_params(real_config, "20240101", "20240103")
    df, elevation = power.parse_response(http.get(real_config, real_config.endpoint("power") + power.API_PATH,
                                                  params=params).json())
    assert len(df) == 3 and elevation > 0 and not df["is_synthetic"].any()


def test_cdl_catalog_live(real_config) -> None:
    assert 2025 in cdl.raster_catalog(real_config)


def test_cdl_box_live(real_config) -> None:
    catalog = cdl.raster_catalog(real_config)
    tif = cdl.fetch_box_year(real_config, 2025, catalog[2025], force=True)
    assert tif is not None
    fractions = cdl.box_fractions(tif, 2025)
    assert fractions["fraction"].sum() == pytest.approx(1.0)
    # The default site box overlaps the town of Nevada, IA, so only check that crops are present.
    assert {1, 5} <= set(fractions["cdl_code"])


def test_sda_live(real_config) -> None:
    payload = soils.run_query(real_config, soils.sql_mapunits(["2800480"]))
    assert soils.parse_table(payload).iloc[0]["mukey"] == "2800480"
