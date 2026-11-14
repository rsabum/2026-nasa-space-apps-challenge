"""Optimization mode for selecting zone sequences with MILP."""

from __future__ import annotations

from itertools import product

import pulp

from .evaluate import evaluate
from .models import Problem, Rotation
from .scoring import sequence_water_m3


def enumerate_sequences(zone_name: str, problem: Problem, horizon: int = 4) -> list[tuple[str, ...]]:
    """Enumerate locally-allowed crop sequences for a zone."""
    crops = list(problem.crops)
    sequences: list[tuple[str, ...]] = []
    for candidate in product(crops, repeat=horizon):
        ok = True
        for i in range(1, len(candidate)):
            if problem.crops[candidate[i - 1]].family == problem.crops[candidate[i]].family:
                ok = False
                break
        if not ok:
            continue
        if not any(problem.crops[name].n_fixing for name in candidate):
            continue
        sequences.append(candidate)
    return sequences


def _sequence_score(problem: Problem, zone_name: str, sequence: tuple[str, ...]) -> float:
    report = evaluate(Rotation(assignments={zone_name: list(sequence)}), problem)
    return report.total_score


def optimize(problem: Problem) -> Rotation:
    """Choose one sequence per zone maximizing score under farm-wide constraints."""
    horizon = int(problem.settings.get("horizon_years", 4))
    seqs_by_zone = {z: enumerate_sequences(z, problem, horizon) for z in problem.zones}

    model = pulp.LpProblem("field_shift", pulp.LpMaximize)
    x: dict[tuple[str, int], pulp.LpVariable] = {}
    scores: dict[tuple[str, int], float] = {}
    waters: dict[tuple[str, int], float] = {}

    for zone_name, sequences in seqs_by_zone.items():
        for idx, seq in enumerate(sequences):
            x[(zone_name, idx)] = pulp.LpVariable(f"x_{zone_name}_{idx}", cat="Binary")
            scores[(zone_name, idx)] = _sequence_score(problem, zone_name, seq)
            waters[(zone_name, idx)] = sequence_water_m3(problem, zone_name, seq)
        model += pulp.lpSum(x[(zone_name, i)] for i in range(len(sequences))) == 1

    model += pulp.lpSum(scores[key] * var for key, var in x.items())

    budget = float(problem.settings.get("water_budget_m3", float("inf")))
    if budget < float("inf"):
        model += pulp.lpSum(waters[key] * var for key, var in x.items()) <= budget

    caps = problem.settings.get("acre_caps_ha", {})
    if isinstance(caps, dict) and caps:
        for year in range(horizon):
            for crop_name, cap in caps.items():
                model += (
                    pulp.lpSum(
                        problem.zones[z].area_ha * x[(z, i)]
                        for z, sequences in seqs_by_zone.items()
                        for i, seq in enumerate(sequences)
                        if seq[year] == crop_name
                    )
                    <= float(cap)
                )

    equip = problem.settings.get("equipment_max_zones", {})
    if isinstance(equip, dict) and equip:
        for year in range(horizon):
            for crop_name, limit in equip.items():
                model += (
                    pulp.lpSum(
                        x[(z, i)]
                        for z, sequences in seqs_by_zone.items()
                        for i, seq in enumerate(sequences)
                        if seq[year] == crop_name
                    )
                    <= int(limit)
                )

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    assignments: dict[str, list[str]] = {}
    for zone_name, sequences in seqs_by_zone.items():
        selected_idx = 0
        for i in range(len(sequences)):
            if pulp.value(x[(zone_name, i)]) and pulp.value(x[(zone_name, i)]) > 0.5:
                selected_idx = i
                break
        assignments[zone_name] = list(sequences[selected_idx])
    return Rotation(assignments=assignments)


def gap_to_optimal(problem: Problem, candidate: Rotation) -> float:
    """Return objective gap between candidate and optimizer output."""
    best = evaluate(optimize(problem), problem).total_score
    cand = evaluate(candidate, problem).total_score
    return best - cand


def nearest_fix(problem: Problem, candidate: Rotation) -> Rotation:
    """Attempt a minimal-fix rotation by replacing repeated-family years."""
    assignments = {zone: list(seq) for zone, seq in candidate.assignments.items()}
    for zone_name, seq in assignments.items():
        for i in range(1, len(seq)):
            if problem.crops[seq[i - 1]].family != problem.crops[seq[i]].family:
                continue
            for crop_name, crop in problem.crops.items():
                if crop.family != problem.crops[seq[i - 1]].family:
                    seq[i] = crop_name
                    break
    return Rotation(assignments=assignments)
