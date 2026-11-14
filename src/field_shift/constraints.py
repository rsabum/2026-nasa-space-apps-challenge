"""Constraint checks for rotations."""

from __future__ import annotations

from collections import defaultdict

from .models import Problem, Rotation, Violation
from .scoring import estimate_rotation_water_m3


def season_fits(rotation: Rotation, problem: Problem) -> list[Violation]:
    """Ensure selected crops fit within available weather year length."""
    violations: list[Violation] = []
    weather_days = min((len(w.rain_mm) for w in problem.weather_years), default=0)
    for zone_name, sequence in rotation.assignments.items():
        for year, crop_name in enumerate(sequence):
            crop = problem.crops[crop_name]
            if crop.season_days > weather_days:
                violations.append(
                    Violation(
                        constraint="season_fits",
                        scope=f"{zone_name}:year_{year + 1}",
                        message=f"{crop_name} season ({crop.season_days}d) exceeds weather year length ({weather_days}d).",
                    )
                )
    return violations


def no_same_family_consecutive(rotation: Rotation, problem: Problem) -> list[Violation]:
    """Disallow consecutive crops from the same botanical family."""
    violations: list[Violation] = []
    for zone_name, sequence in rotation.assignments.items():
        for idx in range(1, len(sequence)):
            prev_crop = problem.crops[sequence[idx - 1]]
            curr_crop = problem.crops[sequence[idx]]
            if prev_crop.family == curr_crop.family:
                violations.append(
                    Violation(
                        constraint="no_same_family_consecutive",
                        scope=f"{zone_name}:years_{idx}_{idx + 1}",
                        message=f"{sequence[idx - 1]} and {sequence[idx]} share family '{curr_crop.family}'.",
                    )
                )
    return violations


def legume_required(rotation: Rotation, problem: Problem) -> list[Violation]:
    """Require at least one nitrogen-fixing crop in each zone horizon."""
    violations: list[Violation] = []
    for zone_name, sequence in rotation.assignments.items():
        if not any(problem.crops[crop_name].n_fixing for crop_name in sequence):
            violations.append(
                Violation(
                    constraint="legume_required",
                    scope=zone_name,
                    message="No nitrogen-fixing crop scheduled in this zone over the planning horizon.",
                )
            )
    return violations


def erosion_cover_required(rotation: Rotation, problem: Problem) -> list[Violation]:
    """On high-risk slopes, require at least one designated cover crop."""
    violations: list[Violation] = []
    cover_crops = set(problem.settings.get("cover_crops", []))
    slope_threshold = float(problem.settings.get("slope_cover_threshold_pct", 8.0))
    erodibility_threshold = float(problem.settings.get("erodibility_cover_threshold", 0.3))

    for zone_name, zone in problem.zones.items():
        if zone.slope_pct < slope_threshold or zone.erodibility < erodibility_threshold:
            continue
        sequence = rotation.assignments.get(zone_name, [])
        if not any(crop in cover_crops for crop in sequence):
            violations.append(
                Violation(
                    constraint="erosion_cover_required",
                    scope=zone_name,
                    message="High erosion-risk zone must include at least one cover crop in the horizon.",
                )
            )
    return violations


def water_budget(rotation: Rotation, problem: Problem) -> list[Violation]:
    """Ensure estimated irrigation demand does not exceed farm budget."""
    budget_m3 = float(problem.settings.get("water_budget_m3", float("inf")))
    used_m3 = estimate_rotation_water_m3(problem, rotation)
    if used_m3 <= budget_m3:
        return []
    return [
        Violation(
            constraint="water_budget",
            scope="farm",
            message=f"Estimated irrigation demand {used_m3:.1f} m3 exceeds budget {budget_m3:.1f} m3.",
        )
    ]


def acre_cap(rotation: Rotation, problem: Problem) -> list[Violation]:
    """Enforce crop-specific area caps per year."""
    caps = problem.settings.get("acre_caps_ha", {})
    if not isinstance(caps, dict) or not caps:
        return []

    violations: list[Violation] = []
    horizon = max((len(seq) for seq in rotation.assignments.values()), default=0)
    for year in range(horizon):
        crop_area: dict[str, float] = defaultdict(float)
        for zone_name, seq in rotation.assignments.items():
            if year >= len(seq):
                continue
            crop_area[seq[year]] += problem.zones[zone_name].area_ha
        for crop_name, area in crop_area.items():
            cap = float(caps.get(crop_name, float("inf")))
            if area > cap:
                violations.append(
                    Violation(
                        constraint="acre_cap",
                        scope=f"year_{year + 1}",
                        message=f"{crop_name} area {area:.2f} ha exceeds cap {cap:.2f} ha.",
                    )
                )
    return violations


def equipment(rotation: Rotation, problem: Problem) -> list[Violation]:
    """Limit crop concurrency by equipment capacity (max zones per crop per year)."""
    limits = problem.settings.get("equipment_max_zones", {})
    if not isinstance(limits, dict) or not limits:
        return []

    violations: list[Violation] = []
    horizon = max((len(seq) for seq in rotation.assignments.values()), default=0)
    for year in range(horizon):
        crop_zones: dict[str, int] = defaultdict(int)
        for _zone_name, seq in rotation.assignments.items():
            if year < len(seq):
                crop_zones[seq[year]] += 1
        for crop_name, used in crop_zones.items():
            limit = int(limits.get(crop_name, 10**9))
            if used > limit:
                violations.append(
                    Violation(
                        constraint="equipment",
                        scope=f"year_{year + 1}",
                        message=f"{crop_name} scheduled in {used} zones, exceeding equipment limit {limit}.",
                    )
                )
    return violations
