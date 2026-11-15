"""Checks for model.py. Run:  python check_model.py   (about half a minute)

Plain asserts, no test framework. The key check is EXACTNESS: on a small 2-field farm,
for every goal, the MILP's answer equals a brute-force search over every pair of
rotations (unpruned), with and without limits, on each available solver.
"""
import os
import time

import numpy as np

import model
from contract import (BACKTEST_COLUMNS, CONSTRAINTS, DEFAULT_LIMITS, FARM, GOALS, PLAN_COLUMNS,
                      WORST_SHARE, baseline_plan)
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
base = dict(CONSTRAINTS)


def default_limits(goal, farm=FARM, scenario="average", rules=CONSTRAINTS):
    """The limits the app starts each goal with: DEFAULT_LIMITS positions along limit_ranges."""
    ranges = model.limit_ranges(farm, None, scenario, rules)
    return {k: ranges[k][0] + pos * (ranges[k][1] - ranges[k][0]) for k, pos in DEFAULT_LIMITS[goal].items()}
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
print("2. Demo farm: every goal follows the ground rules and meets its default limits")
for scenario in ("average", "dry"):
    for goal in GOALS:
        t = model.solve(FARM, None, goal, scenario, {**base, "limits": default_limits(goal, scenario=scenario)})
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
    ("max_profit", {"shortfall_max": 0.8 * ref_s["shortfall"]}, pair["profit"], max, ~clash & (pair["short"] <= 0.8 * ref_s["shortfall"] + 1e-6)),
    ("min_water", {}, pair["water"], min, ~clash),
    ("min_water", {"profit_min": 0.97 * ref_s["profit"]}, pair["water"], min, ~clash & (pair["profit"] >= 0.97 * ref_s["profit"] - tol)),
    ("max_worst_profit", {}, pair["worst"], max, ~clash),
    ("max_worst_profit", {"profit_min": 0.99 * ref_s["profit"]}, pair["worst"], max, ~clash & (pair["profit"] >= 0.99 * ref_s["profit"] - tol)),
    ("max_soil", {}, pair["soil"], max, ~clash),
    ("max_soil", {"profit_min": 0.98 * ref_s["profit"]}, pair["soil"], max, ~clash & (pair["profit"] >= 0.98 * ref_s["profit"] - tol)),
]
for name in solvers():
    use_solver(name)
    for goal, limits, obj, sense, ok_mask in cases:
        best = sense(obj[ok_mask])
        t = model.solve(small, None, goal, "average", {**rules, "limits": limits})
        got = goal_value(goal, summary_of(t, small))
        rel = abs(got - best) / max(abs(best), 1)
        check(f"{name:6s} {goal:17s} limits={ {k: round(v) for k, v in limits.items()} or 'none'}", rel < 1e-5, f"MILP {got:,.2f} vs brute force {best:,.2f}")

# ---------------------------------------------------------------- 4. impossible limits
print("4. Impossible limits return a plan and say what wasn't met")
use_solver(solvers()[0])
too_much = 1.5 * model.limit_ranges(FARM, None, "average", CONSTRAINTS)["profit_min"][1]
t = model.solve(FARM, None, "min_water", "average", {**CONSTRAINTS, "limits": {"profit_min": too_much}})
check(f"profit at least ${too_much:,.0f}/yr (beyond reach): plan returned, status Relaxed", len(t) == 16 and t.attrs["status"] == "Relaxed")
check("…with a plain message", len(t.attrs["unmet"]) == 1, t.attrs["unmet"][0] if t.attrs["unmet"] else "none")
t = model.solve(FARM, None, "max_profit", "average", {**CONSTRAINTS, "max_crop_share": 0.30, "limits": {}})
check("acre cap below the biggest field (30% < 40%): still returns a plan", len(t) == 16, t.attrs["status"])

# ---------------------------------------------------------------- 5. goals behave as named
print("5. Each goal is best at its own measure (no limits)")
vals = {}
for goal in GOALS:
    t = model.solve(FARM, None, goal, "average", {**CONSTRAINTS, "limits": {}})
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

# ---------------------------------------------------------------- 8. rotation length and the cycle
print("8. Rotation length (2-5 years) and the repeating cycle")
two = {"North": ["soybeans", "corn"], "South": ["corn", "soybeans"],
       "East": ["soybeans", "corn"], "West": ["corn", "soybeans"]}
four = {k: v * 2 for k, v in two.items()}
e2, e4 = model.evaluate(two, FARM), model.evaluate(four, FARM)
check("2-year corn-soy = the same written as 4 years (per season)",
      abs(e2["profit_usd"].sum() / 2 - e4["profit_usd"].sum() / 4) < 1 and
      abs((e2["water_shortfall_mm"] * e2["acres"]).sum() / 2 - (e4["water_shortfall_mm"] * e4["acres"]).sum() / 4) < 1)
check("…and their backtests match", model.backtest(two, FARM)["total_profit_usd"].equals(model.backtest(four, FARM)["total_profit_usd"]))
one = {**FARM, "fields": [FARM["fields"][0]]}          # North, last crop corn
no_cap = {**CONSTRAINTS, "max_crop_share": 1}
wrap = rule_problems({"North": ["soybeans", "corn", "soybeans"]}, one, no_cap)
check("soy-corn-soy breaks no back-to-back through the wrap", any("repeats" in w for w in wrap), wrap[0] if wrap else "")
check("soy-corn is fine (wrap corn -> soy)", rule_problems({"North": ["soybeans", "corn"]}, one, no_cap) == [])
for name in solvers():
    use_solver(name)
    for L in (2, 3, 4, 5):
        model._candidates_cached.cache_clear()
        start = time.time()
        t = model.solve({**FARM, "years": L}, None, "max_profit", "average", dict(CONSTRAINTS))
        broken = rule_problems(model.table_to_plan(t), {**FARM, "years": L}, CONSTRAINTS)
        check(f"{name:6s} {L}-year search follows the rules", t["year"].max() == L and not broken
              and t.attrs["status"] == "Optimal", f"{time.time() - start:.2f} s")
use_solver(solvers()[0])
ref2 = model._summary(model._prep(None), FARM, two, None, "average", WORST_SHARE)
t = model.solve({**FARM, "years": 3}, None, "min_water", "average",
                {**CONSTRAINTS, "limits": {"profit_min": 0.8 * ref2["profit"]}})
got = summary_of(t, FARM)
check("3-year search, absolute profit limit is per season",
      got["profit"] >= 0.8 * ref2["profit"] - 1 and not t.attrs["unmet"],
      f"${got['profit']:,.0f}/yr vs your ${ref2['profit']:,.0f}/yr")
t = model.solve({**FARM, "years": 3}, None, "min_water", "average",
                {**CONSTRAINTS, "limits": {"profit_min": 0.9 * ref2["profit"]}})
check("…and 90% (beyond any 3-year rotation) is reported as unmet", len(t.attrs["unmet"]) == 1,
      t.attrs["unmet"][0] if t.attrs["unmet"] else "")

# ---------------------------------------------------------------- 9. limit ranges
print("9. limit_ranges brackets what the optimizer can reach")
use_solver(solvers()[0])
for L in (2, 4):
    farm_l = {**FARM, "years": L}
    ranges = model.limit_ranges(farm_l, None, "average", CONSTRAINTS)
    inside = True
    for goal in GOALS:
        got = summary_of(model.solve(farm_l, None, goal, "average", dict(CONSTRAINTS)), farm_l)
        for key, measure in (("profit_min", "profit"), ("shortfall_max", "shortfall"), ("soil_min", "soil")):
            lo, hi = ranges[key]
            inside &= lo - 1e-6 <= got[measure] <= hi + 1e-6
    check(f"{L}-year: every goal's plan lies inside the ranges", inside,
          f"profit ${ranges['profit_min'][0]:,.0f}–${ranges['profit_min'][1]:,.0f}/yr, "
          f"shortfall {ranges['shortfall_max'][0]:,.0f}–{ranges['shortfall_max'][1]:,.0f} acre-in/yr")
    loose = {"profit_min": ranges["profit_min"][0], "shortfall_max": ranges["shortfall_max"][1]}
    t = model.solve(farm_l, None, "max_soil", "average", {**CONSTRAINTS, "limits": loose})
    check(f"{L}-year: limits at their loosest ends are met", not t.attrs["unmet"])
check("production ranges only for allowed crops",
      set(model.limit_ranges(FARM, None, "average", {**CONSTRAINTS, "allowed_crops": ["corn", "soybeans"]})["production_min"]) <= {"corn", "soybeans"})

# ---------------------------------------------------------------- 10. timing
print("10. Timing: what one app rerun costs (solve + evaluate + 2 backtests)")
for name in solvers():
    use_solver(name)
    model._candidates_cached.cache_clear()
    for label in ("first run", "new limits"):
        start = time.time()
        lim = None if label == "first run" else {"shortfall_max": sum(model.limit_ranges(FARM)["shortfall_max"]) / 2}
        t = model.solve(FARM, None, "max_profit", "average", {**CONSTRAINTS, "limits": lim})
        model.evaluate(ref, FARM)
        model.backtest(model.table_to_plan(t), FARM, covers=model.table_to_covers(t))
        model.backtest(ref, FARM)
        print(f"  {name:6s} {label:10s} {time.time() - start:5.2f} s")

print()
print(f"{sum(RESULTS)} of {len(RESULTS)} checks passed")
raise SystemExit(0 if all(RESULTS) else 1)
