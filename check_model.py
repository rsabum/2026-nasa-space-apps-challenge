"""Checks for model.py. Run:  python check_model.py   (about half a minute)

Plain asserts, no test framework. The key check is EXACTNESS: on a small 2-field farm,
for every goal, the MILP's answer equals a brute-force search over every pair of
rotations (unpruned), with and without limits, on each available solver.
"""
import os
import time

import numpy as np

import model
from contract import (BACKTEST_COLUMNS, CONSTRAINTS, FARM, GOALS, PLAN_COLUMNS, WORST_SHARE,
                      baseline_plan)
from rules import rule_problems

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  (' + detail + ')') if detail else ''}")


def use_solver(name):
    os.environ["FIELD_SHIFT_SOLVER"] = name
    model._SOLVE_CACHE.clear()


def solvers():
    names = ["cbc"]
    if model._gurobi_env() is not None:
        names.insert(0, "gurobi")
    else:
        print("  NOTE  Gurobi not available here: checking CBC only")
    return names


def goal_value(goal, s):
    return {"max_profit": s["profit"], "min_water": s["water"],
            "max_worst_profit": s["worst_profit"], "max_soil": s["soil"]}[goal]


def summary_of(table, farm, scenario="average"):
    prep = model._prep(None)
    return model._summary(prep, farm, model.table_to_plan(table), model.table_to_covers(table),
                          scenario, WORST_SHARE)


# ---------------------------------------------------------------- 1. contract shape
print("1. Contract shape and repeatability")
ref = baseline_plan(FARM)
base = {**CONSTRAINTS, "reference_plan": ref}
use_solver(solvers()[0])
t = model.solve(FARM, None, "max_profit", "average", base)
check("solve() returns PLAN_COLUMNS (+ cover, irrigation_mm)", list(t.columns[:len(PLAN_COLUMNS)]) == PLAN_COLUMNS)
check("one row per field per year", len(t) == len(FARM["fields"]) * FARM["years"])
bt = model.backtest(ref, FARM)
check("backtest() returns BACKTEST_COLUMNS, 44 rows",
      list(bt.columns[:len(BACKTEST_COLUMNS)]) == BACKTEST_COLUMNS and len(bt) == 44)
model._SOLVE_CACHE.clear()
t2 = model.solve(FARM, None, "max_profit", "average", base)
check("same answer on a fresh solve", t.equals(t2))
ev = model.evaluate(ref, FARM)
check("evaluate() of the corn-soy plan has no rye", not ev["cover"].any())

# ---------------------------------------------------------------- 2. demo farm, every goal
print("2. Demo farm: every goal follows the ground rules and its default limits")
for scenario in ("average", "dry"):
    for goal in GOALS:
        t = model.solve(FARM, None, goal, scenario, base)
        broken = rule_problems(model.table_to_plan(t), FARM, CONSTRAINTS)
        check(f"{scenario:7s} {goal:17s}", not broken and not t.attrs["unmet"] and t.attrs["status"] == "Optimal",
              f"solver {t.attrs['solver']}, profit ${t['profit_usd'].sum():,}")

# ---------------------------------------------------------------- 3. exactness by brute force
print("3. Exactness: MILP = brute force over every pair of rotations (2-field farm)")
small = {**FARM, "fields": [
    {"name": "A", "acres": 60, "soil": "silt loam", "last_crop": "corn"},
    {"name": "B", "acres": 40, "soil": "sandy loam", "last_crop": "soybeans", "irrigated": True}]}
rules = {**CONSTRAINTS, "max_crop_share": 0.75}     # 0.75: the two fields can't grow the same crop the same year
prep = model._prep(None)
full = [model.Candidates(prep, f, small, rules, prune=False) for f in small["fields"]]
acres = [60.0, 40.0]
total = 100.0
pool = prep.pool("average")


def per_rotation(c):
    """Farm-level contribution of each rotation on its field (acres already applied)."""
    return {"profit": c.profit_y[:, pool].mean(1), "water": (c.short_y[:, pool].mean(1) + c.irr_y[:, pool].mean(1)) / 25.4,
            "short": c.short_y[:, pool].mean(1) / 25.4, "soil": c.soil / total, "profit_y": c.profit_y}


a, b = (per_rotation(c) for c in full)
pair = {k: acres[0] * a[k][:, None] + acres[1] * b[k][None, :] for k in ("profit", "water", "short", "soil")}
pair["soil"] = (acres[0] * a["soil"][:, None] + acres[1] * b["soil"][None, :])
# Acre cap: the same crop on both fields in the same year would be 100% > 75%.
clash = (full[0].C[:, None, :] == full[1].C[None, :, :]).any(2)
# Bad-year profit (CVaR) for every pair, row by row to keep memory small.
k = WORST_SHARE * len(prep.years)
cvar = np.empty(clash.shape)
for i in range(len(full[0].C)):
    py = np.sort(acres[0] * a["profit_y"][i][None, :] + acres[1] * b["profit_y"], axis=1)
    whole = int(np.floor(k))
    cvar[i] = (py[:, :whole].sum(1) + (k - whole) * py[:, whole]) / k
pair["worst"] = cvar
print(f"  ({len(full[0].C)} x {len(full[1].C)} = {clash.size:,} pairs, {int((~clash).sum()):,} within the acre cap)")

ref_small = baseline_plan(small)
ref_s = model._summary(prep, small, ref_small, None, "average", WORST_SHARE)
tol = 1e-6 * abs(ref_s["profit"])          # the solver's own feasibility tolerance, roughly
cases = [  # goal, limits, brute-force objective, sense, feasible mask
    ("max_profit", {}, pair["profit"], max, ~clash),
    ("max_profit", {"shortfall_max": 0.8}, pair["profit"], max, ~clash & (pair["short"] <= 0.8 * ref_s["shortfall"] + 1e-6)),
    ("min_water", {}, pair["water"], min, ~clash),
    ("min_water", {"profit_min": 0.97}, pair["water"], min, ~clash & (pair["profit"] >= model._at_least(ref_s["profit"], 0.97) - tol)),
    ("max_worst_profit", {}, pair["worst"], max, ~clash),
    ("max_worst_profit", {"profit_min": 0.99}, pair["worst"], max, ~clash & (pair["profit"] >= model._at_least(ref_s["profit"], 0.99) - tol)),
    ("max_soil", {}, pair["soil"], max, ~clash),
    ("max_soil", {"profit_min": 0.98}, pair["soil"], max, ~clash & (pair["profit"] >= model._at_least(ref_s["profit"], 0.98) - tol)),
]
for name in solvers():
    use_solver(name)
    for goal, limits, obj, sense, ok_mask in cases:
        best = sense(obj[ok_mask])
        t = model.solve(small, None, goal, "average", {**rules, "limits": limits, "reference_plan": ref_small})
        got = goal_value(goal, summary_of(t, small))
        rel = abs(got - best) / max(abs(best), 1)
        check(f"{name:6s} {goal:17s} limits={limits or 'none'}", rel < 1e-5, f"MILP {got:,.2f} vs brute force {best:,.2f}")

# ---------------------------------------------------------------- 4. impossible limits
print("4. Impossible limits return a plan and say what wasn't met")
use_solver(solvers()[0])
t = model.solve(FARM, None, "min_water", "average", {**CONSTRAINTS, "limits": {"profit_min": 2.0}, "reference_plan": ref})
check("profit at least 200% of yours: plan returned, status Relaxed", len(t) == 16 and t.attrs["status"] == "Relaxed")
check("…with a plain message", len(t.attrs["unmet"]) == 1, t.attrs["unmet"][0] if t.attrs["unmet"] else "none")
t = model.solve(FARM, None, "max_profit", "average", {**CONSTRAINTS, "max_crop_share": 0.30, "limits": {}, "reference_plan": ref})
check("acre cap below the biggest field (30% < 40%): still returns a plan", len(t) == 16, t.attrs["status"])

# ---------------------------------------------------------------- 5. goals behave as named
print("5. Each goal is best at its own measure (no limits)")
vals = {}
for goal in GOALS:
    t = model.solve(FARM, None, goal, "average", {**CONSTRAINTS, "limits": {}, "reference_plan": ref})
    vals[goal] = summary_of(t, FARM)
for goal, sense in (("max_profit", max), ("min_water", min), ("max_worst_profit", max), ("max_soil", max)):
    mine = goal_value(goal, vals[goal])
    others = [goal_value(goal, vals[g]) for g in GOALS]
    check(f"{goal:17s} wins on its own measure", abs(mine - sense(others)) <= 1e-6 * (abs(mine) + 1), f"{mine:,.1f}")

# ---------------------------------------------------------------- 6. weather sense
print("6. Weather makes sense")
check("dry-year profit below typical (corn-soy)",
      model.evaluate(ref, FARM, scenario="dry")["profit_usd"].sum() < model.evaluate(ref, FARM)["profit_usd"].sum())
check("2012 is the driest season", int(bt.loc[bt["growing_season_rain_mm"].idxmin(), "year"]) == 2012)
check("2012 is corn-soy's worst profit season", int(bt.loc[bt["total_profit_usd"].idxmin(), "year"]) == 2012)
wet = {**FARM, "fields": [{**f, "irrigated": f["name"] == "West"} for f in FARM["fields"]]}
dry_w = model.evaluate(ref, FARM).query("field == 'West'")
irr_w = model.evaluate(ref, wet).query("field == 'West'")
check("irrigating West cuts its shortfall and pumps water",
      irr_w["water_shortfall_mm"].sum() < dry_w["water_shortfall_mm"].sum() and irr_w["irrigation_mm"].sum() > 0)

# ---------------------------------------------------------------- 7. trade-off curve
print("7. Trade-off curve (solve_pareto)")
opts = model.solve_pareto(FARM, None, "average", CONSTRAINTS, n=7)
profits = [o["total_profit_usd"] for o in opts]
water = [o["total_shortfall_acre_in"] + o["total_irrigation_acre_in"] for o in opts]
check("several distinct options", len(opts) >= 3, f"{len(opts)} options")
check("more profit costs more water", profits == sorted(profits) and water == sorted(water))

# ---------------------------------------------------------------- 8. fake_model still works
print("8. fake_model.py still runs with a goal name")
import fake_model  # noqa: E402
t = fake_model.solve(FARM, None, "max_profit", "average", CONSTRAINTS)
check("fake_model.solve(goal=...)", len(t) == 16)

# ---------------------------------------------------------------- 9. timing
print("9. Timing: what one app rerun costs (solve + evaluate + 2 backtests)")
for name in solvers():
    use_solver(name)
    model._candidates_cached.cache_clear()
    for label in ("first run", "new limits"):
        start = time.time()
        lim = None if label == "first run" else {"shortfall_max": 0.9}
        t = model.solve(FARM, None, "max_profit", "average", {**CONSTRAINTS, "limits": lim, "reference_plan": ref})
        model.evaluate(ref, FARM)
        model.backtest(model.table_to_plan(t), FARM, covers=model.table_to_covers(t))
        model.backtest(ref, FARM)
        print(f"  {name:6s} {label:10s} {time.time() - start:5.2f} s")

print()
print(f"{sum(RESULTS)} of {len(RESULTS)} checks passed")
raise SystemExit(0 if all(RESULTS) else 1)
