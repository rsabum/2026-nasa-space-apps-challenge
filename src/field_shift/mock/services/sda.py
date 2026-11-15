"""Mock USDA Soil Data Access: POST /tabular/post.rest with {"query": SQL, "format": ...}.

The mock cannot run SQL. It understands exactly the query shapes real SDA users
send for this job:

    SELECT <cols> FROM mapunit|component|chorizon WHERE <key> IN ('..', ...)
    SELECT mukey, mupolygongeo.STIntersection(geometry::STGeomFromText('<WKT>', 4326)).STAsText() AS wkt
      FROM mupolygon WHERE mupolygongeo.STIntersects(geometry::STGeomFromText('<WKT>', 4326)) = 1

Anything else returns an SDA-style XML error. Replies use the real layouts:
`JSON+COLUMNNAME` -> {"Table": [[names], [values as strings], ...]}; no rows -> {}.
"""

from __future__ import annotations

import re
from typing import Any

from flask import Blueprint, Response, jsonify, request
from shapely import wkt as shapely_wkt

from field_shift.mock.services.common import world

bp = Blueprint("sda", __name__)

_SELECT = re.compile(r"^\s*SELECT\s+(?P<cols>.+?)\s+FROM\s+(?P<table>\w+)(?:\s+WHERE\s+(?P<where>.+))?\s*$",
                     re.IGNORECASE | re.DOTALL)
_GEOM = r"geometry::STGeomFromText\('(?P<wkt>[^']+)'\s*,\s*4326\)"
_CLIP = re.compile(r"^mupolygongeo\.STIntersection\(" + _GEOM + r"\)\.STAsText\(\)$", re.IGNORECASE)
_INTERSECTS = re.compile(r"^mupolygongeo\.STIntersects\(" + _GEOM + r"\)\s*=\s*1$", re.IGNORECASE)
_IN = re.compile(r"^(?P<key>\w+)\s+IN\s*\((?P<values>[^)]*)\)$", re.IGNORECASE)


def _error(message: str) -> Response:
    body = ('<?xml version=\'1.0\' encoding="UTF-8" standalone="no" ?>\n<ServiceExceptionReport '
            'xmlns="http://www.opengis.net/ogc"><ServiceException>\n'
            f"Invalid query: {message}</ServiceException></ServiceExceptionReport>")
    return Response(body, status=500, mimetype="text/xml")


def _split_columns(text: str) -> list[str]:
    """Split a SELECT list on top-level commas (ignoring commas inside () and quotes)."""
    parts, depth, quoted, current = [], 0, False, []
    for ch in text:
        if ch == "'":
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return parts


def _rows(table: str) -> list[dict[str, Any]]:
    soils = world().soils
    if table == "mupolygon":
        return [{"mukey": mukey, "_geom": geom} for mukey, geom in soils.polygons]
    return {"mapunit": soils.mapunits, "component": soils.components, "chorizon": soils.horizons}[table]


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@bp.post("/tabular/post.rest")
def post_rest():
    body = request.get_json(silent=True) or request.form.to_dict()
    sql, fmt = str(body.get("query", "")), str(body.get("format", "JSON")).upper()
    if re.search(r"\bDECLARE\b", sql, re.IGNORECASE):
        return _error('Keyword "declare" not allowed.')
    match = _SELECT.match(" ".join(sql.split()))
    if not match:
        return _error("the mock SDA only understands simple SELECT ... FROM ... WHERE ... queries")
    table = match["table"].lower()
    if table not in {"mupolygon", "mapunit", "component", "chorizon"}:
        return _error(f"table {table} is not available in the mock")
    rows = _rows(table)

    where = (match["where"] or "").strip()
    if (m := _INTERSECTS.match(where)) and table == "mupolygon":
        box = shapely_wkt.loads(m["wkt"])
        rows = [r for r in rows if r["_geom"].intersects(box)]
    elif m := _IN.match(where):
        wanted = {v.strip().strip("'") for v in m["values"].split(",")}
        rows = [r for r in rows if str(r.get(m["key"])) in wanted]
    elif where:
        return _error(f"unsupported WHERE clause: {where[:120]}")

    names, getters = [], []
    for expr in _split_columns(match["cols"]):
        alias = re.search(r"\s+AS\s+(\w+)$", expr, re.IGNORECASE)
        base = expr[: alias.start()].strip() if alias else expr
        name = alias.group(1) if alias else base.split(".")[-1]
        if (clip := _CLIP.match(base)) and table == "mupolygon":
            box = shapely_wkt.loads(clip["wkt"])
            getters.append(lambda r, box=box: r["_geom"].intersection(box).wkt)
        elif rows and base not in rows[0] or base.startswith("_"):
            return _error(f"Invalid column name '{base}'.")
        else:
            getters.append(lambda r, col=base: r.get(col))
        names.append(name)
    if not rows:
        return jsonify({})
    table_out = [[_cell(get(r)) for get in getters] for r in rows]
    if fmt == "JSON+COLUMNNAME":
        table_out.insert(0, names)
    return jsonify({"Table": table_out})
