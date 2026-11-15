"""Field Shift check-up. Run it whenever the model or the data changes:

    source .venv/bin/activate
    python test_app.py            # tests whichever model app.py imports
    python test_app.py model      # force the real model.py
    python test_app.py fake_model # force the stand-in

Part 1 checks the model against the interface contract in contract.py.
Part 2 loads the whole page (typical and dry year) the way a browser would and
checks every section appears, with no errors. Prints a checklist; exit code 1 if
anything failed, so it can gate a deploy.
"""
import importlib
import sys
import traceback

import pandas as pd

from contract import (BACKTEST_COLUMNS, CONSTRAINTS, CROPS, FARM, FIRST_YEAR, LAST_YEAR,
                      PARETO_KEYS, PLAN_COLUMNS, WEIGHTS, baseline_plan, normalize_weights)
from rules import rule_problems

results = []


def check(name, fn):
    """Run one check, record ✓ or ✗ with the reason."""
    try:
        detail = fn()
        results.append((True, name, detail or ""))
    except Exception as e:  # noqa: BLE001 - we want every failure reported, not the first
        results.append((False, name, f"{type(e).__name__}: {e}"))


# ---------------------------------------------------------------- which model
def which_model():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for line in open("app.py", encoding="utf-8"):
        if line.startswith("import ") and " as model" in line:
            return line.split()[1]
    return "fake_model"


MODEL_NAME = which_model()
model = importlib.import_module(MODEL_NAME)
farm = dict(FARM)
plan0 = baseline_plan(farm)
n_cells = len(farm["fields"]) * farm["years"]


# ---------------------------------------------------------------- part 1: contract
def c_functions():
    missing = [f for f in ("evaluate", "solve", "solve_pareto", "backtest", "table_to_plan")
               if not callable(getattr(model, f, None))]
    assert not missing, f"missing functions: {missing}"


def c_evaluate():
    t = model.evaluate(plan0, farm, None, "average")
    assert isinstance(t, pd.DataFrame), "evaluate must return a DataFrame"
    assert list(t.columns) == PLAN_COLUMNS, f"columns {list(t.columns)} != PLAN_COLUMNS"
    assert len(t) == n_cells, f"{len(t)} rows, expected {n_cells} (fields × years)"
    assert set(t["crop"]) <= set(CROPS), f"unknown crops: {set(t['crop']) - set(CROPS)}"
    assert t[["profit_usd", "water_shortfall_mm", "soil_score_change"]].notna().all().all(), "NaN in numbers"
    assert (t["water_shortfall_mm"] >= 0).all(), "water shortfall must be >= 0"
    return f"{len(t)} rows, profit ${t['profit_usd'].sum():,.0f}"


def c_evaluate_dry():
    a = model.evaluate(plan0, farm, None, "average")
    d = model.evaluate(plan0, farm, None, "dry")
    assert list(d.columns) == PLAN_COLUMNS
    assert d["water_shortfall_mm"].sum() >= a["water_shortfall_mm"].sum(), \
        "a dry year should not have LESS water shortfall than an average one"
    return f"shortfall avg {a['water_shortfall_mm'].sum():.0f} mm vs dry {d['water_shortfall_mm'].sum():.0f} mm"


def c_solve():
    t = model.solve(farm, None, normalize_weights(WEIGHTS), "average", CONSTRAINTS)
    assert isinstance(t, pd.DataFrame) and list(t.columns) == PLAN_COLUMNS
    assert len(t) == n_cells
    plan = model.table_to_plan(t)
    assert set(plan) == {f["name"] for f in farm["fields"]}, "plan must cover every field"
    assert all(len(c) == farm["years"] for c in plan.values()), "each field needs one crop per year"
    problems = rule_problems(plan, farm, CONSTRAINTS)
    return "meets all default ground rules" if not problems else f"NOTE: breaks {len(problems)} rule(s): {problems[0]}"


def c_solve_allowed():
    cons = {**CONSTRAINTS, "allowed_crops": ["corn", "soybeans"], "no_repeat": True}
    plan = model.table_to_plan(model.solve(farm, None, normalize_weights(WEIGHTS), "average", cons))
    used = {c for crops in plan.values() for c in crops}
    assert used <= {"corn", "soybeans"}, f"used crops outside the allowed list: {used}"


def c_solve_weights():
    """Different priorities should (usually) give different plans."""
    p1 = model.table_to_plan(model.solve(farm, None, {"profit": 1, "water": 0, "soil": 0}, "average", CONSTRAINTS))
    p2 = model.table_to_plan(model.solve(farm, None, {"profit": 0, "water": 1, "soil": 0}, "average", CONSTRAINTS))
    return "profit-first and water-first plans differ" if p1 != p2 else "NOTE: same plan for both; fine if the rules force it"


def c_backtest():
    t = model.backtest(plan0, farm, None)
    assert isinstance(t, pd.DataFrame) and list(t.columns) == BACKTEST_COLUMNS, f"columns {list(t.columns)}"
    years = list(t["year"])
    assert years == list(range(FIRST_YEAR, LAST_YEAR + 1)), f"years {years[0]}..{years[-1]}, {len(years)} rows"
    assert t.notna().all().all(), "NaN in backtest"
    assert (t["growing_season_rain_mm"] > 0).all(), "rain must be positive"
    return f"{len(t)} seasons, driest {int(t.loc[t['growing_season_rain_mm'].idxmin(), 'year'])}"


def c_pareto():
    opts = model.solve_pareto(farm, None, "average", CONSTRAINTS)
    assert isinstance(opts, list) and opts, "solve_pareto must return a non-empty list"
    for o in opts:
        assert set(PARETO_KEYS) <= set(o), f"option keys {list(o)} missing {set(PARETO_KEYS) - set(o)}"
        plan = o["plan"]
        plan = model.table_to_plan(plan) if hasattr(plan, "groupby") else plan
        assert set(plan) == {f["name"] for f in farm["fields"]}
    return f"{len(opts)} options"


def c_table_to_plan():
    t = model.evaluate(plan0, farm, None, "average")
    assert model.table_to_plan(t) == plan0, "evaluate -> table_to_plan must give the plan back"


def c_speed():
    import time
    t0 = time.time()
    model.solve(farm, None, normalize_weights(WEIGHTS), "dry", CONSTRAINTS)
    model.solve_pareto(farm, None, "dry", CONSTRAINTS)
    model.backtest(plan0, farm, None)
    dt = time.time() - t0
    assert dt < 20, f"{dt:.1f}s for solve + solve_pareto + backtest: too slow for a live demo"
    return f"solve + pareto + backtest in {dt:.1f}s"


# ---------------------------------------------------------------- part 2: the page
def load_page(**state):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app.py", default_timeout=180)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    errors = [e.value for e in at.exception] + [e.value for e in at.error]
    assert not errors, errors[0]
    return at


def p_sections(at):
    titles = [h.value for h in at.subheader]
    for want in ("What you plan to plant", "Recommended plan", "How it holds up", "Other good plans"):
        assert any(want in t for t in titles), f"section '{want}' missing; have {titles}"
    assert len(at.get("plotly_chart")) == 3, f"{len(at.get('plotly_chart'))} charts, expected 3"
    assert len(at.metric) == 3, f"{len(at.metric)} metric cards, expected 3"


def p_typical():
    at = load_page(scenario="average")
    p_sections(at)
    assert any("typical year" in h.value for h in at.subheader), "recommendation title should say 'typical year'"


def p_dry():
    at = load_page(scenario="dry")
    p_sections(at)
    assert any("dry year" in h.value for h in at.subheader), "recommendation title should say 'dry year'"


def p_tradeoffs():
    at = load_page()
    sb = [s for s in at.selectbox if s.label == "Look at an option"]
    assert sb, "trade-off picker missing"
    assert len(sb[0].options) >= 2, f"only {len(sb[0].options)} trade-off option(s)"
    return f"{len(sb[0].options)} options in the picker"


def p_apply():
    """A recommendation copied into Your rotation shows up in the tiles and the caption."""
    alt = {f["name"]: ["winter_wheat", "sorghum", "corn", "soybeans"][: farm["years"]] for f in farm["fields"]}
    at = load_page(applied_plan=alt, editor_version=1)
    caps = " ".join(c.value for c in at.caption)
    assert "now the recommendation" in caps, "caption should say the rotation is the applied recommendation"
    md = " ".join(m.value for m in at.markdown)
    assert "Sorghum" in md and "Winter wheat" in md, "applied crops not shown in the tiles"


def p_one_crop():
    at = load_page(allowed_crops=["corn"], scenario="average")
    p_sections(at)
    md = " ".join(m.value for m in at.markdown)
    warn = " ".join(w.value for w in at.warning)
    assert "Corn" in md
    return "page survives a one-crop ground rule" + (" (rule warning shown)" if warn else "")


def p_assistant():
    at = load_page(faq_history=[{"role": "user", "content": "How did the recommendation do?"}], faq_pending=True)
    h = at.session_state["faq_history"]
    assert len(h) == 2 and h[1]["role"] == "assistant" and "seasons" in h[1]["content"], h[-1]["content"][:80]
    return "quick answer uses the live numbers"


# ---------------------------------------------------------------- run
if __name__ == "__main__":
    print(f"Field Shift check-up · model under test: {MODEL_NAME}.py\n")
    for name, fn in [("functions present", c_functions), ("evaluate()", c_evaluate),
                     ("evaluate(): dry year", c_evaluate_dry), ("solve()", c_solve),
                     ("solve(): respects allowed crops", c_solve_allowed),
                     ("solve(): reacts to priorities", c_solve_weights), ("backtest()", c_backtest),
                     ("solve_pareto()", c_pareto), ("table_to_plan()", c_table_to_plan),
                     ("speed", c_speed)]:
        check(name, fn)
    n1 = len(results)
    for name, fn in [("typical year", p_typical), ("dry year", p_dry), ("trade-off picker", p_tradeoffs),
                     ("apply a recommendation", p_apply), ("one-crop ground rule", p_one_crop),
                     ("assistant", p_assistant)]:
        check(name, fn)

    for i, (ok, name, detail) in enumerate(results):
        if i == 0:
            print("Part 1 · model vs interface contract")
        if i == n1:
            print("\nPart 2 · the page")
        print(f"  {'✓' if ok else '✗'} {name}" + (f"  · {detail}" if detail else ""))
    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    sys.exit(1 if failed else 0)
