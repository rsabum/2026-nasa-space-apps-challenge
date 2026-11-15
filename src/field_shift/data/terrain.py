"""Elevation and slope: NASA SRTM 1 arc-second, with USGS 3DEP as the backup.

- SRTM (SRTMGL1 v003, LP DAAC): granule search through NASA CMR
  (https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html), download of the
  1x1 degree `.hgt.zip` tiles with an Earthdata bearer token.
- 3DEP 1/3 arc-second (~10 m): product search through the USGS TNM Access API
  (https://tnmaccess.nationalmap.gov/api/v1/docs), then a windowed read of the
  cloud-optimised GeoTIFF, so only the box is downloaded.

Used for: slope and slope zones.
Processed: terrain/{dem,slope_pct,slope_zones}.tif (UTM, metres) and
terrain_summary.parquet (source, resolution, elevation and slope stats, zone shares).
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
import rasterio.errors
import rasterio.transform
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject

from field_shift.config import Config
from field_shift.data import cache, checks, credentials, http

log = logging.getLogger(__name__)

DATASET = "terrain"
MARGIN_DEG = 0.003  # read a little beyond the box so edge slopes are well defined
TNM_DATASET = "National Elevation Dataset (NED) 1/3 arc-second"
SOURCE_RESOLUTION_M = {"srtm": 30.0, "3dep": 10.0}
_TILE_RE = re.compile(r"[ns]\d{2}[ew]\d{3}", re.IGNORECASE)


def out_dir(config: Config) -> Path:
    path = config.processed_dir() / DATASET
    path.mkdir(parents=True, exist_ok=True)
    return path


def summary_path(config: Config) -> Path:
    return config.processed_path("terrain_summary")


def read_bounds(config: Config) -> tuple[float, float, float, float]:
    w, s, e, n = config.bbox.as_tuple()
    return (w - MARGIN_DEG, s - MARGIN_DEG, e + MARGIN_DEG, n + MARGIN_DEG)


def utm_crs(lon: float, lat: float) -> str:
    zone = int((lon + 180.0) // 6.0) + 1
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


# --- SRTM via CMR -------------------------------------------------------------------


def parse_cmr_granule_links(payload: dict) -> list[str]:
    """Data download URLs (`.hgt.zip`) from a CMR granules.json response."""
    urls = []
    for entry in payload.get("feed", {}).get("entry", []):
        for link in entry.get("links", []):
            href = link.get("href", "")
            if link.get("rel", "").endswith("/data#") and not link.get("inherited") and href.endswith(".zip"):
                urls.append(href)
                break
    return urls


def fetch_srtm(config: Config, force: bool) -> tuple[Path, str] | str:
    """Download SRTM tiles and merge them over the box. Returns (geotiff, source) or a reason string."""
    token = credentials.earthdata_token(config)
    if token is None:
        return "no Earthdata login (see README: ~/.netrc or earthaccess.login)"
    raw_dir = config.raw_dir(DATASET)
    w, s, e, n = read_bounds(config)
    params = {"short_name": "SRTMGL1", "version": "003", "bounding_box": f"{w},{s},{e},{n}", "page_size": "50"}
    payload = http.get(config, config.endpoint("cmr") + "/search/granules.json", params=params).json()
    urls = parse_cmr_granule_links(payload)
    if not urls:
        return "CMR returned no SRTMGL1 granules for the box"
    tiles = []
    for url in urls:
        dest = raw_dir / url.rsplit("/", 1)[-1]
        if not dest.exists() or force:
            http.download(config, url, dest, headers={"Authorization": f"Bearer {token}"})
            http.polite_sleep(config)
        if not zipfile.is_zipfile(dest):
            dest.unlink()
            return f"{dest.name} is not a zip (login rejected?)"
        with zipfile.ZipFile(dest) as zf:
            hgt = next(name for name in zf.namelist() if name.lower().endswith(".hgt"))
        tiles.append(f"/vsizip/{dest}/{hgt}")
    out = raw_dir / "dem_srtm_box.tif"
    merge_to_geotiff(tiles, read_bounds(config), out)
    return out, "srtm"


# --- 3DEP via TNM -------------------------------------------------------------------------


def parse_tnm_items(payload: dict) -> list[str]:
    """Latest download URL per 1x1 degree tile from a TNM products response."""
    best: dict[str, tuple[str, str]] = {}
    for item in payload.get("items", []):
        url = item.get("downloadURL", "")
        if not url.lower().endswith(".tif"):
            continue
        match = _TILE_RE.search(url)
        tile = match.group(0).lower() if match else url
        date = str(item.get("publicationDate", ""))
        if tile not in best or date > best[tile][0]:
            best[tile] = (date, url)
    return [url for _, url in best.values()]


def fetch_3dep(config: Config, force: bool) -> tuple[Path, str] | str:
    w, s, e, n = read_bounds(config)
    params = {"datasets": TNM_DATASET, "bbox": f"{w},{s},{e},{n}", "prodFormats": "GeoTIFF",
              "outputFormat": "JSON", "max": "20"}
    payload = http.get(config, config.endpoint("tnm") + "/api/v1/products", params=params).json()
    urls = parse_tnm_items(payload)
    if not urls:
        return "TNM returned no 3DEP 1/3 arc-second tiles for the box"
    out = config.raw_dir(DATASET) / "dem_3dep_box.tif"
    if out.exists() and not force:
        return out, "3dep"
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                      GDAL_HTTP_TIMEOUT=str(int(config.timeout_s))):
        merge_to_geotiff([f"/vsicurl/{u}" for u in urls], read_bounds(config), out)
    return out, "3dep"


# --- raster processing -------------------------------------------------------------------


def merge_to_geotiff(sources: list[str], bounds: tuple[float, float, float, float], out: Path) -> None:
    """Mosaic the source rasters over `bounds` (source CRS degrees) into a float32 GeoTIFF."""
    datasets = [rasterio.open(src) for src in sources]
    try:
        nodata = datasets[0].nodata
        array, transform = merge(datasets, bounds=bounds, nodata=nodata)
        profile = {
            "driver": "GTiff", "height": array.shape[1], "width": array.shape[2], "count": 1,
            "dtype": "float32", "crs": datasets[0].crs, "transform": transform, "nodata": np.nan,
        }
        data = array[0].astype("float32")
        if nodata is not None:
            data[data == nodata] = np.nan
    finally:
        for ds in datasets:
            ds.close()
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data, 1)


def reproject_to_utm(src_path: Path, crs: str, resolution_m: float) -> tuple[np.ndarray, rasterio.Affine]:
    """Bilinear reprojection to a metric CRS (needed before computing slope)."""
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, crs, src.width, src.height, *src.bounds, resolution=resolution_m)
        dem = np.full((height, width), np.nan, dtype="float32")
        reproject(source=rasterio.band(src, 1), destination=dem, src_transform=src.transform,
                  src_crs=src.crs, src_nodata=np.nan, dst_transform=transform, dst_crs=crs,
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
    return dem, transform


def slope_percent(dem: np.ndarray, resolution_m: float) -> np.ndarray:
    """Slope in percent: 100 * |grad z| with central differences."""
    dz_dy, dz_dx = np.gradient(dem.astype("float64"), resolution_m)
    return (100.0 * np.hypot(dz_dx, dz_dy)).astype("float32")


def slope_zones(slope: np.ndarray, breaks: list[float]) -> np.ndarray:
    """Zone 1..len(breaks)+1 by slope class; 0 where slope is NaN."""
    zones = (np.digitize(slope, breaks) + 1).astype("uint8")
    zones[~np.isfinite(slope)] = 0
    return zones


def box_mask(config: Config, transform: rasterio.Affine, shape: tuple[int, int], crs: str) -> np.ndarray:
    """True for pixels whose centre lies inside the config box."""
    to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    w, s, e, n = config.bbox.as_tuple()
    xs, ys = to_utm.transform([w, e, e, w], [s, s, n, n])
    rows, cols = np.indices(shape)
    x, y = rasterio.transform.xy(transform, rows.ravel(), cols.ravel())
    x, y = np.asarray(x).reshape(shape), np.asarray(y).reshape(shape)
    return (x >= min(xs)) & (x <= max(xs)) & (y >= min(ys)) & (y <= max(ys))


def write_raster(path: Path, data: np.ndarray, transform: rasterio.Affine, crs: str, nodata: float | int) -> None:
    profile = {"driver": "GTiff", "height": data.shape[0], "width": data.shape[1], "count": 1,
               "dtype": str(data.dtype), "crs": crs, "transform": transform, "nodata": nodata,
               "compress": "deflate"}
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def summarize(dem: np.ndarray, slope: np.ndarray, zones: np.ndarray, inside: np.ndarray,
              breaks: list[float], source: str, resolution_m: float, is_synthetic: bool) -> pd.DataFrame:
    valid = inside & np.isfinite(slope) & np.isfinite(dem)
    s, z = slope[valid], dem[valid]
    labels = _zone_labels(breaks)
    row = {
        "source": source, "resolution_m": resolution_m,
        "elev_mean_m": float(z.mean()), "elev_min_m": float(z.min()), "elev_max_m": float(z.max()),
        "slope_mean_pct": float(s.mean()), "slope_p90_pct": float(np.percentile(s, 90)),
        "slope_max_pct": float(s.max()), "pixels": int(valid.sum()), "is_synthetic": is_synthetic,
    }
    for zone, label in enumerate(labels, start=1):
        row[f"zone{zone}_{label}_frac"] = float((zones[valid] == zone).mean())
    return pd.DataFrame([row])


def _zone_labels(breaks: list[float]) -> list[str]:
    edges = [0, *breaks]
    labels = [f"{a:g}_{b:g}pct" for a, b in zip(edges[:-1], edges[1:])]
    return labels + [f"gt{breaks[-1]:g}pct"]


# --- fetch / load ------------------------------------------------------------------------------


def fetch(config: Config, force: bool = False) -> cache.FetchResult:
    summary_file = summary_path(config)
    if summary_file.exists() and not force:
        return cache.FetchResult(DATASET, "cached", str(summary_file))
    fetchers = {"srtm": fetch_srtm, "3dep": fetch_3dep}
    notes = []
    result: tuple[Path, str] | None = None
    for name in config.section("terrain")["sources"]:
        try:
            attempt = fetchers[name](config, force)
        except (http.HttpError, rasterio.errors.RasterioIOError, ValueError) as exc:
            attempt = f"failed: {exc}"
        if isinstance(attempt, tuple):
            result = attempt
            break
        notes.append(f"{name}: {attempt}")
        log.warning("terrain: %s not used (%s); trying the next source", name, attempt)
    if result is None:
        return cache.FetchResult(DATASET, "failed", "; ".join(notes))
    dem_geo, source = result
    crs, resolution = utm_crs(config.lon, config.lat), SOURCE_RESOLUTION_M[source]
    dem, transform = reproject_to_utm(dem_geo, crs, resolution)
    slope = slope_percent(dem, resolution)
    breaks = list(config.section("terrain")["slope_zone_breaks_pct"])
    zones = slope_zones(slope, breaks)
    folder = out_dir(config)
    write_raster(folder / "dem.tif", dem, transform, crs, np.nan)
    write_raster(folder / "slope_pct.tif", slope, transform, crs, np.nan)
    write_raster(folder / "slope_zones.tif", zones, transform, crs, 0)
    inside = box_mask(config, transform, dem.shape, crs)
    summary = summarize(dem, slope, zones, inside, breaks, source, resolution, config.is_mock)
    cache.write_table(summary, summary_file)
    warnings = checks.check_terrain(summary)
    cache.update_manifest(config, DATASET, rows=1, source_used=source, crs=crs, resolution_m=resolution,
                          skipped_sources=notes, warnings=len(warnings))
    row = summary.iloc[0]
    used = "SRTM (NASA)" if source == "srtm" else "USGS 3DEP (backup)"
    return cache.FetchResult(DATASET, "fetched", f"source {used}; slope mean {row['slope_mean_pct']:.1f}%, "
                                                 f"p90 {row['slope_p90_pct']:.1f}%, max {row['slope_max_pct']:.1f}%")


def load(config: Config) -> pd.DataFrame:
    """Summary stats (one row)."""
    return cache.read_table(config, DATASET, summary_path(config))


def raster_path(config: Config, name: str) -> Path:
    """Path of 'dem', 'slope_pct' or 'slope_zones' GeoTIFF (raises if missing)."""
    path = out_dir(config) / f"{name}.tif"
    if not path.exists():
        raise cache.NotCachedError(DATASET, path)
    return path
