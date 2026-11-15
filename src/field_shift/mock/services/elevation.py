"""Mock elevation services.

- cmr: NASA CMR GET /search/granules.json (SRTMGL1 only) and the granule download
  GET /data/SRTMGL1.003/<name>, which requires `Authorization: Bearer <token>` like
  Earthdata Cloud does. Only the 1x1 degree tile containing the site exists.
- tnm: USGS TNM Access GET /api/v1/products and GET /files/<name> (a tiled GeoTIFF
  served with HTTP Range support so clients can do windowed reads). The mock tile
  covers only a small area around the site, not a full 1x1 degree tile.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, request, send_file

from field_shift.mock.services.common import base_url, world

cmr_bp = Blueprint("cmr", __name__)
tnm_bp = Blueprint("tnm", __name__)

TNM_DATASET = "National Elevation Dataset (NED) 1/3 arc-second"


def _bbox_contains_site(text: str) -> bool:
    try:
        w, s, e, n = (float(v) for v in text.split(","))
    except ValueError:
        return False
    site = world()
    return w <= site.lon <= e and s <= site.lat <= n


@cmr_bp.get("/search/granules.json")
def granules():
    args = request.args
    entries = []
    if args.get("short_name", "").upper() == "SRTMGL1" and _bbox_contains_site(args.get("bounding_box", "")):
        name = f"{world().srtm_tile_name()}.SRTMGL1.hgt.zip"
        entries.append({
            "id": "G-MOCK-SRTMGL1", "title": f"SRTMGL1.003:{name} (SYNTHETIC MOCK)",
            "time_start": "2000-02-11T00:00:00.000Z", "time_end": "2000-02-21T23:59:59.000Z",
            "links": [
                {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "type": "application/zip",
                 "href": f"{base_url()}/cmr/data/SRTMGL1.003/{name}"},
                {"rel": "http://esipfed.org/ns/fedsearch/1.1/metadata#", "inherited": True,
                 "href": "https://lpdaac.usgs.gov/"},
            ],
        })
    return jsonify({"feed": {"updated": "2026-01-01T00:00:00Z", "title": "ECHO granule metadata", "entry": entries}})


@cmr_bp.get("/data/SRTMGL1.003/<name>")
def srtm_download(name: str):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return "<html><body>Earthdata Login required</body></html>", 401
    if name != f"{world().srtm_tile_name()}.SRTMGL1.hgt.zip":
        abort(404)
    return send_file(world().srtm_zip(), mimetype="application/zip", download_name=name)


@tnm_bp.get("/api/v1/products")
def products():
    args = request.args
    items = []
    if args.get("datasets") == TNM_DATASET and _bbox_contains_site(args.get("bbox", "")):
        name = world().tnm_tile_name()
        path = world().tnm_tile()
        items.append({
            "title": f"USGS 1/3 Arc Second {name[8:15]} 20240229 (SYNTHETIC MOCK)",
            "downloadURL": f"{base_url()}/tnm/files/{name}", "format": "GeoTIFF",
            "publicationDate": "2024-02-29", "sizeInBytes": path.stat().st_size,
        })
    return jsonify({"total": len(items), "items": items, "errors": [], "messages": []})


@tnm_bp.route("/files/<name>", methods=["GET", "HEAD"])
def tnm_file(name: str):
    if name != world().tnm_tile_name():
        abort(404)
    return send_file(world().tnm_tile(), mimetype="image/tiff", conditional=True)
