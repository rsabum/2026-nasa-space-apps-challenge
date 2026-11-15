"""Mock NASS QuickStats API: GET /api/get_counts/ and /api/api_get/.

Records use the real QuickStats field names. A non-empty `key` is required
(any value). Filters: equality on any field, and `year__GE/__LE/__GT/__LT/__NE`.
Status codes follow the real service: 401 without a key, 400 for unknown
fields or empty results from api_get, 413 above 50,000 rows.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from field_shift.mock.services.common import world

bp = Blueprint("nass", __name__)

MAX_ROWS = 50_000
# crop -> yield series and state price series (commodity, class, utilization, unit)
SERIES = {
    "corn": {"yield": ("CORN", "ALL CLASSES", "GRAIN", "BU / ACRE"),
             "price": ("CORN", "ALL CLASSES", "GRAIN", "$ / BU")},
    "soybeans": {"yield": ("SOYBEANS", "ALL CLASSES", "ALL UTILIZATION PRACTICES", "BU / ACRE"),
                 "price": ("SOYBEANS", "ALL CLASSES", "ALL UTILIZATION PRACTICES", "$ / BU")},
    "oats": {"yield": ("OATS", "ALL CLASSES", "ALL UTILIZATION PRACTICES", "BU / ACRE"),
             "price": ("OATS", "ALL CLASSES", "ALL UTILIZATION PRACTICES", "$ / BU")},
    "winter_wheat": {"yield": ("WHEAT", "WINTER", "ALL UTILIZATION PRACTICES", "BU / ACRE"),
                     "price": ("WHEAT", "ALL CLASSES", "ALL UTILIZATION PRACTICES", "$ / BU")},
    "alfalfa": {"yield": ("HAY", "ALFALFA", "ALL UTILIZATION PRACTICES", "TONS / ACRE"),
                "price": ("HAY", "ALFALFA", "ALL UTILIZATION PRACTICES", "$ / TON")},
}


def short_desc(commodity: str, cls: str, util: str, stat: str, unit: str) -> str:
    """Compose a short_desc the way QuickStats does ('ALL ...' parts are omitted)."""
    parts = [commodity] + [p for p in (cls, util) if not p.startswith("ALL ")]
    return f"{', '.join(parts)} - {stat}, MEASURED IN {unit}"


def _value(value: float) -> str:
    return "                 (D)" if value != value else f"{value:,.1f}" if value >= 100 else f"{value:,.2f}"


def records() -> list[dict[str, Any]]:
    w = world()
    site = w.params["world"]
    cfg = w.config
    common = {
        "source_desc": "SURVEY", "sector_desc": "CROPS", "group_desc": "FIELD CROPS",
        "prodn_practice_desc": "ALL PRODUCTION PRACTICES", "domain_desc": "TOTAL",
        "domaincat_desc": "NOT SPECIFIED", "state_ansi": cfg.state_fips, "state_fips_code": cfg.state_fips,
        "state_alpha": cfg.state_alpha, "state_name": site["state_name"], "country_code": "9000",
        "country_name": "UNITED STATES", "freq_desc": "ANNUAL", "begin_code": "00", "end_code": "00",
        "week_ending": "", "zip_5": "", "watershed_code": "00000000", "watershed_desc": "",
        "congr_district_code": "", "region_desc": "", "load_time": "2026-01-01 00:00:00", "CV (%)": "",
    }
    out = []
    for row in w.county_yields.itertuples():
        commodity, cls, util, unit = SERIES[row.crop]["yield"]
        out.append({**common, "commodity_desc": commodity, "class_desc": cls, "util_practice_desc": util,
                    "statisticcat_desc": "YIELD", "unit_desc": unit,
                    "short_desc": short_desc(commodity, cls, util, "YIELD", unit),
                    "agg_level_desc": "COUNTY", "asd_code": site["asd_code"], "asd_desc": site["asd_desc"],
                    "county_ansi": cfg.county_fips or site["county_fips"], "county_code": cfg.county_fips or site["county_fips"],
                    "county_name": site["county_name"],
                    "location_desc": f"{site['state_name']}, {site['asd_desc']}, {site['county_name']}",
                    "year": int(row.year), "reference_period_desc": "YEAR", "Value": _value(row.value)})
    for row in w.state_prices.itertuples():
        commodity, cls, util, unit = SERIES[row.crop]["price"]
        out.append({**common, "commodity_desc": commodity, "class_desc": cls,
                    "util_practice_desc": util, "statisticcat_desc": "PRICE RECEIVED",
                    "unit_desc": unit, "short_desc": short_desc(commodity, cls, util, "PRICE RECEIVED", unit),
                    "agg_level_desc": "STATE", "asd_code": "", "asd_desc": "", "county_ansi": "",
                    "county_code": "", "county_name": "", "location_desc": site["state_name"],
                    "year": int(row.year), "reference_period_desc": "MARKETING YEAR", "Value": _value(row.value)})
    return out


def _filter(rows: list[dict[str, Any]]):
    args = {k: v for k, v in request.args.items() if k not in {"key", "format"}}
    fields = set(rows[0]) if rows else set()
    for name, wanted in args.items():
        field, _, op = name.partition("__")
        if field not in fields or op not in {"", "GE", "LE", "GT", "LT", "NE"}:
            return None
        if op:
            target = float(wanted)
            compare = {"GE": float.__ge__, "LE": float.__le__, "GT": float.__gt__,
                       "LT": float.__lt__, "NE": float.__ne__}[op]
            rows = [r for r in rows if compare(float(r[field]), target)]
        else:
            rows = [r for r in rows if str(r[field]).upper() == wanted.upper()]
    return rows


def _authorized() -> bool:
    return bool(request.args.get("key", "").strip())


@bp.get("/api/get_counts/")
def get_counts():
    if not _authorized():
        return jsonify({"error": ["unauthorized"]}), 401
    rows = _filter(records())
    if rows is None:
        return jsonify({"error": ["bad request - invalid query"]}), 400
    return jsonify({"count": len(rows)})


@bp.get("/api/api_get/")
def api_get():
    if not _authorized():
        return jsonify({"error": ["unauthorized"]}), 401
    rows = _filter(records())
    if not rows:
        return jsonify({"error": ["bad request - invalid query"]}), 400
    if len(rows) > MAX_ROWS:
        return jsonify({"error": [f"exceeds limit={MAX_ROWS}"]}), 413
    return jsonify({"data": rows})
