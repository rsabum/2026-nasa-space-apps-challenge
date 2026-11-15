"""Capture tiny REAL API responses into tests/fixtures/real/ for contract tests.

The contract tests run the same parsers on these real responses and on the
mock's responses, so the mock cannot silently drift from the real formats.
Uses the clients' own request builders, a handful of small requests, and only
public no-auth services (POWER is trimmed from a response you already have).

Usage:
    python scripts/capture_fixtures.py [--power-json path/to/power.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.geometry import box as shapely_box

from field_shift.config import load_config
from field_shift.data import cdl, http, soils, terrain

OUT = Path(__file__).resolve().parents[1] / "tests/fixtures/real"


def save(name: str, content: str | bytes) -> None:
    path = OUT / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    print(f"saved {path.relative_to(OUT.parents[2])} ({path.stat().st_size} bytes)")


def trim_power(path: Path, days: int = 5) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for name, values in payload["properties"]["parameter"].items():
        payload["properties"]["parameter"][name] = dict(list(values.items())[:days])
    save("power_daily_point.json", json.dumps(payload, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--power-json", type=Path)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config(endpoints={"mode": "real"})

    if args.power_json:
        trim_power(args.power_json)

    # CDL point (one year) and the PDI raster catalog.
    x, y = cdl.to_albers(config.lon, config.lat)
    url = config.endpoint("cdl_point") + cdl.POINT_PATH
    save("cdl_point_2025.xml", http.get(config, url, params={"year": 2025, "x": f"{x:.3f}", "y": f"{y:.3f}"}).text)
    url = config.endpoint("cdl_image") + cdl.IMAGE_SERVICE_PATH + "/query"
    params = {"where": "1=1", "outFields": "OBJECTID,Name,Year,LowPS", "returnGeometry": "false", "f": "pjson"}
    save("cdl_catalog.json", http.get(config, url, params=params).text)

    # SDA: first 3 polygons in the box, then their map units, components and horizons.
    box_wkt = shapely_box(*config.bbox.as_tuple()).wkt
    polygons = soils.run_query(config, soils.sql_polygons(box_wkt))
    polygons["Table"] = polygons["Table"][:4]
    save("sda_mupolygon.json", json.dumps(polygons))
    mukeys = sorted({row[0] for row in polygons["Table"][1:]})
    save("sda_mapunit.json", json.dumps(soils.run_query(config, soils.sql_mapunits(mukeys))))
    components = soils.run_query(config, soils.sql_components(mukeys))
    save("sda_component.json", json.dumps(components))
    cokeys = sorted({row[1] for row in components["Table"][1:]})
    save("sda_chorizon.json", json.dumps(soils.run_query(config, soils.sql_horizons(cokeys))))

    # Elevation search responses (metadata only, no downloads).
    w, s, e, n = terrain.read_bounds(config)
    params = {"short_name": "SRTMGL1", "version": "003", "bounding_box": f"{w},{s},{e},{n}", "page_size": "50"}
    save("cmr_srtmgl1_granules.json", http.get(config, config.endpoint("cmr") + "/search/granules.json", params=params).text)
    params = {"datasets": terrain.TNM_DATASET, "bbox": f"{w},{s},{e},{n}", "prodFormats": "GeoTIFF",
              "outputFormat": "JSON", "max": "20"}
    save("tnm_products.json", http.get(config, config.endpoint("tnm") + "/api/v1/products", params=params).text)


if __name__ == "__main__":
    main()
