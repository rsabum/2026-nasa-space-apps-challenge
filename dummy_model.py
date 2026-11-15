"""Stand-in for model.py while working on the app and UX (owner: Claude-Thomas).

Same functions, same tables, but solve() doesn't run the optimizer (no Gurobi, no CBC):
it picks a sensible-looking rotation for the chosen goal from a fixed pattern, then scores
it with Robert's real crop simulation. So every number on screen is a real simulated
result for that plan; only the "this is the best plan" part is fake.

Everything except solve() and solve_pareto() is Robert's code, re-exported unchanged
(evaluate, backtest, limit_ranges, table_to_plan, table_to_covers: simulation only, fast).

Switch in ui.py: USE_REAL_OPTIMIZER = True to go back to model.py.
"""
import itertools

import model as _real
from contract import CROPS, GOALS
from rules import rule_problems

# Re-exported unchanged: these only simulate, they never call a solver.
evaluate = _real.evaluate
backtest = _real.backtest
limit_ranges = _real.limit_ranges
table_to_plan = _real.table_to_plan
table_to_covers = _real.table_to_covers
baseline_plan = _real.baseline_plan

SOLVER_NAME = "dummy (UI mode)"

# A rotation pattern per goal; each field starts at a different point in it, so the
# fields differ (and no single crop takes every acre in a year).
PATTERNS = {
    "max_profit": ["corn", "soybeans", "corn", "winter_wheat"],
    "min_water": ["sorghum", "winter_wheat", "soybeans"],
    "max_worst_profit": ["corn", "soybeans", "winter_wheat", "sorghum"],
    "max_soil": ["soybeans", "winter_wheat", "soybeans", "corn"],
}


def pick_solver(name=None):
    """Matches model.pick_solver's shape: (name, solver object)."""
    return SOLVER_NAME, None


def _rotation(goal, length, offset, constraints):
    """One field's rotation: the goal's pattern from `offset`, bent to the ground rules
    (allowed crops, no back-to-back, at least one soybean year)."""
    allowed = [c for c in (constraints.get("allowed_crops") or CROPS) if c in CROPS] or list(CROPS)
    pattern = [c for c in PATTERNS.get(goal, PATTERNS["max_profit"]) if c in allowed] or allowed
    seq = [pattern[(offset + t) % len(pattern)] for t in range(length)]

    if constraints.get("no_repeat", True) and len(allowed) > 1:
        for t in range(length):
            prev = seq[t - 1] if t else (seq[-1] if length > 1 else None)
            if seq[t] == prev:
                nxt = seq[t + 1] if t + 1 < length else None
                seq[t] = next((c for c in allowed if c not in (prev, nxt)),   # differs from both sides
                              next(c for c in allowed if c != prev))         # else just from the year before

    if constraints.get("min_legume_years", 0) and "soybeans" in allowed and "soybeans" not in seq:
        for t in range(length):
            before, after = seq[t - 1], seq[(t + 1) % length]
            if "soybeans" not in (before, after) or length < 3:
                seq[t] = "soybeans"
                break
    return seq


def _plan(farm, goal, constraints, shift=0):
    """Pick one rotation per field so the whole plan breaks as few ground rules as possible
    (ideally none), judged by rules.rule_problems: the same check the app shows. Each field
    gets a few candidates (the goal's pattern started at different points, then the other
    goals' patterns); combinations are tried in order, so the goal's own pattern wins ties."""
    length = int(farm.get("years", 4))
    names = [f["name"] for f in farm["fields"]]
    goals = [goal] + [g for g in PATTERNS if g != goal]

    def candidates(i):
        out = []
        for g in goals:
            for o in range(4):
                seq = _rotation(g, length, i + shift + o, constraints)
                if seq not in out:
                    out.append(seq)
        return out[:6]

    cands = [candidates(i) for i in range(len(names))]
    rules = {k: v for k, v in constraints.items() if k not in ("limits", "reference_plan")}

    def problems(plan):
        return len(rule_problems(plan, farm, rules))

    if len(names) <= 6:                       # small farm: try every combination (<= 6^6)
        best, best_n = None, None
        for combo in itertools.product(*cands):
            plan = dict(zip(names, combo))
            n = problems(plan)
            if best_n is None or n < best_n:
                best, best_n = plan, n
                if n == 0:
                    break
        return best
    plan = {n: c[0] for n, c in zip(names, cands)}   # big farm: improve one field at a time
    for name, options in zip(names, cands):
        plan[name] = min(options, key=lambda seq: problems({**plan, name: seq}))
    return plan


def solve(farm, data=None, goal="max_profit", scenario="average", constraints=None):
    """A plausible plan for the goal, scored by the real simulation. Same return shape as
    model.solve: evaluate()'s table with attrs goal / solver / status / unmet."""
    if goal not in GOALS:
        raise ValueError(f"unknown goal {goal!r}; pick one of {list(GOALS)}")
    constraints = dict(constraints or {})
    table = evaluate(_plan(farm, goal, constraints), farm, data, scenario)
    table.attrs.update(goal=goal, solver=SOLVER_NAME, status="Optimal", unmet=[])
    return table


def solve_pareto(farm, data=None, scenario="average", constraints=None, n=9):
    """A handful of different plans, scored for real, in model.solve_pareto's format."""
    constraints = {k: v for k, v in (constraints or {}).items() if k != "limits"}
    options, seen = [], set()
    for goal in GOALS:
        for shift in range(3):
            plan = _plan(farm, goal, constraints, shift)
            tag = str(sorted(plan.items()))
            if tag in seen:
                continue
            seen.add(tag)
            t = evaluate(plan, farm, data, scenario)
            options.append({
                "total_profit_usd": int(t["profit_usd"].sum()),
                "total_shortfall_acre_in": round(float((t["water_shortfall_mm"] * t["acres"]).sum() / 25.4), 1),
                "total_irrigation_acre_in": round(float((t["irrigation_mm"] * t["acres"]).sum() / 25.4), 1),
                "soil_score_change": round(float(t["soil_score_change"].sum()), 2),
                "plan": t,
            })
            if len(options) >= n:
                return options
    return options


__all__ = ["evaluate", "solve", "solve_pareto", "backtest", "table_to_plan", "table_to_covers",
           "baseline_plan", "pick_solver", "limit_ranges"]
