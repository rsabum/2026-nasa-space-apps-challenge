"""Field Shift data layer.

Each dataset module exposes `fetch(config, force=False)` and `load(config)`.
Later code should only ever call `load()`: it reads the local cache and never
touches the network.

    from field_shift.config import load_config
    from field_shift.data import power
    weather = power.load(load_config())
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from field_shift.config import Config
from field_shift.data import cdl, credentials, nass, power, soils, terrain


@dataclass(frozen=True)
class DatasetInfo:
    module: ModuleType
    primary_output: Callable[[Config], Path]
    credential: str | None = None  # human-readable credential name, if any
    has_credential: Callable[[Config], bool] = lambda config: True


# Fetch order for `fetch --all`.
DATASETS: dict[str, DatasetInfo] = {
    "power": DatasetInfo(power, power.processed_path),
    "nass": DatasetInfo(nass, nass.processed_path, "NASS_API_KEY",
                        lambda config: credentials.nass_api_key() is not None),
    "cdl": DatasetInfo(cdl, cdl.processed_path),
    "soils": DatasetInfo(soils, soils.processed_path),
    "terrain": DatasetInfo(terrain, terrain.summary_path, "Earthdata login (SRTM; 3DEP backup without it)",
                           credentials.earthdata_available),
}

__all__ = ["DATASETS", "DatasetInfo", "cdl", "nass", "power", "soils", "terrain"]
