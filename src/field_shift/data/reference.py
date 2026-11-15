"""The three hand-filled reference tables in `data/reference/` (no network).

- crops.csv            one row per MVP crop (5 cash crops + cereal rye)
- rotation_effects.csv previous crop -> next crop yield change and N credit
- site.csv             rainfall erosivity and cereal-rye planting dates per site

Each loader validates the schema (columns, types, allowed values, MM-DD dates)
and raises `ReferenceTableError` on invalid content. Blank cells are allowed
while the tables are being filled in: each one is reported as a warning.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from field_shift.config import Config

log = logging.getLogger(__name__)

LEVELS = ("low", "medium", "high")
_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_TRUE, _FALSE = {"true", "yes", "1", "y"}, {"false", "no", "0", "n"}


@dataclass(frozen=True)
class Column:
    name: str
    kind: str  # "str" | "bool" | "int" | "float" | "level" | "mmdd"
    unit: str = ""
    lo: float | None = None  # loose sanity bounds to catch typos, not agronomic values
    hi: float | None = None
    required: bool = False  # must never be blank (row keys)
    description: str = ""


CROPS = [
    Column("crop", "str", required=True, description="MVP crop key"),
    Column("is_cover_crop", "bool", required=True),
    Column("cdl_code", "int", description="CDL class code (official legend)"),
    Column("nass_commodity", "str", description="QuickStats commodity/class"),
    Column("family", "str", description="botanical family, e.g. Poaceae"),
    Column("is_legume", "bool"),
    Column("water_use_mm_season", "float", "mm", 0, 2000, description="seasonal crop water use"),
    Column("drought_sensitivity", "level"),
    Column("season_length_days", "int", "days", 1, 400),
    Column("frost_tolerance", "level"),
    Column("planting_window_start", "mmdd"),
    Column("planting_window_end", "mmdd", description="USDA RMA final planting date"),
    Column("cost_per_acre_usd", "float", "USD/acre", 0, 5000),
    Column("cost_source", "str", description="Iowa State Ag Decision Maker; USDA ERS for oats and wheat"),
    Column("erosion_protection", "level"),
    Column("soil_health_points", "float", "points", -100, 100, description="input to our own soil heuristic"),
    Column("source", "str"),
    Column("notes", "str"),
]
ROTATION_EFFECTS = [
    Column("prev_crop", "str", required=True),
    Column("next_crop", "str", required=True),
    Column("yield_change_pct", "float", "%", -100, 100),
    Column("n_credit_lb_per_acre", "float", "lb N/acre", 0, 500),
    Column("source", "str"),
    Column("notes", "str"),
]
SITE = [
    Column("site_id", "str", required=True),
    Column("rainfall_erosivity_r", "float", "MJ mm / (ha h yr) or US units; say which in notes", 0, 20000),
    Column("rye_plant_earliest", "mmdd", description="Midwest Cover Crops Council decision tool"),
    Column("rye_plant_latest", "mmdd", description="Midwest Cover Crops Council decision tool"),
    Column("source", "str"),
    Column("notes", "str"),
]
TABLES: dict[str, list[Column]] = {"crops": CROPS, "rotation_effects": ROTATION_EFFECTS, "site": SITE}


class ReferenceTableError(ValueError):
    """A reference table has invalid (not merely blank) content."""


def table_path(config: Config, name: str) -> Path:
    return config.reference_dir / f"{name}.csv"


def _parse_cell(column: Column, text: str) -> object:
    if column.kind == "str":
        return text
    if column.kind == "bool":
        low = text.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError(f"expected true/false, got {text!r}")
    if column.kind in ("int", "float"):
        value = float(text)
        if column.kind == "int" and value != int(value):
            raise ValueError(f"expected a whole number, got {text!r}")
        if (column.lo is not None and value < column.lo) or (column.hi is not None and value > column.hi):
            raise ValueError(f"{value} is outside the sanity range [{column.lo}, {column.hi}] {column.unit}")
        return int(value) if column.kind == "int" else value
    if column.kind == "level":
        if text.lower() not in LEVELS:
            raise ValueError(f"expected one of {LEVELS}, got {text!r}")
        return text.lower()
    if column.kind == "mmdd":
        if not _MMDD.match(text):
            raise ValueError(f"expected an MM-DD date, got {text!r}")
        return text
    raise AssertionError(column.kind)


def validate(name: str, raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Validate a raw (all-string) table. Returns (typed table, blank-cell warnings)."""
    schema = TABLES[name]
    expected = [c.name for c in schema]
    if list(raw.columns) != expected:
        raise ReferenceTableError(f"{name}.csv columns must be exactly {expected}, got {list(raw.columns)}")
    errors, blanks = [], []
    typed: dict[str, list[object]] = {c.name: [] for c in schema}
    for i, row in raw.iterrows():
        key = row[expected[0]] or f"row {i + 2}"
        for column in schema:
            text = str(row[column.name]).strip()
            if text == "":
                if column.required:
                    errors.append(f"{name}.csv line {i + 2}: {column.name} must not be blank")
                elif column.name != "notes":
                    blanks.append(f"{name}.csv: {key}: {column.name} is blank")
                typed[column.name].append(None)
                continue
            try:
                typed[column.name].append(_parse_cell(column, text))
            except ValueError as exc:
                errors.append(f"{name}.csv line {i + 2} ({key}) {column.name}: {exc}")
                typed[column.name].append(None)
    if errors:
        raise ReferenceTableError("; ".join(errors))
    return pd.DataFrame(typed), blanks


def load_table(config: Config, name: str, warn: bool = True) -> pd.DataFrame:
    path = table_path(config, name)
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; it is a committed template, restore it from git")
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    df, blanks = validate(name, raw)
    if warn and blanks:
        log.warning("%s.csv has %d blank cells still to fill in (first: %s)", name, len(blanks), blanks[0])
    return df


def load_crops(config: Config) -> pd.DataFrame:
    df = load_table(config, "crops")
    missing = set(config.all_crops) - set(df["crop"])
    if missing:
        raise ReferenceTableError(f"crops.csv is missing rows for {sorted(missing)}")
    return df


def load_rotation_effects(config: Config) -> pd.DataFrame:
    df = load_table(config, "rotation_effects")
    unknown = (set(df["prev_crop"]) | set(df["next_crop"])) - set(config.all_crops)
    if unknown:
        raise ReferenceTableError(f"rotation_effects.csv mentions unknown crops {sorted(unknown)}")
    return df


def load_site(config: Config) -> pd.DataFrame:
    return load_table(config, "site")


def blank_counts(config: Config) -> dict[str, int | str]:
    """Blank (still to fill) cells per table, for `status`. Invalid tables report 'INVALID'."""
    out: dict[str, int | str] = {}
    for name in TABLES:
        try:
            raw = pd.read_csv(table_path(config, name), dtype=str, keep_default_na=False)
            out[name] = len(validate(name, raw)[1])
        except FileNotFoundError:
            out[name] = "MISSING"
        except ReferenceTableError:
            out[name] = "INVALID"
    return out
