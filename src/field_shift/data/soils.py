"""SSURGO soils through USDA Soil Data Access (SDA), no auth.

Service: https://sdmdataaccess.sc.egov.usda.gov (POST /tabular/post.rest, SQL).
SDA rejects `DECLARE`, so the box WKT is written inline into each query.
Used for: soil water (AWC), erosion risk (surface K factor), soil zones (polygons).

Processed:
    soils.parquet   one row per map unit in the box, with pct_of_box and
                    0-100 cm depth-weighted, component-weighted properties
    soils/mupolygons.geojson   map-unit polygons clipped to the box (WGS84)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely import wkt as shapely_wkt
from shapely.geometry import box as shapely_box
from shapely.geometry import mapping

from field_shift.config import Config
from field_shift.data import cache, checks, http

log = logging.getLogger(__name__)

DATASET = "soils"
SDA_PATH = "/tabular/post.rest"
DEPTH_CM = 100.0

COMPONENT_COLUMNS = ["mukey", "cokey", "compname", "comppct_r", "majcompflag", "drainagecl",
                     "hydgrp", "slope_l", "slope_r", "slope_h"]
HORIZON_COLUMNS = ["cokey", "chkey", "hzname", "hzdept_r", "hzdepb_r", "awc_r", "om_r",
                   "sandtotal_r", "silttotal_r", "claytotal_r", "kwfact"]
NUMERIC = {"comppct_r", "slope_l", "slope_r", "slope_h", "hzdept_r", "hzdepb_r", "awc_r",
           "om_r", "sandtotal_r", "silttotal_r", "claytotal_r", "kwfact"}
# horizon column -> output column (depth-weighted over 0-100 cm)
WEIGHTED = {"awc_r": "awc_cm_cm", "om_r": "om_pct", "sandtotal_r": "sand_pct",
            "silttotal_r": "silt_pct", "claytotal_r": "clay_pct"}


def processed_path(config: Config) -> Path:
    return config.processed_path(DATASET)


def geojson_path(config: Config) -> Path:
    path = config.processed_dir() / DATASET
    path.mkdir(parents=True, exist_ok=True)
    return path / "mupolygons.geojson"


# --- SQL ------------------------------------------------------------------------


def _in_list(keys: list[str]) -> str:
    return ",".join(f"'{int(k)}'" for k in keys)  # int() guards against injection


def sql_polygons(box_wkt: str) -> str:
    geom = f"geometry::STGeomFromText('{box_wkt}', 4326)"
    return (f"SELECT mukey, mupolygongeo.STIntersection({geom}).STAsText() AS wkt "
            f"FROM mupolygon WHERE mupolygongeo.STIntersects({geom}) = 1")


def sql_mapunits(mukeys: list[str]) -> str:
    return f"SELECT mukey, musym, muname FROM mapunit WHERE mukey IN ({_in_list(mukeys)})"


def sql_components(mukeys: list[str]) -> str:
    return f"SELECT {', '.join(COMPONENT_COLUMNS)} FROM component WHERE mukey IN ({_in_list(mukeys)})"


def sql_horizons(cokeys: list[str]) -> str:
    return f"SELECT {', '.join(HORIZON_COLUMNS)} FROM chorizon WHERE cokey IN ({_in_list(cokeys)})"


def run_query(config: Config, sql: str) -> dict[str, Any]:
    url = config.endpoint("sda") + SDA_PATH
    response = http.post(config, url, json={"query": sql, "format": "JSON+COLUMNNAME"})
    http.polite_sleep(config)
    text = response.text.strip()
    if text.startswith("<"):  # SDA reports SQL errors as XML with HTTP 200 or 500
        raise ValueError(f"SDA error: {text[:300]}")
    return json.loads(text) if text else {}


def parse_table(payload: dict[str, Any]) -> pd.DataFrame:
    """SDA `JSON+COLUMNNAME`: {"Table": [[col, ...], [val, ...], ...]}; `{}` means no rows."""
    table = payload.get("Table") or []
    if not table:
        return pd.DataFrame()
    df = pd.DataFrame(table[1:], columns=table[0])
    for column in df.columns:
        if column in NUMERIC:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


# --- geometry -----------------------------------------------------------------------


def polygon_areas(polygons: pd.DataFrame, box_wkt: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Per-mukey area share of the box (computed in EPSG:5070) and a GeoJSON dict."""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)

    def albers_area(geom) -> float:
        return shapely.transform(geom, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))).area

    box_geom = shapely_wkt.loads(box_wkt)
    box_area = albers_area(box_geom)
    merged: dict[str, Any] = {}
    for mukey, group in polygons.groupby("mukey"):
        geoms = [shapely_wkt.loads(w) for w in group["wkt"] if isinstance(w, str) and w]
        geom = shapely.union_all([g for g in geoms if not g.is_empty]).intersection(box_geom)
        merged[str(mukey)] = geom
    rows = [{"mukey": k, "pct_of_box": albers_area(g) / box_area * 100.0}
            for k, g in merged.items()]
    features = [{"type": "Feature", "geometry": mapping(g), "properties": {"mukey": k}}
                for k, g in merged.items() if not g.is_empty]
    return pd.DataFrame(rows), {"type": "FeatureCollection", "features": features}


# --- aggregation ------------------------------------------------------------------------


def aggregate_horizons(horizons: pd.DataFrame, depth_cm: float = DEPTH_CM) -> pd.DataFrame:
    """Depth-weight horizon properties over 0-`depth_cm` per component.

    Also returns `aws_0_100_mm` (sum of AWC x thickness) and the surface-horizon
    K factor `kwfact_surface` (RUSLE uses the surface layer's erodibility).
    """
    hz = horizons.copy()
    hz["thick_cm"] = (hz["hzdepb_r"].clip(upper=depth_cm) - hz["hzdept_r"].clip(lower=0)).clip(lower=0)
    rows = []
    for cokey, group in hz.groupby("cokey"):
        row: dict[str, Any] = {"cokey": cokey}
        for source, target in WEIGHTED.items():
            valid = group[group[source].notna() & (group["thick_cm"] > 0)]
            weight = valid["thick_cm"].sum()
            row[target] = float((valid[source] * valid["thick_cm"]).sum() / weight) if weight > 0 else np.nan
        awc = group[group["awc_r"].notna()]
        row["aws_0_100_mm"] = float((awc["awc_r"] * awc["thick_cm"]).sum() * 10.0) if not awc.empty else np.nan
        surface = group.sort_values("hzdept_r").iloc[0]
        row["kwfact_surface"] = float(surface["kwfact"]) if pd.notna(surface["kwfact"]) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_mapunits(components: pd.DataFrame, horizon_props: pd.DataFrame) -> pd.DataFrame:
    """Component-percent-weighted properties per map unit; categorical fields
    (drainage class, hydrologic group, slope range) from the dominant component."""
    comp = components.merge(horizon_props, on="cokey", how="left")
    numeric = list(WEIGHTED.values()) + ["aws_0_100_mm", "kwfact_surface"]
    rows = []
    for mukey, group in comp.groupby("mukey"):
        row: dict[str, Any] = {"mukey": str(mukey)}
        for column in numeric:
            valid = group[group[column].notna() & group["comppct_r"].notna()]
            weight = valid["comppct_r"].sum()
            row[column] = float((valid[column] * valid["comppct_r"]).sum() / weight) if weight > 0 else np.nan
        dominant = group.sort_values("comppct_r", ascending=False).iloc[0]
        row.update({
            "compname": dominant["compname"], "comppct_dominant": dominant["comppct_r"],
            "drainagecl": dominant["drainagecl"], "hydgrp": dominant["hydgrp"],
            "slope_l_pct": dominant["slope_l"], "slope_r_pct": dominant["slope_r"],
            "slope_h_pct": dominant["slope_h"],
        })
        rows.append(row)
    return pd.DataFrame(rows)


def build_table(polygons: pd.DataFrame, mapunits: pd.DataFrame, components: pd.DataFrame,
                horizons: pd.DataFrame, box_wkt: str, is_synthetic: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Combine the four SDA tables into the processed map-unit table + GeoJSON."""
    areas, geojson = polygon_areas(polygons, box_wkt)
    props = aggregate_mapunits(components, aggregate_horizons(horizons))
    mapunits = mapunits.assign(mukey=mapunits["mukey"].astype(str))
    df = areas.merge(mapunits, on="mukey", how="left").merge(props, on="mukey", how="left")
    df = df.sort_values("pct_of_box", ascending=False).reset_index(drop=True)
    df["is_synthetic"] = is_synthetic
    names = df.set_index("mukey")["muname"].to_dict()
    for feature in geojson["features"]:
        mukey = feature["properties"]["mukey"]
        feature["properties"]["muname"] = names.get(mukey)
        feature["properties"]["pct_of_box"] = float(df.loc[df["mukey"] == mukey, "pct_of_box"].iloc[0])
    return df, geojson


# --- fetch / load ---------------------------------------------------------------------


def _cached_query(config: Config, name: str, sql: str, force: bool) -> pd.DataFrame:
    raw = config.raw_dir(DATASET) / f"{name}.json"
    if raw.exists() and not force:
        payload = json.loads(raw.read_text(encoding="utf-8"))
    else:
        payload = run_query(config, sql)
        raw.write_text(json.dumps(payload), encoding="utf-8")
    return parse_table(payload)


def fetch(config: Config, force: bool = False) -> cache.FetchResult:
    out_path, geo_path = processed_path(config), geojson_path(config)
    if out_path.exists() and geo_path.exists() and not force:
        return cache.FetchResult(DATASET, "cached", str(out_path))
    box_wkt = shapely_box(*config.bbox.as_tuple()).wkt
    polygons = _cached_query(config, "mupolygon", sql_polygons(box_wkt), force)
    if polygons.empty:
        return cache.FetchResult(DATASET, "failed", "SDA returned no map units for the box")
    mukeys = sorted(polygons["mukey"].astype(str).unique())
    mapunits = _cached_query(config, "mapunit", sql_mapunits(mukeys), force)
    components = _cached_query(config, "component", sql_components(mukeys), force)
    cokeys = sorted(components["cokey"].astype(str).unique())
    horizons = _cached_query(config, "chorizon", sql_horizons(cokeys), force)
    df, geojson = build_table(polygons, mapunits, components, horizons, box_wkt, config.is_mock)
    cache.write_table(df, out_path)
    geo_path.write_text(json.dumps(geojson), encoding="utf-8")
    warnings = checks.check_soils(df)
    cache.update_manifest(config, DATASET, rows=len(df), files=[str(out_path), str(geo_path)],
                          warnings=len(warnings))
    top = df.iloc[0]
    return cache.FetchResult(DATASET, "fetched",
                             f"{len(df)} map units; dominant {top['compname']} ({top['pct_of_box']:.0f}% of box)")


def load(config: Config) -> pd.DataFrame:
    return cache.read_table(config, DATASET, processed_path(config))


def load_polygons(config: Config) -> dict[str, Any]:
    """Map-unit polygons (GeoJSON dict, WGS84) for building soil zones."""
    path = geojson_path(config)
    if not path.exists():
        raise cache.NotCachedError(DATASET, path)
    return json.loads(path.read_text(encoding="utf-8"))
