from field_shift.constraints import (
    acre_cap,
    equipment,
    erosion_cover_required,
    legume_required,
    no_same_family_consecutive,
    season_fits,
    water_budget,
)
from field_shift.models import Crop, Problem, Rotation, WeatherYear, Zone


def build_problem() -> Problem:
    weather = WeatherYear(rain_mm=[0.0] * 365, et0_mm=[5.0] * 365, tmin_c=[5.0] * 365, tmax_c=[20.0] * 365)
    return Problem(
        zones={
            "z1": Zone(area_ha=10.0, slope_pct=12.0, awc_mm=120.0, erodibility=0.5),
            "z2": Zone(area_ha=10.0, slope_pct=2.0, awc_mm=120.0, erodibility=0.1),
        },
        crops={
            "corn": Crop("grass", 110, 8.0, 1.1, 1.2, False, 1.0),
            "wheat": Crop("grass", 100, 6.0, 1.0, 1.0, False, 0.8),
            "soybean": Crop("legume", 95, 10.0, 0.9, 0.9, True, 0.9),
            "clover": Crop("legume", 70, 5.0, 0.7, 0.8, True, 0.5),
        },
        weather_years=[weather, weather, weather, weather],
        prices={"corn": 100.0, "wheat": 80.0, "soybean": 90.0, "clover": 30.0},
        weights={"profit": 1.0, "soil": 1.0, "erosion": 1.0},
        settings={
            "cover_crops": ["clover"],
            "slope_cover_threshold_pct": 8.0,
            "erodibility_cover_threshold": 0.3,
            "water_budget_m3": 1.0,
            "acre_caps_ha": {"corn": 15.0},
            "equipment_max_zones": {"corn": 1},
        },
    )


def test_season_fits_violation() -> None:
    p = build_problem()
    p = Problem(**{**p.__dict__, "crops": {**p.crops, "corn": Crop("grass", 400, 8.0, 1.1, 1.2, False, 1.0)}})
    v = season_fits(Rotation({"z1": ["corn", "soybean", "wheat", "clover"]}), p)
    assert v


def test_no_same_family_consecutive_violation() -> None:
    v = no_same_family_consecutive(Rotation({"z1": ["corn", "wheat", "soybean", "clover"]}), build_problem())
    assert v


def test_legume_required_violation() -> None:
    v = legume_required(Rotation({"z1": ["corn", "wheat", "corn", "wheat"]}), build_problem())
    assert v


def test_erosion_cover_required_violation() -> None:
    v = erosion_cover_required(Rotation({"z1": ["corn", "soybean", "corn", "soybean"]}), build_problem())
    assert v


def test_water_budget_violation() -> None:
    v = water_budget(Rotation({"z1": ["corn", "soybean", "wheat", "clover"]}), build_problem())
    assert v


def test_acre_cap_violation() -> None:
    v = acre_cap(Rotation({"z1": ["corn", "soybean", "wheat", "clover"], "z2": ["corn", "wheat", "soybean", "clover"]}), build_problem())
    assert v


def test_equipment_violation() -> None:
    v = equipment(Rotation({"z1": ["corn", "soybean", "wheat", "clover"], "z2": ["corn", "wheat", "soybean", "clover"]}), build_problem())
    assert v
