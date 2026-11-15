"""Synthetic SSURGO-like soils: map-unit polygons, components and horizons.

Seeded Voronoi cells tile a square around the site. Each cell gets a soil series
by its relative elevation on the synthetic terrain (low cells -> poorly drained
series), so soils and slope agree. One map unit per series, as in SSURGO where
many polygons share a mukey. All property values are PLACEHOLDERs (params YAML).
Synthetic mukeys start at 9_900_001 so they can never be mistaken for real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import shapely
from shapely.geometry import MultiPoint, Polygon, box

from field_shift.mock.generators.terrain import M_PER_DEG_LAT, M_PER_DEG_LON_EQ, Surface

HALF_SIZE_M = 3_000.0
MUKEY_START = 9_900_001


@dataclass
class SoilWorld:
    polygons: list[tuple[str, Polygon]] = field(default_factory=list)  # (mukey, WGS84 polygon)
    mapunits: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    horizons: list[dict[str, Any]] = field(default_factory=list)


def build_soils(params: dict[str, Any], surface: Surface, rng: np.random.Generator) -> SoilWorld:
    lon0, lat0 = surface.lon0, surface.lat0
    dlon = HALF_SIZE_M / (M_PER_DEG_LON_EQ * np.cos(np.radians(lat0)))
    dlat = HALF_SIZE_M / M_PER_DEG_LAT
    region = box(lon0 - dlon, lat0 - dlat, lon0 + dlon, lat0 + dlat)
    n = int(params["n_cells"])
    pts = np.column_stack([rng.uniform(lon0 - dlon, lon0 + dlon, n), rng.uniform(lat0 - dlat, lat0 + dlat, n)])
    cells = [c.intersection(region) for c in shapely.voronoi_polygons(MultiPoint(pts), extend_to=region).geoms]
    cells = [c for c in cells if not c.is_empty]

    centroids = np.array([[c.centroid.x, c.centroid.y] for c in cells])
    relief = surface.relative_elevation(centroids[:, 0], centroids[:, 1])
    order = list(params["by_relative_elevation"])
    ranks = np.argsort(np.argsort(relief))
    series_of_cell = [order[min(int(r * len(order) / len(cells)), len(order) - 1)] for r in ranks]

    world = SoilWorld()
    mukeys = {name: str(MUKEY_START + i) for i, name in enumerate(order)}
    for cell, name in zip(cells, series_of_cell):
        world.polygons.append((mukeys[name], cell))
    inclusion = float(params["inclusion_pct"])
    for i, name in enumerate(order):
        spec = params["series"][name]
        mukey = mukeys[name]
        world.mapunits.append({"mukey": mukey, "musym": spec["musym"], "muname": spec["muname"]})
        neighbour = order[i + 1] if i + 1 < len(order) else order[i - 1]
        for j, (comp, pct, major) in enumerate([(name, 100 - inclusion, "Yes"), (neighbour, inclusion, "No")]):
            cspec = params["series"][comp]
            cokey = f"{mukey}{j + 1:02d}"
            lo, rv, hi = cspec["slope"]
            world.components.append({
                "mukey": mukey, "cokey": cokey, "compname": comp.capitalize(), "comppct_r": pct,
                "majcompflag": major, "drainagecl": cspec["drainagecl"], "hydgrp": cspec["hydgrp"],
                "slope_l": lo, "slope_r": rv, "slope_h": hi,
            })
            for k, (hzname, top, bottom, awc, om, sand, silt, clay, kw) in enumerate(cspec["horizons"]):
                world.horizons.append({
                    "cokey": cokey, "chkey": f"{cokey}{k + 1:02d}", "hzname": hzname, "hzdept_r": top,
                    "hzdepb_r": bottom, "awc_r": awc, "om_r": om, "sandtotal_r": sand,
                    "silttotal_r": silt, "claytotal_r": clay, "kwfact": kw,
                })
    return world
