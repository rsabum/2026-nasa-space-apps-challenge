"""Mock Cropland Data Layer services.

- cdl_point: CropScape GET /axis2/services/CDLService/GetCDLValue?year=&x=&y= (EPSG:5070), XML reply.
- cdl_image: USDA PDI ArcGIS ImageServer `CDL_WM`: GET .../ImageServer/query (raster catalog)
  and GET .../ImageServer/exportImage (GeoTIFF clip, EPSG:5070 only in the mock).
"""

from __future__ import annotations

import json

import numpy as np
from flask import Blueprint, Response, jsonify, request
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from field_shift.data.cdl_legend import crop_name
from field_shift.mock.generators.fields import pixel_size_m
from field_shift.mock.services.common import world

point_bp = Blueprint("cdl_point", __name__)
image_bp = Blueprint("cdl_image", __name__)

COLORS = {1: "#FFD400", 5: "#267300", 24: "#A57000", 27: "#AE017E", 28: "#A1A1A1", 36: "#FFA5E2",
          121: "#9C9C9C", 122: "#9C9C9C", 141: "#93CC93", 176: "#E8FFBF"}
# Raster ids as listed by the real PDI catalog on 2026-11-14 (year -> OBJECTID).
OBJECT_IDS = {1997: 25, 1998: 24, 1999: 23, 2000: 22, 2001: 21, 2002: 20, 2003: 19, 2004: 18, 2005: 16,
              2006: 15, 2007: 13, **{y: 2020 - y for y in range(2008, 2020)}, **{y: y - 1985 for y in range(2020, 2026)}}


def _available_years() -> list[int]:
    w = world()
    return [y for y in OBJECT_IDS if w.fields.start_year <= y <= w.years[1]]


@point_bp.get("/axis2/services/CDLService/GetCDLValue")
def get_cdl_value():
    try:
        year, x, y = int(request.args["year"]), float(request.args["x"]), float(request.args["y"])
    except (KeyError, ValueError):
        return Response("Error: year, x and y are required", status=500, mimetype="text/plain")
    if year not in _available_years():
        return Response(f"Error: CDL data for year {year} is not available", status=500, mimetype="text/plain")
    code = world().fields.site_code(x, y, year)
    body = (f'<ns1:GetCDLValueResponse xmlns:ns1="http://cropscape.csiss.gmu.edu/CDLService/"><Result>'
            f'{{x: {x}, y: {y}, value: {code}, category: "{crop_name(code)}", color: "{COLORS.get(code, "#000000")}"}}'
            f'</Result></ns1:GetCDLValueResponse>')
    return Response(body, mimetype="text/xml")


@image_bp.get("/image/rest/services/CDL_WM/ImageServer/query")
def query():
    features = []
    for year in _available_years():
        pixel = 56 if year == 2006 else pixel_size_m(year)
        features.append({"attributes": {"OBJECTID": OBJECT_IDS[year], "Name": f"{year}_{int(pixel)}m_cdls",
                                        "MinPS": 0, "MaxPS": 50200, "LowPS": pixel, "HighPS": 1920,
                                        "Category": 1, "Year": year}})
    return jsonify({"objectIdFieldName": "OBJECTID", "fields": [{"name": n} for n in
                    ("OBJECTID", "Name", "MinPS", "MaxPS", "LowPS", "HighPS", "Category", "Year")],
                    "features": features})


def _arcgis_error(message: str):
    return jsonify({"error": {"code": 400, "message": message, "details": []}}), 400


@image_bp.get("/image/rest/services/CDL_WM/ImageServer/exportImage")
def export_image():
    args = request.args
    try:
        xmin, ymin, xmax, ymax = (float(v) for v in args["bbox"].split(","))
        width, height = (int(v) for v in args.get("size", "400,400").split(","))
        rule = json.loads(args.get("mosaicRule", "{}"))
    except (KeyError, ValueError):
        return _arcgis_error("Unable to complete operation: bad bbox, size or mosaicRule")
    if args.get("imageSR", "5070") not in ("5070", "102039"):
        return _arcgis_error("the mock exportImage only supports imageSR=5070")
    if args.get("bboxSR", "5070") == "4326":
        to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
        xs, ys = to_albers.transform([xmin, xmax, xmax, xmin], [ymin, ymin, ymax, ymax])
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    by_id = {v: k for k, v in OBJECT_IDS.items()}
    ids = rule.get("lockRasterIds") or [OBJECT_IDS[max(_available_years())]]
    year = by_id.get(int(ids[0]))
    if year is None or year not in _available_years():
        return _arcgis_error(f"raster id {ids[0]} not found")
    if width * height > 15000 * 4100:
        return _arcgis_error("requested image exceeds the size limit")
    px, py = (xmax - xmin) / width, (ymax - ymin) / height
    cols, rows = np.meshgrid(np.arange(width), np.arange(height))
    codes = world().fields.classify(xmin + (cols + 0.5) * px, ymax - (rows + 0.5) * py, year)
    profile = {"driver": "GTiff", "height": height, "width": width, "count": 1, "dtype": "uint8",
               "crs": "EPSG:5070", "transform": from_bounds(xmin, ymin, xmax, ymax, width, height), "nodata": 0}
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dst:
            dst.write(codes.astype("uint8"), 1)
        data = memfile.read()
    return Response(data, mimetype="image/tiff")
