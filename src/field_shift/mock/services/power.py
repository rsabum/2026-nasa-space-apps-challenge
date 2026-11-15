"""Mock NASA POWER daily point API: GET /api/temporal/daily/point.

Same query parameters and JSON layout as https://power.larc.nasa.gov (v2.x).
Only the configured site is served; `header.sources` says SYNTHETIC.
"""

from __future__ import annotations

import pandas as pd
from flask import Blueprint, jsonify, request

from field_shift.mock.services.common import world

bp = Blueprint("power", __name__)

PARAMETERS = {
    "T2M": ("tmean_c", "C", "Temperature at 2 Meters"),
    "T2M_MAX": ("tmax_c", "C", "Temperature at 2 Meters Maximum"),
    "T2M_MIN": ("tmin_c", "C", "Temperature at 2 Meters Minimum"),
    "PRECTOTCORR": ("precip_mm", "mm/day", "Precipitation Corrected"),
    "ALLSKY_SFC_SW_DWN": ("rs_mj_m2", "MJ/m^2/day", "All Sky Surface Shortwave Downward Irradiance"),
    "RH2M": ("rh2m_pct", "%", "Relative Humidity at 2 Meters"),
    "WS2M": ("wind2m_m_s", "m/s", "Wind Speed at 2 Meters"),
    "GWETTOP": ("gwettop_frac", "1", "Surface Soil Wetness"),
    "GWETROOT": ("gwetroot_frac", "1", "Root Zone Soil Wetness"),
}
FILL = -999.0
MAX_DISTANCE_DEG = 0.25


def _error(message: str, status: int = 422):
    return jsonify({"header": {"title": "NASA/POWER (SYNTHETIC MOCK)"}, "messages": [message]}), status


@bp.get("/api/temporal/daily/point")
def daily_point():
    w = world()
    args = request.args
    names = [p.strip().upper() for p in args.get("parameters", "").split(",") if p.strip()]
    unknown = [p for p in names if p not in PARAMETERS]
    if not names or unknown:
        return _error(f"mock POWER supports only {sorted(PARAMETERS)}; unknown: {unknown}")
    if args.get("community", "").upper() not in {"AG", "RE", "SB"}:
        return _error("community must be one of AG, RE, SB")
    if args.get("format", "JSON").upper() != "JSON":
        return _error("the mock only serves format=JSON")
    try:
        lat, lon = float(args["latitude"]), float(args["longitude"])
        start, end = pd.to_datetime(args["start"], format="%Y%m%d"), pd.to_datetime(args["end"], format="%Y%m%d")
    except (KeyError, ValueError):
        return _error("latitude, longitude, start (YYYYMMDD) and end (YYYYMMDD) are required")
    if abs(lat - w.lat) > MAX_DISTANCE_DEG or abs(lon - w.lon) > MAX_DISTANCE_DEG:
        return _error(f"the mock serves only the configured site ({w.lat}, {w.lon})")
    if start > end or start.year < w.years[0]:
        return _error(f"start must be <= end and on or after {w.years[0]}0101")

    daily = w.weather.set_index("date")
    dates = pd.date_range(start, end, freq="D")
    subset = daily.reindex(dates)
    keys = dates.strftime("%Y%m%d")
    parameter = {}
    for name in names:
        values = subset[PARAMETERS[name][0]].round(2).fillna(FILL)
        parameter[name] = dict(zip(keys, values.tolist()))
    return jsonify({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat, round(w.elevation_m, 2)]},
        "properties": {"parameter": parameter},
        "header": {
            "title": "NASA/POWER Source Native Resolution Daily Data (SYNTHETIC MOCK)",
            "api": {"version": "mock", "name": "POWER Daily API"},
            "sources": ["SYNTHETIC"],
            "fill_value": FILL,
            "time_standard": "LST",
            "start": keys[0],
            "end": keys[-1],
        },
        "messages": [],
        "parameters": {name: {"units": PARAMETERS[name][1], "longname": PARAMETERS[name][2]} for name in names},
        "times": {"data": 0.0, "process": 0.0},
    })
