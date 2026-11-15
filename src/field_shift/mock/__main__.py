"""`python -m field_shift.mock serve [--host 127.0.0.1] [--port 8765]`

Starts the local mock services that imitate POWER, NASS QuickStats, CropScape/CDL,
Soil Data Access, CMR (SRTM) and TNM (3DEP), serving SYNTHETIC data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from urllib.parse import urlparse

from field_shift.config import load_config
from field_shift.mock.app import create_app
from field_shift.mock.world import World


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m field_shift.mock", description=__doc__)
    parser.add_argument("--config", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the mock services")
    serve.add_argument("--host", default=None, help="default: host of endpoints.mock_base_url")
    serve.add_argument("--port", type=int, default=None, help="default: port of endpoints.mock_base_url")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    config = load_config(args.config)
    url = urlparse(config.mock_base_url)
    host, port = args.host or url.hostname or "127.0.0.1", args.port or url.port or 8765
    world = World(config)
    logging.info("building the synthetic world (seed %d); first run takes a few seconds", world.seed)
    _ = world.weather, world.fields, world.soils
    world.srtm_zip()
    world.tnm_tile()
    logging.info("mock services ready at http://%s:%d  (SYNTHETIC data; Ctrl+C to stop)", host, port)
    create_app(config, world).run(host=host, port=port, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
