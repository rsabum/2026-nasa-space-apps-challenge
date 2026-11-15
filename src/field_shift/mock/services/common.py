"""Helpers shared by the mock service blueprints."""

from __future__ import annotations

from flask import current_app, request

from field_shift.mock.world import World


def world() -> World:
    return current_app.config["WORLD"]


def base_url() -> str:
    """Scheme + host of the running mock, for links inside responses."""
    return request.host_url.rstrip("/")
