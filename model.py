"""Field Shift optimizer: Enumerate, Simulate, Assign (owner: Robert).

    1. Enumerate  every rotation of the chosen length (2-5 years) per field: a crop each year
                  and a yes/no rye cover after it (4^4 x 2^4 = 4,096 for 4 years), keeping
                  those that pass the ground rules. A rotation repeats: year 1 follows the last.
    2. Simulate   each rotation in every weather year, by table lookups into the
                  precomputed crop model (crop_sim.py).
    3. Assign     one rotation per field with a small integer program (PuLP), solved by
                  Gurobi when it is licensed on this machine, otherwise by the free CBC.

The farmer picks ONE goal (contract.GOALS); the other measures become absolute limits
("profit at least $40,000 a year"). This is the epsilon-constraint method (Haimes,
Lasdon & Wismer 1971). limit_ranges() says what the farm can reach on each measure, for
the app's sliders. Impossible limits never crash: the plan comes back with
table.attrs["unmet"] explaining what couldn't be met.

The app (ui.py) imports this module as `model`; the function signatures are the team's
interface contract (see contract.py and CLAUDE.md).
"""
import functools
import itertools
import json
import os

import numpy as np
import pandas as pd
import pulp

import synthetic_data
from contract import (BACKTEST_COLUMNS, GOAL_OWN_LIMITS, GOALS, LIMIT_LABELS, PLAN_COLUMNS,
                      WORST_SHARE, baseline_plan)
from crop_sim import CropSim
from rules import rule_problems

MM_PER_IN = 25.4
DRY_SHARE = 0.25        # the "dry" scenario = the driest quarter of seasons by May-Sep rain
GAP = 1e-6              # solver optimality gap: effectively exact
TIME_LIMIT = 30         # seconds per solve; the best plan found so far is used if it's hit


# ---------------------------------------------------------------- data and crop model

@functools.lru_cache(maxsize=1)
def _synthetic():
    return synthetic_data.load_data()


_PREPARED = {}


def _prep(data):
    """The crop model and lookup arrays for a dataset, built once and reused."""
    data = _synthetic() if data is None else data
    if id(data) not in _PREPARED:
        _PREPARED[id(data)] = (data, Prepared(data))   # keep `data` alive so its id stays unique
    return _PREPARED[id(data)][1]


def _flag(value):
    """True/False from a table cell that may be None, NaN or a numpy bool."""
    try:
        return bool(value) and not pd.isna(value)
    except (TypeError, ValueError):
        return False


class Prepared:
    def __init__(self, data):
        self.sim = CropSim(data)
        crops = data["crops"]
        self.crops = list(crops["crop"])
        self.idx = {c: i for i, c in enumerate(self.crops)}
        n = len(self.crops)
        self.price = crops["price_usd"].to_numpy(float)
        self.base_yield = crops["base_yield"].to_numpy(float)
        self.cost = crops["cost_usd_per_acre"].to_numpy(float)
        self.soil_points = crops["soil_points"].to_numpy(float)
        site = data["site"].iloc[0]
        self.n_price = float(site["n_price_usd_per_lb"])
        self.rye_cost = float(site["rye_cost_usd_per_acre"])
        self.rye_points = float(site["rye_soil_points"])
        self.irr_cost = float(site["irrigation_cost_usd_per_acre_in"])
        # Rotation effects; the extra last row is "previous crop unknown" (no effect).
        self.rho, self.nu = np.ones((n + 1, n)), np.zeros((n + 1, n))
        for r in data["rotation_effects"].itertuples():
            if r.prev_crop in self.idx and r.crop in self.idx:
                self.rho[self.idx[r.prev_crop], self.idx[r.crop]] = r.yield_mult
                self.nu[self.idx[r.prev_crop], self.idx[r.crop]] = r.n_credit_lb
        self.years = self.sim.years
        rain = self.sim.season_rain
        self.pools = {"average": np.ones(len(rain), bool),
                      "dry": rain <= np.quantile(rain, DRY_SHARE)}
        self._tables = {}

    def pool(self, scenario):
        return self.pools["dry" if scenario == "dry" else "average"]

    def field_tables(self, field):
        """Season results for this field's soil and irrigation: arrays (crop, rye before, year)."""
        key = (self.sim.awc(field.get("soil")), _flag(field.get("irrigated")))
        if key not in self._tables:
            out = {k: np.zeros((len(self.crops), 2, len(self.years)))
                   for k in ("etc", "eta", "irrigation", "ratio")}
            for ci, crop in enumerate(self.crops):
                for rye in (0, 1):
                    s = self.sim.season(field.get("soil"), crop, rye, key[1])
                    for k in out:
                        out[k][ci, rye] = s[k]
            self._tables[key] = out
        return self._tables[key]

    def metrics(self, field, C, G):
        """Per-acre results of rotations on one field.
        C, G: int arrays (rotations, years) of crop index and rye-after flag.
        Returns arrays (rotations, years, weather years), plus soil (rotations, years).
        A rotation is a repeating cycle: year 1 follows the last year, so year 1's previous
        crop (and rye before it) is the last year's. Last season's actual crop only matters
        for the switch-over rule check, not the steady-state numbers."""
        tab = self.field_tables(field)
        prev = np.roll(C, 1, axis=1)
        rye_before = np.roll(G, 1, axis=1)
        ratio = tab["ratio"][C, rye_before]
        irr = tab["irrigation"][C, rye_before]
        yld = (self.base_yield[C] * self.rho[prev, C])[..., None] * ratio
        cost = (self.cost[C] - self.n_price * self.nu[prev, C] + self.rye_cost * G)[..., None]
        profit = self.price[C][..., None] * yld - cost - self.irr_cost * irr / MM_PER_IN
        return {
            "profit": profit,
            "need": tab["etc"][C, rye_before],
            "shortfall": tab["etc"][C, rye_before] - tab["eta"][C, rye_before],
            "irrigation": irr,
            "yield": yld,
            "soil": self.soil_points[C] + self.rye_points * G,
        }


# ---------------------------------------------------------------- solver choice

@functools.lru_cache(maxsize=1)
def _gurobi_env():
    """A quiet Gurobi environment, or None when gurobipy or a license is missing."""
    try:
        import gurobipy as gp
        env = gp.Env(empty=True)
        env.setParam("OutputFlag", 0)
        env.start()
        return env
    except Exception:
        return None


def pick_solver(name=None):
    """('gurobi', solver) when Gurobi is installed and licensed, else ('cbc', solver).
    The environment variable FIELD_SHIFT_SOLVER=gurobi|cbc forces one."""
    name = (name or os.environ.get("FIELD_SHIFT_SOLVER", "auto")).lower()
    if name in ("auto", "gurobi") and _gurobi_env() is not None:
        return "gurobi", pulp.GUROBI(msg=False, gapRel=GAP, timeLimit=TIME_LIMIT, env=_gurobi_env())
    return "cbc", pulp.PULP_CBC_CMD(msg=False, gapRel=GAP, timeLimit=TIME_LIMIT)


# ---------------------------------------------------------------- stage 1: candidate rotations

class Candidates:
    """Every rotation kept for one field, with its per-acre measures (per season)."""
    CHUNK = 64      # crop sequences per batch

    def __init__(self, prep, field, farm, constraints, prune=True):
        n, T = len(prep.crops), farm["years"]
        rule_set = {**constraints, "max_crop_share": 1}     # the acre cap is a farm-wide MILP row
        seqs = list(itertools.product(range(n), repeat=T))
        broken = [len(rule_problems({field["name"]: [prep.crops[i] for i in s]}, farm, rule_set))
                  for s in seqs]
        fewest = min(broken)                 # 0 when legal rotations exist; else the least-bad
        seqs = [s for s, b in zip(seqs, broken) if b == fewest]
        self.rules_met = fewest == 0

        wheat = prep.idx.get("winter_wheat")
        patterns = list(itertools.product((0, 1), repeat=T))
        parts = {k: [] for k in ("C", "G", "profit_y", "short_y", "irr_y", "soil", "prod_y")}
        self.n_before_pruning = 0
        # Built a few crop sequences at a time, so a 5-year search (up to 32,768 rotations
        # per field) never holds all its daily-weather arrays at once. Pruning compares rye
        # patterns within one crop sequence, so doing it chunk by chunk is still exact.
        for start in range(0, len(seqs), self.CHUNK):
            C, G = [], []
            for s in seqs[start:start + self.CHUNK]:
                for g in patterns:
                    # Rye can't go in right before winter wheat: their fall planting windows
                    # clash. The cycle wraps, so rye after the last year meets year 1.
                    if any(g[t] and s[(t + 1) % T] == wheat for t in range(T)):
                        continue
                    C.append(s)
                    G.append(g)
            C, G = np.array(C), np.array(G)
            m = prep.metrics(field, C, G)
            keep = self._undominated(C, m) if prune else np.ones(len(C), bool)
            self.n_before_pruning += len(C)
            # Averages per season over the cycle, so rotations of different lengths compare.
            parts["C"].append(C[keep])
            parts["G"].append(G[keep])
            parts["profit_y"].append(m["profit"].mean(1)[keep])        # (R, Y): $/acre per season
            parts["short_y"].append(m["shortfall"].mean(1)[keep])      # (R, Y): mm per season
            parts["irr_y"].append(m["irrigation"].mean(1)[keep])       # (R, Y): mm per season
            parts["soil"].append(m["soil"].mean(1)[keep])              # (R,): points per acre per season
            parts["prod_y"].append(np.stack([(m["yield"] * (C == c)[..., None]).mean(1)[keep]
                                             for c in range(n)], 1))   # (R, crops, Y): bu/acre per season
        for k, v in parts.items():
            setattr(self, k, np.concatenate(v))

    @staticmethod
    def _undominated(C, m):
        """Within one crop sequence every farm-wide row is identical, so a rye pattern that is
        no better on any measure (any year's profit, shortfall, irrigation, harvest, or soil)
        and worse on one can never be optimal for any goal or limit. Dropping it is exact."""
        feats = np.concatenate([
            m["profit"].sum(1), -m["shortfall"].sum(1), -m["irrigation"].sum(1),
            m["yield"].reshape(len(C), -1), m["soil"].sum(1, keepdims=True)], 1)
        keep = np.ones(len(C), bool)
        _, group = np.unique(C, axis=0, return_inverse=True)
        for g in np.unique(group):
            rows = np.flatnonzero(group == g)
            f = feats[rows]
            ge = (f[:, None, :] >= f[None, :, :] - 1e-9).all(2)    # ge[j, i]: j at least as good as i
            gt = (f[:, None, :] > f[None, :, :] + 1e-9).any(2)
            same = ge & ge.T
            earlier = np.arange(len(rows))[:, None] < np.arange(len(rows))[None, :]
            beaten = ((ge & gt) | (same & earlier)).any(0)
            keep[rows[beaten]] = False
        return keep


@functools.lru_cache(maxsize=256)
def _candidates_cached(prep_id, field_json, farm_json, rules_json):
    prep = _PREPARED[prep_id][1]
    return Candidates(prep, json.loads(field_json), json.loads(farm_json), json.loads(rules_json))


def _candidates(prep, farm, constraints):
    # Missing ground rules mean "no rule": any crop, repeats allowed, no soybean minimum.
    rules = {"allowed_crops": constraints.get("allowed_crops") or None,
             "no_repeat": bool(constraints.get("no_repeat")),
             "min_legume_years": int(constraints.get("min_legume_years") or 0)}
    farm_json = _dumps(farm)
    return [_candidates_cached(_prep_key(prep), _dumps(f), farm_json, _dumps(rules))
            for f in farm["fields"]]


def _prep_key(prep):
    return next(k for k, (_, p) in _PREPARED.items() if p is prep)


def _dumps(obj):
    return json.dumps(obj, sort_keys=True, default=lambda o: o.item() if hasattr(o, "item") else str(o))


# ---------------------------------------------------------------- farm-level measures

def _cvar(values, share):
    """Average of the worst `share` of values (fractional at the edge), as the MILP computes it."""
    v = np.sort(np.asarray(values, float))
    k = max(share * len(v), 1.0)
    full = int(np.floor(k))
    return (v[:full].sum() + (k - full) * (v[full] if full < len(v) else 0.0)) / k


def _summary(prep, farm, plan, covers, scenario, worst_share):
    """Farm-level measures of a plan, in the same units the MILP uses."""
    pool = prep.pool(scenario)
    total_acres = sum(float(f["acres"]) for f in farm["fields"])
    s = {"profit_y": 0.0, "short_y": 0.0, "irr_y": 0.0, "soil": 0.0,
         "prod_y": np.zeros((len(prep.crops), len(prep.years)))}
    for f in farm["fields"]:
        crops = plan[f["name"]]
        C = np.array([[prep.idx[c] for c in crops]])
        G = np.array([[int(_flag(x)) for x in (covers or {}).get(f["name"], [0] * len(crops))]])
        m = prep.metrics(f, C, G)
        a = float(f["acres"])
        T = len(crops)
        s["profit_y"] = s["profit_y"] + a * m["profit"][0].mean(0)
        s["short_y"] = s["short_y"] + a * m["shortfall"][0].mean(0) / MM_PER_IN
        s["irr_y"] = s["irr_y"] + a * m["irrigation"][0].mean(0) / MM_PER_IN
        s["soil"] += a * m["soil"][0].mean() / total_acres
        for t, ci in enumerate(C[0]):
            s["prod_y"][ci] += a * m["yield"][0, t] / T
    # Everything per season (per year of the repeating cycle), so lengths compare.
    return {
        "profit": s["profit_y"][pool].mean(),            # $ per season, scenario average
        "profit_y": s["profit_y"],                       # $ per season, if every season were year y
        "worst_profit": _cvar(s["profit_y"], worst_share),
        "shortfall": s["short_y"][pool].mean(),          # acre-inches per season
        "irrigation": s["irr_y"][pool].mean(),
        "irrigation_y": s["irr_y"][pool],                # acre-inches per season, each scenario year
        "water": s["short_y"][pool].mean() + s["irr_y"][pool].mean(),
        "soil": s["soil"],                               # points per acre per season
        "production": {c: s["prod_y"][i][pool].mean() for i, c in enumerate(prep.crops)},  # bu per season
    }


def _bounds(limits, prep, scenario):
    """Absolute limits -> the bounds the MILP rows use. Values are farm totals per season
    (per year of the cycle); None or missing means the limit is off."""
    b = {}
    for key, value in (limits or {}).items():
        if value is None:
            continue
        if key == "irrigation_max":      # applies in every season of the scenario
            b[key] = np.full(int(prep.pool(scenario).sum()), float(value))
        elif key == "production_min":
            b[key] = {c: float(v) for c, v in dict(value).items() if v and c in prep.idx}
        else:
            b[key] = float(value)
    return b


def limit_ranges(farm, data=None, scenario="average", constraints=None):
    """What this farm can reach on each limit's measure, per season: {name: (low, high)}, and
    for production_min {crop: (low, high)}. For slider ranges. Each end adds up, field by
    field, acres x the lowest / highest value among that field's candidate rotations (the
    ground rules and farm["years"] apply). It's an outer envelope: it ignores the acre cap,
    and bad-year profit adds per-field values. No solve needed; the candidates are cached."""
    prep = _prep(data)
    constraints = dict(constraints or {})
    pool = prep.pool(scenario)
    worst = float(constraints.get("worst_share") or WORST_SHARE)
    total = sum(float(f["acres"]) for f in farm["fields"])
    lo, hi = {}, {}

    def add(key, a, values):
        lo[key] = lo.get(key, 0.0) + a * float(np.min(values))
        hi[key] = hi.get(key, 0.0) + a * float(np.max(values))

    prod = {}
    for f, c in zip(farm["fields"], _candidates(prep, farm, constraints)):
        a = float(f["acres"])
        add("profit_min", a, c.profit_y[:, pool].mean(1))
        add("worst_profit_min", a, [_cvar(row, worst) for row in c.profit_y])
        add("shortfall_max", a, c.short_y[:, pool].mean(1) / MM_PER_IN)
        add("irrigation_max", a, c.irr_y[:, pool].max(1) / MM_PER_IN)
        add("soil_min", a / total, c.soil)
        for ci, crop in enumerate(prep.crops):
            p_lo, p_hi = prod.get(crop, (0.0, 0.0))
            col = c.prod_y[:, ci][:, pool].mean(1)
            prod[crop] = (p_lo + a * float(col.min()), p_hi + a * float(col.max()))
    out = {k: (lo[k], hi[k]) for k in lo}
    allowed = constraints.get("allowed_crops") or prep.crops
    out["production_min"] = {crop: r for crop, r in prod.items() if crop in allowed and r[1] > 0}
    return out


# ---------------------------------------------------------------- stage 2: the MILP

def _optimize(prep, farm, cands, goal, scenario, bounds, cap_share, worst_share, solver_name):
    """Pick one rotation per field. Returns (choice index per field, status).
    Limits and acre caps are hard first; if that is infeasible, a second pass finds the
    smallest total (relative) violation and a third optimizes the goal within it."""
    pool = prep.pool(scenario)
    acres = [float(f["acres"]) for f in farm["fields"]]
    total = sum(acres)
    T = farm["years"]

    def build(mode, violation_cap=None):
        sense = pulp.LpMinimize if (mode == "violation" or goal == "min_water") else pulp.LpMaximize
        m = pulp.LpProblem("field_shift", sense)
        y = [[pulp.LpVariable(f"y_{z}_{r}", cat="Binary") for r in range(len(c.C))]
             for z, c in enumerate(cands)]
        slacks = []

        def expr(coefs):
            """Sum over fields and rotations of acres * per-acre coefficient * y."""
            return pulp.LpAffineExpression(
                [(y[z][r], acres[z] * float(v)) for z, c in enumerate(cands)
                 for r, v in enumerate(coefs(c)) if v])

        def row(lhs, bound, at_most, scale):
            if mode == "hard":
                m.addConstraint(lhs <= bound if at_most else lhs >= bound)
            else:
                s = pulp.LpVariable(f"s_{len(slacks)}", lowBound=0)
                slacks.append((s, max(abs(scale), 1.0)))
                m.addConstraint(lhs - s <= bound if at_most else lhs + s >= bound)

        for z in range(len(cands)):                              # one rotation per field
            m.addConstraint(pulp.lpSum(y[z]) == 1)
        if cap_share < 1:                                        # acre cap per crop, every year
            for ci in range(len(prep.crops)):
                for t in range(T):
                    row(expr(lambda c: (c.C[:, t] == ci).astype(float)), cap_share * total,
                        True, cap_share * total)

        def cvar_expr():
            eta = pulp.LpVariable("eta")
            n = len(prep.years)
            u = [pulp.LpVariable(f"u_{w}", lowBound=0) for w in range(n)]
            for w in range(n):
                m.addConstraint(u[w] >= eta - expr(lambda c: c.profit_y[:, w]))
            return eta - (1.0 / (max(worst_share * n, 1.0))) * pulp.lpSum(u)

        mean = lambda a: a[:, pool].mean(1)                     # noqa: E731
        if "profit_min" in bounds:
            row(expr(lambda c: mean(c.profit_y)), bounds["profit_min"], False, bounds["profit_min"])
        if "shortfall_max" in bounds:
            row(expr(lambda c: mean(c.short_y) / MM_PER_IN), bounds["shortfall_max"], True,
                bounds["shortfall_max"])
        if "irrigation_max" in bounds and any(_flag(f.get("irrigated")) for f in farm["fields"]):
            for k, w in enumerate(np.flatnonzero(pool)):
                b = float(bounds["irrigation_max"][k])
                row(expr(lambda c: c.irr_y[:, w] / MM_PER_IN), b, True, b)
        if "soil_min" in bounds:
            row(expr(lambda c: c.soil / total), bounds["soil_min"], False, bounds["soil_min"])
        for crop, b in bounds.get("production_min", {}).items():
            ci = prep.idx[crop]
            row(expr(lambda c: mean(c.prod_y[:, ci])), b, False, b)
        cvar = None
        if "worst_profit_min" in bounds or goal == "max_worst_profit":
            cvar = cvar_expr()
            if "worst_profit_min" in bounds:
                row(cvar, bounds["worst_profit_min"], False, bounds["worst_profit_min"])

        goal_expr = {
            "max_profit": lambda: expr(lambda c: mean(c.profit_y)),
            "min_water": lambda: expr(lambda c: (mean(c.short_y) + mean(c.irr_y)) / MM_PER_IN),
            "max_worst_profit": lambda: cvar,
            "max_soil": lambda: expr(lambda c: c.soil / total),
        }[goal]()
        # Tie-break, used in a second pass: among plans equally good on the goal, prefer the
        # most profitable (or, when the goal is profit, the one needing the least water).
        water = expr(lambda c: (mean(c.short_y) + mean(c.irr_y)) / MM_PER_IN)
        profit = expr(lambda c: mean(c.profit_y))
        tiebreak = -water if goal == "max_profit" else (-profit if goal == "min_water" else profit)
        violation = pulp.lpSum(s * (1.0 / scale) for s, scale in slacks)
        if mode == "violation":
            m.setObjective(violation)
        else:
            m.setObjective(goal_expr)
            if violation_cap is not None:
                m.addConstraint(violation <= violation_cap)
        return m, y, violation, goal_expr, tiebreak

    timed_out = []

    def run(m):
        # A fresh solver object every time: PuLP's GUROBI object keeps reporting "Infeasible"
        # for every later model once one model was infeasible (seen with PuLP 3.3.2).
        m.solve(pick_solver(solver_name)[1])
        if m.status == 1 and m.sol_status == pulp.LpSolutionIntegerFeasible:
            timed_out.append(True)     # stopped at TIME_LIMIT with a good, maybe not best, plan
        return pulp.LpStatus[m.status]

    m, y, _, goal_expr, tiebreak = build("hard")
    status = run(m)
    if status != "Optimal":
        m, y, violation, _, _ = build("violation")
        run(m)
        cap = (pulp.value(violation) or 0.0) * (1 + 1e-6) + 1e-7
        m, y, _, goal_expr, tiebreak = build("soft", violation_cap=cap)
        status = "Relaxed" if run(m) == "Optimal" else "Failed"
    if status != "Failed":
        best = pulp.value(goal_expr)
        tol = 1e-6 * abs(best) + 1e-6
        if m.sense == pulp.LpMaximize:
            m.addConstraint(goal_expr >= best - tol)
        else:
            m.addConstraint(goal_expr <= best + tol)
        m.setObjective(tiebreak)
        if run(m) != "Optimal":            # keep the first-pass answer if the tie-break trips
            m.setObjective(goal_expr)
            run(m)
    choice = [int(np.argmax([v.value() or 0 for v in yz])) for yz in y]
    if timed_out and status == "Optimal":
        status = "Time limit"
    return choice, status


# ---------------------------------------------------------------- contract functions

def _scenario_rows(prep, farm, plan, covers, scenario):
    """One row per field per year: the contract's PLAN_COLUMNS plus cover and irrigation."""
    pool = prep.pool(scenario)
    rows = []
    for f in farm["fields"]:
        crops = plan[f["name"]]
        cov = [int(_flag(x)) for x in (covers or {}).get(f["name"], [0] * len(crops))]
        m = prep.metrics(f, np.array([[prep.idx[c] for c in crops]]), np.array([cov]))
        a = float(f["acres"])
        for t, crop in enumerate(crops):
            rows.append({
                "field": f["name"], "year": t + 1, "crop": crop, "acres": f["acres"],
                "water_need_mm": round(float(m["need"][0, t, pool].mean()), 1),
                "water_shortfall_mm": round(float(m["shortfall"][0, t, pool].mean()), 1),
                "soil_score_change": round(float(m["soil"][0, t]), 2),
                "profit_usd": round(a * float(m["profit"][0, t, pool].mean())),
                "cover": bool(cov[t]),
                "irrigation_mm": round(float(m["irrigation"][0, t, pool].mean()), 1),
            })
    return pd.DataFrame(rows, columns=PLAN_COLUMNS + ["cover", "irrigation_mm"])


def _check_plan(prep, farm, plan):
    names = [f["name"] for f in farm["fields"]]
    if list(plan) != names and set(plan) != set(names):
        raise ValueError(f"plan fields {list(plan)} don't match the farm's fields {names}")
    lengths = {len(crops) for crops in plan.values()}
    if len(lengths) > 1:
        raise ValueError(f"every field needs the same rotation length; got {sorted(lengths)}")
    for field, crops in plan.items():
        if len(crops) < 1:
            raise ValueError(f"{field} has an empty rotation")
        unknown = [c for c in crops if c not in prep.idx]
        if unknown:
            raise ValueError(f"{field}: unknown crop(s) {unknown}; known: {prep.crops}")


def evaluate(plan, farm, data=None, scenario="average", covers=None):
    """Score a plan {field: [crop per year]}. covers {field: [rye after year t?]}; None = no rye.
    Values are averages over the scenario's weather years."""
    prep = _prep(data)
    _check_plan(prep, farm, plan)
    return _scenario_rows(prep, farm, plan, covers, scenario)


_SOLVE_CACHE = {}


def solve(farm, data=None, goal="max_profit", scenario="average", constraints=None):
    """The best plan for ONE goal (a key of contract.GOALS) under the ground rules and limits.

    constraints: the ground rules (contract.CONSTRAINTS keys) plus optional
        limits       absolute values, farm totals per season (None/missing = off):
                       profit_min $/yr, worst_profit_min $/yr (average of the worst seasons),
                       shortfall_max acre-in/yr, irrigation_max acre-in in every season,
                       soil_min points per acre per year, production_min {crop: bu/yr}.
                     No limits by default; limit_ranges() gives sensible ranges.
        worst_share  share of seasons counted as "bad years" (default contract.WORST_SHARE)
    Returns evaluate()'s table for the chosen plan and rye covers, with table.attrs:
        goal, solver, status ("Optimal", "Relaxed", or "Time limit"), unmet (plain sentences).
    The rotation length searched is farm["years"] (2-5). Rotations repeat (year 1 follows
    the last year) and every measure is per season.
    """
    if isinstance(goal, dict):
        raise TypeError(f"solve() takes a goal name now, not weights: one of {list(GOALS)}")
    if goal not in GOALS:
        raise ValueError(f"unknown goal {goal!r}; pick one of {list(GOALS)}")
    constraints = dict(constraints or {})
    prep = _prep(data)
    solver_name, _ = pick_solver()

    limits = {k: v for k, v in (constraints.get("limits") or {}).items() if v is not None}
    for key in GOAL_OWN_LIMITS[goal]:
        limits.pop(key, None)
    worst_share = float(constraints.get("worst_share") or WORST_SHARE)
    cap_share = float(constraints.get("max_crop_share", 1) or 1)

    rules = {k: v for k, v in constraints.items() if k not in ("limits", "reference_plan")}
    key = _dumps([_prep_key(prep), farm, goal, scenario, rules, limits, solver_name])
    if key not in _SOLVE_CACHE:
        bounds = _bounds(limits, prep, scenario)
        cands = _candidates(prep, farm, constraints)
        choice, status = _optimize(prep, farm, cands, goal, scenario, bounds, cap_share,
                                   worst_share, solver_name)
        plan = {f["name"]: [prep.crops[i] for i in c.C[k]]
                for f, c, k in zip(farm["fields"], cands, choice)}
        covers = {f["name"]: [bool(x) for x in c.G[k]]
                  for f, c, k in zip(farm["fields"], cands, choice)}
        got = _summary(prep, farm, plan, covers, scenario, worst_share)
        table = _scenario_rows(prep, farm, plan, covers, scenario)
        table.attrs.update(goal=goal, solver=solver_name, status=status,
                           unmet=_unmet(bounds, got))
        if len(_SOLVE_CACHE) > 64:
            _SOLVE_CACHE.clear()
        _SOLVE_CACHE[key] = table
    table = _SOLVE_CACHE[key].copy()
    table.attrs = dict(_SOLVE_CACHE[key].attrs)
    return table


def _unmet(bounds, got):
    """Plain sentences for limits the chosen plan does not meet (all per year)."""
    def money(v):
        return f"{'−' if v < 0 else ''}${abs(v):,.0f}"

    out = []
    for key, b in bounds.items():
        label = LIMIT_LABELS[key]
        tol = 1e-6 * (abs(np.max(b)) + 1) if not isinstance(b, dict) else 0
        if key == "profit_min" and got["profit"] < b - tol:
            out.append(f"{label} {money(b)} a year: the best plan found earns {money(got['profit'])}.")
        elif key == "worst_profit_min" and got["worst_profit"] < b - tol:
            out.append(f"{label} {money(b)} a year: the best plan found makes "
                       f"{money(got['worst_profit'])} in bad years.")
        elif key == "shortfall_max" and got["shortfall"] > b + tol:
            out.append(f"{label} {b:,.0f} acre-in a year: the best plan found runs "
                       f"{got['shortfall']:,.0f} acre-in short.")
        elif key == "irrigation_max" and np.any(got["irrigation_y"] > b + tol):
            n = int(np.sum(got["irrigation_y"] > b + tol))
            out.append(f"{label} {float(np.max(b)):,.0f} acre-in: the best plan found pumps more "
                       f"in {n} season{'s' if n > 1 else ''}.")
        elif key == "soil_min" and got["soil"] < b - tol:
            out.append(f"{label} {b:+.2f} a year: the best plan found scores {got['soil']:+.2f}.")
        elif key == "production_min":
            for crop, bc in b.items():
                if got["production"][crop] < bc - 1e-6 * (bc + 1):
                    out.append(f"{label} {bc:,.0f} bu of {crop.replace('_', ' ')} a year: the "
                               f"best plan found harvests {got['production'][crop]:,.0f} bu.")
    return out


def solve_pareto(farm, data=None, scenario="average", constraints=None, n=9):
    """Trade-off plans between profit and water (epsilon-constraint sweep): minimize water
    with a profit floor stepped from the least-water plan's profit up to the best profit."""
    constraints = {k: v for k, v in (constraints or {}).items() if k != "limits"}
    prep = _prep(data)
    solver, _ = pick_solver()
    cands = _candidates(prep, farm, constraints)
    cap = float(constraints.get("max_crop_share", 1) or 1)
    ws = float(constraints.get("worst_share") or WORST_SHARE)

    def plan_of(choice):
        plan = {f["name"]: [prep.crops[i] for i in c.C[k]] for f, c, k in zip(farm["fields"], cands, choice)}
        covers = {f["name"]: [bool(x) for x in c.G[k]] for f, c, k in zip(farm["fields"], cands, choice)}
        return plan, covers

    hi = _summary(prep, farm, *plan_of(_optimize(prep, farm, cands, "max_profit", scenario, {},
                                                 cap, ws, solver)[0]), scenario, ws)["profit"]
    lo = _summary(prep, farm, *plan_of(_optimize(prep, farm, cands, "min_water", scenario, {},
                                                 cap, ws, solver)[0]), scenario, ws)["profit"]
    options, seen = [], set()
    for floor in np.linspace(lo, hi, n):
        choice, _ = _optimize(prep, farm, cands, "min_water", scenario,
                              {"profit_min": floor - 1e-6 * abs(floor)}, cap, ws, solver)
        plan, covers = plan_of(choice)
        tag = _dumps([plan, covers])
        if tag in seen:
            continue
        seen.add(tag)
        s = _summary(prep, farm, plan, covers, scenario, ws)
        options.append({
            "total_profit_usd": int(round(s["profit"])),
            "total_shortfall_acre_in": round(float(s["shortfall"]), 1),
            "total_irrigation_acre_in": round(float(s["irrigation"]), 1),
            "soil_score_change": round(float(s["soil"]), 2),
            "plan": _scenario_rows(prep, farm, plan, covers, scenario),
        })
    return options


def backtest(plan, farm, data=None, covers=None):
    """The plan against every historical year: one row per weather year, as if every season
    of the rotation had that year's weather (values per season, averaged over the cycle)."""
    prep = _prep(data)
    _check_plan(prep, farm, plan)
    total_acres = sum(float(f["acres"]) for f in farm["fields"])
    T = len(next(iter(plan.values())))
    profit = short = irr = soil = 0.0
    for f in farm["fields"]:
        crops = plan[f["name"]]
        cov = [int(_flag(x)) for x in (covers or {}).get(f["name"], [0] * len(crops))]
        m = prep.metrics(f, np.array([[prep.idx[c] for c in crops]]), np.array([cov]))
        a = float(f["acres"])
        profit = profit + a * m["profit"][0].sum(0) / T
        short = short + a * m["shortfall"][0].sum(0) / T / MM_PER_IN
        irr = irr + a * m["irrigation"][0].sum(0) / T / MM_PER_IN
        soil += a * m["soil"][0].sum() / T / total_acres
    return pd.DataFrame({
        "year": prep.years,
        "growing_season_rain_mm": prep.sim.season_rain.round(0),
        "total_profit_usd": np.round(profit).astype(int),
        "total_shortfall_acre_in": np.round(short, 1),
        "soil_score_change": round(float(soil), 2),
        "total_irrigation_acre_in": np.round(irr, 1),
    }, columns=BACKTEST_COLUMNS + ["total_irrigation_acre_in"])


def table_to_plan(table):
    """Convert a plan table back to {field: [crop per year]}."""
    return {f: list(g.sort_values("year")["crop"]) for f, g in table.groupby("field", sort=False)}


def table_to_covers(table):
    """Rye choices from a plan table: {field: [rye after year t?]}, or None if it has none."""
    if "cover" not in table:
        return None
    return {f: [bool(x) for x in g.sort_values("year")["cover"]]
            for f, g in table.groupby("field", sort=False)}


__all__ = ["evaluate", "solve", "solve_pareto", "backtest", "table_to_plan", "table_to_covers",
           "baseline_plan", "pick_solver", "limit_ranges"]
