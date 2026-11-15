"""Stand-in for Robert's model.py. Same function signatures, random but valid output.

When model.py is ready, change one line in app.py:
    import fake_model as model   ->   import model
"""
import random

import pandas as pd

from contract import (BACKTEST_COLUMNS, FIRST_YEAR, LAST_YEAR, PLAN_COLUMNS,
                      baseline_plan)
from rules import rule_problems

ACRE_IN_PER_MM_ACRE = 1 / 25.4


def _rng(*parts):
    # Deterministic per input, so the app does not flicker on every rerun.
    return random.Random(str(parts))


def evaluate(plan, farm, data=None, scenario="average"):
    """Score a plan {field: [crop per year]}. Returns one row per field per year."""
    acres = {f["name"]: f["acres"] for f in farm["fields"]}
    rows = []
    for field, crops in plan.items():
        for i, crop in enumerate(crops):
            r = _rng(field, i, crop, scenario)
            need = {"corn": 560, "soybeans": 480, "winter_wheat": 420, "sorghum": 430}.get(crop, 500)
            rain = 380 if scenario == "dry" else 500
            shortfall = max(0, need - rain + r.uniform(-40, 40))
            rows.append({
                "field": field,
                "year": i + 1,
                "crop": crop,
                "acres": acres[field],
                "water_need_mm": need,
                "water_shortfall_mm": round(shortfall, 1),
                "soil_score_change": round(r.uniform(-1, 2) + (1 if crop == "soybeans" else 0), 2),
                "profit_usd": round(acres[field] * r.uniform(80, 320) * (0.7 if scenario == "dry" else 1)),
            })
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def solve(farm, data=None, goal="max_profit", scenario="average", constraints=None):
    """Return a random plan that follows every ground rule (if one can be found), scored by evaluate().
    `goal` is a key of contract.GOALS (older callers passed a weights dict; both are accepted)."""
    constraints = constraints or {}
    allowed = constraints.get("allowed_crops") or ["corn", "soybeans"]
    r = _rng("solve", repr(goal), scenario,
             repr(sorted(constraints.items())), repr(farm["fields"]))
    best, best_broken = {}, None
    for attempt in range(500):   # draw random plans; keep the one that breaks the fewest rules
        plan = {}
        for f in farm["fields"]:
            prev, seq = f["last_crop"], []
            for _ in range(farm["years"]):
                options = [c for c in allowed if not (constraints.get("no_repeat") and c == prev)] or allowed
                prev = r.choice(options)
                seq.append(prev)
            plan[f["name"]] = seq
        broken = len(rule_problems(plan, farm, constraints))
        if best_broken is None or broken < best_broken:
            best, best_broken = plan, broken
        if broken == 0:
            break
    return evaluate(best, farm, data, scenario)


def solve_pareto(farm, data=None, scenario="average", constraints=None, n=9):
    """Return n trade-off options."""
    options = []
    for k in range(n):
        table = solve(farm, data, {"profit": k, "water": n - k, "soil": 3}, scenario, constraints)
        options.append({
            "total_profit_usd": int(table["profit_usd"].sum()),
            "total_shortfall_acre_in": round((table["water_shortfall_mm"] * table["acres"]).sum() * ACRE_IN_PER_MM_ACRE, 1),
            "soil_score_change": round(table["soil_score_change"].sum(), 2),
            "plan": table,
        })
    return options


def backtest(plan, farm, data=None):
    """Score a fixed plan against every historical year. One row per year."""
    total_acres = sum(f["acres"] for f in farm["fields"])
    tag = str(sorted(plan.items()))
    rows = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        r = _rng("backtest", tag, year)
        rain = r.gauss(500, 90) if year != 2012 else 260
        stress = max(0.3, min(1.1, rain / 500))
        rows.append({
            "year": year,
            "growing_season_rain_mm": round(rain),
            "total_profit_usd": round(total_acres * r.uniform(150, 260) * stress),
            "total_shortfall_acre_in": round(max(0, 520 - rain) * total_acres / 25.4, 1),
            "soil_score_change": round(r.uniform(-1, 3), 2),
        })
    return pd.DataFrame(rows, columns=BACKTEST_COLUMNS)


def table_to_plan(table):
    """Convert a plan table back to {field: [crop per year]}."""
    return {f: list(g.sort_values("year")["crop"]) for f, g in table.groupby("field", sort=False)}


__all__ = ["evaluate", "solve", "solve_pareto", "backtest", "table_to_plan", "baseline_plan"]
