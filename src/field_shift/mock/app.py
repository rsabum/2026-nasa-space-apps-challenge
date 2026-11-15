"""The mock service app: one Flask app, one blueprint per real service.

Each service lives under `/<service>` with the rest of the path identical to
the real API, e.g. `/power/api/temporal/daily/point`. `Config.endpoint()` maps
a service name to this prefix when `endpoints.mode` is `mock`.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify

from field_shift.config import Config
from field_shift.data.http import redact
from field_shift.mock.services import cdl, census, elevation, nass, power, sda
from field_shift.mock.world import World

BLUEPRINTS = {
    "power": power.bp,
    "nass": nass.bp,
    "census": census.bp,
    "cdl_point": cdl.point_bp,
    "cdl_image": cdl.image_bp,
    "sda": sda.bp,
    "cmr": elevation.cmr_bp,
    "tnm": elevation.tnm_bp,
}


class _RedactFilter(logging.Filter):
    """Strip key=/token= values from request log lines (the NASS key is a query param)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in record.args)
        return True


def create_app(config: Config, world: World | None = None) -> Flask:
    app = Flask(__name__)
    app.config["WORLD"] = world or World(config)
    for prefix, blueprint in BLUEPRINTS.items():
        app.register_blueprint(blueprint, url_prefix=f"/{prefix}")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "mock": True, "services": sorted(BLUEPRINTS)})

    logging.getLogger("werkzeug").addFilter(_RedactFilter())
    return app
