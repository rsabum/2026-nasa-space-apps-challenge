"""USDA Cropland Data Layer: the farm's current rotation (no auth).

- Site point: CropScape `GetCDLValue` (https://nassgeodata.gmu.edu/CropScape/devhelp/help.html),
  which needs coordinates in USA Contiguous Albers Equal Area (EPSG:5070).
- Box raster: USDA PDI ImageServer `CDL_WM` `exportImage`. CropScape's own clip
  service (`GetCDLFile`) returned 502 errors when checked on 2026-11-14.

Processed tables:
    cdl.parquet                year, cdl_code, crop_name, mvp_crop, is_synthetic   (site point)
    cdl_box_fractions.parquet  year, cdl_code, crop_name, mvp_crop, fraction, pixel_size_m, is_synthetic
Rasters: processed/cdl/box_<year>.tif (EPSG:5070, uint8 CDL codes, 0 = no data).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

from field_shift.config import Config
from field_shift.data import cache, checks, http
from field_shift.data.cdl_legend import crop_name, mvp_crop

log = logging.getLogger(__name__)

DATASET = "cdl"
ALBERS = "EPSG:5070"
POINT_PATH = "/axis2/services/CDLService/GetCDLValue"
IMAGE_SERVICE_PATH = "/image/rest/services/CDL_WM/ImageServer"
_RESULT_RE = re.compile(r"value:\s*(-?\d+)\s*,\s*category:\s*\"([^\"]*)\"")


def processed_path(config: Config) -> Path:
    return config.processed_path(DATASET)


def fractions_path(config: Config) -> Path:
    return config.processed_path("cdl_box_fractions")


def raster_dir(config: Config) -> Path:
    path = config.processed_dir() / DATASET
    path.mkdir(parents=True, exist_ok=True)
    return path


def years(config: Config) -> list[int]:
    return list(range(int(config.section("cdl")["start_year"]), config.end_year + 1))


def to_albers(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 lon/lat -> EPSG:5070 x/y in metres."""
    transformer = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    x, y = transformer.transform(lon, lat)
    return float(x), float(y)


def albers_bbox(config: Config, pixel_m: float) -> tuple[float, float, float, float]:
    """The config box in EPSG:5070, expanded to whole pixels on the CDL grid.

    The CDL grid origin is a multiple of 30 m (and 10 m), so snapping to
    multiples of the pixel size keeps pixels aligned with the source.
    """
    transformer = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    w, s, e, n = config.bbox.as_tuple()
    xs, ys = transformer.transform([w, e, e, w], [s, s, n, n])
    xmin = np.floor(min(xs) / pixel_m) * pixel_m
    ymin = np.floor(min(ys) / pixel_m) * pixel_m
    xmax = np.ceil(max(xs) / pixel_m) * pixel_m
    ymax = np.ceil(max(ys) / pixel_m) * pixel_m
    return float(xmin), float(ymin), float(xmax), float(ymax)


# --- site point ---------------------------------------------------------------


def parse_point_response(xml_text: str) -> tuple[int, str]:
    """Parse GetCDLValue XML: '{x: .., y: .., value: 1, category: "Corn", ...}'."""
    match = _RESULT_RE.search(xml_text)
    if not match:
        raise ValueError(f"unexpected GetCDLValue response: {xml_text[:200]!r}")
    return int(match.group(1)), match.group(2)


def fetch_point_year(config: Config, year: int, x: float, y: float, force: bool) -> tuple[int, str] | None:
    raw = config.raw_dir(DATASET) / f"point_{year}.xml"
    if not raw.exists() or force:
        url = config.endpoint("cdl_point") + POINT_PATH
        try:
            response = http.get(config, url, params={"year": year, "x": f"{x:.3f}", "y": f"{y:.3f}"})
        except http.HttpError as exc:
            log.warning("cdl: no point value for %d (%s)", year, exc)
            return None
        raw.write_text(response.text, encoding="utf-8")
        http.polite_sleep(config)
    try:
        return parse_point_response(raw.read_text(encoding="utf-8"))
    except ValueError as exc:
        log.warning("cdl: %d: %s", year, exc)
        return None


def build_point_table(results: dict[int, tuple[int, str]], is_synthetic: bool) -> pd.DataFrame:
    rows = []
    for year, (code, category) in sorted(results.items()):
        name = crop_name(code)
        if category and category != name:
            log.warning("cdl: legend says %r for code %d but the service says %r", name, code, category)
        rows.append({"year": year, "cdl_code": code, "crop_name": name, "mvp_crop": mvp_crop(code)})
    df = pd.DataFrame(rows, columns=["year", "cdl_code", "crop_name", "mvp_crop"])
    df["is_synthetic"] = is_synthetic
    return df


# --- box raster -------------------------------------------------------------------


def raster_catalog(config: Config) -> dict[int, dict[str, float]]:
    """Map year -> {'object_id', 'pixel_m'} from the ImageServer catalog.

    When a year has several rasters (e.g. 2007 at 30 m and 56 m) the finest wins.
    """
    url = config.endpoint("cdl_image") + IMAGE_SERVICE_PATH + "/query"
    params = {"where": "1=1", "outFields": "OBJECTID,Name,Year,LowPS", "returnGeometry": "false", "f": "pjson"}
    return parse_catalog(http.get(config, url, params=params).json())


def parse_catalog(payload: dict) -> dict[int, dict[str, float]]:
    catalog: dict[int, dict[str, float]] = {}
    for feature in payload.get("features", []):
        attrs = feature["attributes"]
        year, pixel = int(attrs["Year"]), float(attrs["LowPS"])
        if year not in catalog or pixel < catalog[year]["pixel_m"]:
            catalog[year] = {"object_id": int(attrs["OBJECTID"]), "pixel_m": pixel}
    return catalog


def fetch_box_year(config: Config, year: int, entry: dict[str, float], force: bool) -> Path | None:
    raw = config.raw_dir(DATASET) / f"box_{year}.tif"
    if raw.exists() and not force:
        return raw
    pixel = entry["pixel_m"]
    xmin, ymin, xmax, ymax = albers_bbox(config, pixel)
    width, height = int(round((xmax - xmin) / pixel)), int(round((ymax - ymin) / pixel))
    params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": "5070",
        "imageSR": "5070",
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "U8",
        "interpolation": "RSP_NearestNeighbor",
        "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [entry["object_id"]]}),
        "f": "image",
    }
    url = config.endpoint("cdl_image") + IMAGE_SERVICE_PATH + "/exportImage"
    try:
        response = http.get(config, url, params=params)
    except http.HttpError as exc:
        log.warning("cdl: no box raster for %d (%s)", year, exc)
        return None
    if response.content[:4] not in (b"II*\x00", b"MM\x00*"):
        log.warning("cdl: box %d: expected a GeoTIFF, got %r", year, response.content[:120])
        return None
    raw.write_bytes(response.content)
    http.polite_sleep(config)
    return raw


def box_fractions(tif: Path, year: int) -> pd.DataFrame:
    """Share of each CDL class among valid (non-zero) pixels of a box raster."""
    with rasterio.open(tif) as src:
        codes = src.read(1)
        pixel_m = abs(src.transform.a)
    valid = codes[codes > 0]
    values, counts = np.unique(valid, return_counts=True)
    return pd.DataFrame({
        "year": year,
        "cdl_code": values.astype(int),
        "crop_name": [crop_name(v) for v in values],
        "mvp_crop": [mvp_crop(v) for v in values],
        "fraction": counts / max(valid.size, 1),
        "pixel_size_m": pixel_m,
    })


# --- fetch / load -------------------------------------------------------------------


def fetch(config: Config, force: bool = False) -> cache.FetchResult:
    out_point, out_box = processed_path(config), fractions_path(config)
    if out_point.exists() and out_box.exists() and not force:
        return cache.FetchResult(DATASET, "cached", str(out_point))
    x, y = to_albers(config.lon, config.lat)
    points = {}
    for year in years(config):
        result = fetch_point_year(config, year, x, y, force)
        if result is not None:
            points[year] = result
    site = build_point_table(points, is_synthetic=config.is_mock)
    if site.empty:
        return cache.FetchResult(DATASET, "failed", "no CDL point values could be fetched")
    cache.write_table(site, out_point)

    fractions = []
    try:
        catalog = raster_catalog(config)
    except http.HttpError as exc:
        log.warning("cdl: raster catalog unavailable (%s); skipping box fractions", exc)
        catalog = {}
    for year in years(config):
        if year not in catalog:
            continue
        tif = fetch_box_year(config, year, catalog[year], force)
        if tif is not None:
            shutil.copyfile(tif, raster_dir(config) / tif.name)
            fractions.append(box_fractions(tif, year))
    box = pd.concat(fractions, ignore_index=True) if fractions else pd.DataFrame(
        columns=["year", "cdl_code", "crop_name", "mvp_crop", "fraction", "pixel_size_m"])
    box["is_synthetic"] = config.is_mock
    cache.write_table(box, out_box)

    warnings = checks.check_cdl(site)
    missing = sorted(set(years(config)) - set(site["year"]))
    if missing:
        warnings.append(f"missing site years: {missing}")
        log.warning("cdl check: missing site years %s", missing)
    cache.update_manifest(
        config, DATASET, rows=len(site), box_years=int(box["year"].nunique()) if not box.empty else 0,
        date_min=str(site["year"].min()), date_max=str(site["year"].max()), warnings=len(warnings),
    )
    rotation = "-".join((c or "other")[:4] for c in site["mvp_crop"].tail(6))
    return cache.FetchResult(DATASET, "fetched", f"{len(site)} site-years (recent: {rotation}); "
                                                 f"{box['year'].nunique() if not box.empty else 0} box rasters")


def load(config: Config) -> pd.DataFrame:
    """Site crop per year: the farmer's current-rotation baseline."""
    return cache.read_table(config, DATASET, processed_path(config))


def load_box_fractions(config: Config) -> pd.DataFrame:
    return cache.read_table(config, DATASET, fractions_path(config))
