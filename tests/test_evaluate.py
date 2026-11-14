from field_shift.evaluate import evaluate
from field_shift.models import Crop, Problem, Rotation, WeatherYear, Zone


def test_evaluate_tiny_problem() -> None:
    weather = WeatherYear(rain_mm=[2.0] * 365, et0_mm=[4.0] * 365, tmin_c=[8.0] * 365, tmax_c=[25.0] * 365)
    problem = Problem(
        zones={"zone1": Zone(area_ha=5.0, slope_pct=3.0, awc_mm=150.0, erodibility=0.2)},
        crops={
            "corn": Crop("grass", 120, 8.0, 1.1, 1.2, False, 1.2),
            "soybean": Crop("legume", 110, 10.0, 1.0, 0.9, True, 1.0),
            "wheat": Crop("grass", 100, 4.0, 0.9, 1.0, False, 0.8),
            "clover": Crop("legume", 90, 3.0, 0.8, 0.7, True, 0.5),
        },
        weather_years=[weather, weather, weather, weather],
        prices={"corn": 190.0, "soybean": 220.0, "wheat": 180.0, "clover": 120.0},
        weights={"profit": 1.0, "soil": 5.0, "erosion": 2.0},
        settings={"cover_crops": ["clover"], "water_budget_m3": 1e9, "violation_penalty": 100.0},
    )
    rotation = Rotation(assignments={"zone1": ["corn", "soybean", "wheat", "clover"]})

    report = evaluate(rotation, problem)

    assert isinstance(report.total_score, float)
    assert report.profit > 0
    assert report.weather_year_results
