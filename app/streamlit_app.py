"""Streamlit interface for Field Shift."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from field_shift.evaluate import evaluate
from field_shift.models import Crop, Problem, Rotation, WeatherYear, Zone
from field_shift.optimize import optimize


def _stub_problem() -> Problem:
    crops = {
        "corn": Crop("grass", 120, 8.0, 1.1, 1.25, False, 1.2),
        "soybean": Crop("legume", 110, 10.0, 1.0, 0.9, True, 1.0),
        "wheat": Crop("grass", 105, 4.0, 0.9, 1.0, False, 0.8),
        "clover": Crop("legume", 90, 3.0, 0.8, 0.7, True, 0.5),
    }
    zones = {
        "A": Zone(20.0, 3.0, 140.0, 0.2),
        "B": Zone(18.0, 11.0, 130.0, 0.45),
    }
    weather = WeatherYear(rain_mm=[3.0] * 365, et0_mm=[4.0] * 365, tmin_c=[12.0] * 365, tmax_c=[25.0] * 365)
    settings = {
        "cover_crops": ["clover"],
        "water_budget_m3": 300000,
        "horizon_years": 4,
        "acre_caps_ha": {"corn": 30.0},
        "equipment_max_zones": {"corn": 1},
    }
    return Problem(
        zones=zones,
        crops=crops,
        weather_years=[weather, weather, weather, weather],
        prices={"corn": 190, "soybean": 220, "wheat": 180, "clover": 120},
        weights={"profit": 1.0, "soil": 50.0, "erosion": 25.0},
        settings=settings,
    )


def main() -> None:
    st.set_page_config(page_title="Field Shift", layout="wide")
    st.title("Field Shift: Crop Rotation Planner")

    with st.sidebar:
        st.header("Inputs")
        st.text_input("Location", value="39.7, -96.6")
        w_profit = st.slider("Profit weight", 0.0, 5.0, 1.0)
        w_soil = st.slider("Soil weight", 0.0, 200.0, 50.0)
        w_erosion = st.slider("Erosion weight", 0.0, 200.0, 25.0)
        irrigation_budget = st.number_input("Irrigation budget (m³)", value=300000)
        user_rotation = st.text_area(
            "Optional user rotation (zone:crop,crop,crop,crop)",
            value="A:corn,soybean,wheat,clover\nB:soybean,corn,clover,wheat",
        )

    problem = _stub_problem()
    problem = Problem(
        zones=problem.zones,
        crops=problem.crops,
        weather_years=problem.weather_years,
        prices=problem.prices,
        weights={"profit": w_profit, "soil": w_soil, "erosion": w_erosion},
        settings={**problem.settings, "water_budget_m3": irrigation_budget},
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Evaluate")
        parsed = {}
        for line in user_rotation.splitlines():
            if ":" not in line:
                continue
            zone, seq = line.split(":", 1)
            parsed[zone.strip()] = [s.strip() for s in seq.split(",") if s.strip()]
        if parsed:
            report = evaluate(Rotation(assignments=parsed), problem)
            st.metric("Score", f"{report.total_score:,.1f}")
            st.write(f"Violations: {len(report.violations)}")

    with col2:
        st.subheader("Optimize")
        if st.button("Run optimizer"):
            best = optimize(problem)
            best_report = evaluate(best, problem)
            st.json(best.assignments)
            st.metric("Optimized score", f"{best_report.total_score:,.1f}")

    with col3:
        st.subheader("Strategy cards")
        st.info("Balanced: maximize score using current weights")
        st.info("Profit-first: increase profit weight")
        st.info("Soil-first: increase soil and erosion weights")

    st.subheader("Trade-off chart")
    chart_data = [
        {"strategy": "Balanced", "profit": 1.0, "soil": 1.0, "erosion": 1.0},
        {"strategy": "Profit-first", "profit": 1.3, "soil": 0.8, "erosion": 0.7},
        {"strategy": "Soil-first", "profit": 0.8, "soil": 1.4, "erosion": 1.4},
    ]
    fig = px.scatter(chart_data, x="profit", y="soil", size="erosion", color="strategy", hover_name="strategy")
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
