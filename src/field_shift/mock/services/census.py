"""Mock Census geocoder: GET /geocoder/geographies/coordinates (county lookup only)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from field_shift.mock.services.common import world

bp = Blueprint("census", __name__)


@bp.get("/geocoder/geographies/coordinates")
def coordinates():
    w = world()
    site = w.params["world"]
    county = w.config.county_fips or site["county_fips"]
    return jsonify({"result": {
        "input": {"location": {"x": float(request.args.get("x", w.lon)), "y": float(request.args.get("y", w.lat))}},
        "geographies": {"Counties": [{
            "NAME": f"{site['county_name'].title()} County", "STATE": w.config.state_fips,
            "COUNTY": county, "GEOID": f"{w.config.state_fips}{county}",
        }]},
    }})
