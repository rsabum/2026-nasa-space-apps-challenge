"""Evaluate a user-provided rotation."""

from __future__ import annotations

from .constraints import (
    acre_cap,
    equipment,
    erosion_cover_required,
    legume_required,
    no_same_family_consecutive,
    season_fits,
    water_budget,
)
from .models import Problem, Report, Rotation
from .scoring import score_rotation


def evaluate(rotation: Rotation, problem: Problem) -> Report:
    """Score a rotation and collect all violated constraints."""
    violations = []
    for check in (
        season_fits,
        no_same_family_consecutive,
        legume_required,
        erosion_cover_required,
        water_budget,
        acre_cap,
        equipment,
    ):
        violations.extend(check(rotation, problem))

    components = score_rotation(problem, rotation)
    penalty = float(problem.settings.get("violation_penalty", 1000.0)) * len(violations)
    return Report(
        total_score=float(components["total_score"]) - penalty,
        violations=violations,
        profit=float(components["profit"]),
        soil_score=float(components["soil_score"]),
        erosion_score=float(components["erosion_score"]),
        weather_year_results=list(components["weather_year_results"]),
    )
