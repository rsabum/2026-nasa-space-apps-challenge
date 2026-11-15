"""Validator for the three hand-filled reference tables."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

from field_shift.config import REPO_ROOT, Config, load_config
from field_shift.data import reference


@pytest.fixture
def ref_config(tmp_path: Path) -> Config:
    shutil.copytree(REPO_ROOT / "data/reference", tmp_path / "reference")
    return load_config(paths={"data_dir": str(tmp_path / "data"), "reference_dir": str(tmp_path / "reference")})


def _edit(config: Config, name: str, old: str, new: str) -> None:
    path = reference.table_path(config, name)
    path.write_text(path.read_text().replace(old, new, 1))


def test_templates_load_and_warn_about_blanks(ref_config: Config, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        crops = reference.load_crops(ref_config)
    assert list(crops["crop"]) == ["corn", "soybeans", "oats", "winter_wheat", "alfalfa", "cereal_rye"]
    assert bool(crops.set_index("crop").loc["cereal_rye", "is_cover_crop"])
    assert crops.set_index("crop").loc["corn", "cdl_code"] == 1
    assert "blank cells" in caplog.text
    assert len(reference.load_rotation_effects(ref_config)) == 3
    assert reference.load_site(ref_config).iloc[0]["site_id"] == "story_county_ia"
    counts = reference.blank_counts(ref_config)
    assert all(isinstance(v, int) and v > 0 for v in counts.values())


def test_filled_values_are_typed(ref_config: Config) -> None:
    _edit(ref_config, "crops", "corn,false,1,\"CORN, GRAIN\",,,,,,,,,",
          "corn,false,1,\"CORN, GRAIN\",Poaceae,no,500,High,120,low,04-15,05-31,")
    corn = reference.load_crops(ref_config).set_index("crop").loc["corn"]
    assert not bool(corn["is_legume"]) and corn["drought_sensitivity"] == "high"
    assert corn["season_length_days"] == 120 and corn["planting_window_end"] == "05-31"


@pytest.mark.parametrize(("old", "new", "message"), [
    ("corn,false,1,\"CORN, GRAIN\",,,,", "corn,false,1,\"CORN, GRAIN\",,,,extreme", "drought_sensitivity"),
    ("corn,false,1,\"CORN, GRAIN\",,,,,,,", "corn,false,1,\"CORN, GRAIN\",,,,,,,May 1", "planting_window_start"),
    ("corn,false,1,\"CORN, GRAIN\",,,", "corn,false,1,\"CORN, GRAIN\",,,-5", "water_use_mm_season"),
    ("corn,false,1,", "corn,maybe,1,", "is_cover_crop"),
])
def test_invalid_values_fail(ref_config: Config, old: str, new: str, message: str) -> None:
    _edit(ref_config, "crops", old, new)
    with pytest.raises(reference.ReferenceTableError, match=message):
        reference.load_crops(ref_config)


def test_wrong_columns_fail(ref_config: Config) -> None:
    _edit(ref_config, "site", "site_id,", "site,")
    with pytest.raises(reference.ReferenceTableError, match="columns must be exactly"):
        reference.load_site(ref_config)


def test_missing_crop_row_fails(ref_config: Config) -> None:
    path = reference.table_path(ref_config, "crops")
    path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("oats")) + "\n")
    with pytest.raises(reference.ReferenceTableError, match="oats"):
        reference.load_crops(ref_config)


def test_unknown_crop_in_rotation_effects_fails(ref_config: Config) -> None:
    _edit(ref_config, "rotation_effects", "corn,corn", "sorghum,corn")
    with pytest.raises(reference.ReferenceTableError, match="sorghum"):
        reference.load_rotation_effects(ref_config)
