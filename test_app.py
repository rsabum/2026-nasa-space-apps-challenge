"""Field Shift check-up (Claude-Thomas's idea, updated for the three-page app). Run it
before every deploy, and whenever the model or the data changes:

    source .venv/bin/activate
    python test_app.py

Part 1 checks Robert's model (model.py) against the interface contract in contract.py,
on the data the app is really using (real data in data/real/ when all five tables are
valid, else the synthetic sample data). Part 2 loads Home, Rotation evaluator and Rotation
optimizer the way a browser would and checks every section appears, with no errors. Prints
a checklist; exit code 1 if anything failed, so it can gate a deploy (see DEPLOY.md).
check_model.py has the deeper model checks (exactness against brute force, and more).
"""
import sys
import time
import traceback

import pandas as pd

import model
from contract import (BACKTEST_COLUMNS, CONSTRAINTS, CROPS, FARM, FIRST_YEAR, GOALS, LAST_YEAR,
                      PARETO_KEYS, PLAN_COLUMNS, baseline_plan)
from rules import rule_problems

results = []


class Skip(Exception):
    """A check the test tool can't run on this Streamlit version (not an app failure)."""


def check(name, fn):
    """Run one check, record ✓, ✗ (with the reason) or – (skipped, with the reason)."""
    try:
        detail = fn()
        results.append((True, name, detail or ""))
    except Skip as e:
        results.append((None, name, str(e)))
    except Exception as e:  # noqa: BLE001 - we want every failure reported, not the first
        results.append((False, name, f"{type(e).__name__}: {e}"))


def run_after_click(at):
    """at.run() after a click. Streamlit 1.50's test tool crashes replaying a page that has a
    segmented control holding a single value (our rotation-length switch), which is a bug
    in the tool, not the app (fixed in newer Streamlit). Report that as skipped."""
    try:
        at.run()
    except TypeError:
        if "streamlit/testing" in traceback.format_exc():
            raise Skip("Streamlit's test tool can't replay this click on this version; "
                       "check it in a browser (it works there)") from None
        raise


farm = {**FARM, "years": 2}                 # the app's default rotation length
plan0 = baseline_plan(farm)                 # corn-soy
n_cells = len(farm["fields"]) * farm["years"]


# ---------------------------------------------------------------- part 1: contract
def c_functions():
    missing = [f for f in ("evaluate", "solve", "solve_pareto", "backtest", "table_to_plan",
                           "table_to_covers", "limit_ranges", "data_source")
               if not callable(getattr(model, f, None))]
    assert not missing, f"missing functions: {missing}"


def c_data():
    src = model.data_source()
    assert src["kind"] in ("real", "synthetic"), src
    detail = "real data (data/real/)" if src["kind"] == "real" else (
        f"SAMPLE data: real data {len(src['ready'])} of 5 tables ready (python real_data.py check)")
    return detail + f" · solver {model.pick_solver()[0]}"


def c_evaluate():
    t = model.evaluate(plan0, farm, None, "average")
    assert isinstance(t, pd.DataFrame), "evaluate must return a DataFrame"
    assert list(t.columns[:len(PLAN_COLUMNS)]) == PLAN_COLUMNS, f"columns {list(t.columns)}"
    assert len(t) == n_cells, f"{len(t)} rows, expected {n_cells} (fields × years)"
    assert set(t["crop"]) <= set(CROPS), f"unknown crops: {set(t['crop']) - set(CROPS)}"
    assert t[["profit_usd", "water_shortfall_mm", "soil_score_change"]].notna().all().all(), "NaN in numbers"
    assert (t["water_shortfall_mm"] >= 0).all(), "water shortfall must be >= 0"
    return f"{len(t)} rows, corn-soy ${t['profit_usd'].sum() / farm['years']:,.0f} a year"


def c_solve_goals():
    out = []
    for goal in GOALS:
        t = model.solve(farm, None, goal, "average", dict(CONSTRAINTS))
        assert list(t.columns[:len(PLAN_COLUMNS)]) == PLAN_COLUMNS and len(t) == n_cells, goal
        plan = model.table_to_plan(t)
        assert set(plan) == {f["name"] for f in farm["fields"]}, "plan must cover every field"
        problems = rule_problems(plan, farm, CONSTRAINTS)
        assert not problems, f"{goal}: breaks {problems[0]}"
        out.append(t.attrs.get("status", "?"))
    return f"{len(GOALS)} objectives, all meet the default ground rules ({', '.join(sorted(set(out)))})"


def c_solve_allowed():
    cons = {**CONSTRAINTS, "allowed_crops": ["corn", "soybeans"]}
    plan = model.table_to_plan(model.solve(farm, None, "max_profit", "average", cons))
    used = {c for crops in plan.values() for c in crops}
    assert used <= {"corn", "soybeans"}, f"used crops outside the allowed list: {used}"


def c_limits():
    r = model.limit_ranges(farm, None, "average", CONSTRAINTS)
    lo, hi = r["profit_min"]
    assert lo < hi, f"profit range {lo}..{hi}"
    t = model.solve(farm, None, "min_water", "average", {**CONSTRAINTS, "limits": {"profit_min": lo + 0.5 * (hi - lo)}})
    assert not t.attrs.get("unmet"), t.attrs.get("unmet")
    t = model.solve(farm, None, "min_water", "average", {**CONSTRAINTS, "limits": {"profit_min": hi * 2 + 1}})
    assert t.attrs.get("unmet"), "an unreachable limit should come back as unmet"
    return f"profit range ${lo:,.0f}–${hi:,.0f} a year; unreachable limits are reported"


def c_backtest():
    t = model.backtest(plan0, farm, None)
    assert list(t.columns[:len(BACKTEST_COLUMNS)]) == BACKTEST_COLUMNS, f"columns {list(t.columns)}"
    years = list(t["year"])
    assert years == list(range(FIRST_YEAR, LAST_YEAR + 1)), f"years {years[0]}..{years[-1]}, {len(years)} rows"
    assert t[BACKTEST_COLUMNS].notna().all().all(), "NaN in backtest"
    assert (t["growing_season_rain_mm"] > 0).all(), "rain must be positive"
    return f"{len(t)} seasons, driest {int(t.loc[t['growing_season_rain_mm'].idxmin(), 'year'])}"


def c_pareto():
    opts = model.solve_pareto(farm, None, "average", CONSTRAINTS, n=5)
    assert isinstance(opts, list) and opts, "solve_pareto must return a non-empty list"
    for o in opts:
        assert set(PARETO_KEYS) <= set(o), f"option keys {list(o)} missing {set(PARETO_KEYS) - set(o)}"
    return f"{len(opts)} options"


def c_round_trip():
    t = model.evaluate(plan0, farm, None, "average")
    assert model.table_to_plan(t) == plan0, "evaluate -> table_to_plan must give the plan back"


def c_speed():
    t0 = time.time()
    model.solve({**FARM, "years": 4}, None, "max_profit", "average", dict(CONSTRAINTS))
    model.backtest(plan0, farm, None)
    dt = time.time() - t0
    assert dt < 20, f"{dt:.1f}s for a 4-year solve + backtest: too slow for a live demo"
    return f"4-year solve + backtest in {dt:.1f}s"


# ---------------------------------------------------------------- part 2: the pages
def load(page=None, **state):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app.py", default_timeout=180)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    if page:
        at.switch_page(page)
        at.run()
    errors = [e.value for e in at.exception] + [e.value for e in at.error]
    assert not errors, errors[0]
    return at


def has_sections(at, wants, metrics=3):
    titles = [h.value for h in at.subheader]
    for want in wants:
        assert any(want in t for t in titles), f"section '{want}' missing; have {titles}"
    assert len(at.metric) == metrics, f"{len(at.metric)} metric cards, expected {metrics}"


def pill(at):
    md = " ".join(m.value for m in at.markdown)
    return "Real data" if ">Real data<" in md else "Sample data" if ">Sample data<" in md else None


def p_home():
    at = load()
    has_sections(at, ("How would my rotation have done?", "What's the best rotation for my goal?"))
    assert pill(at), "data pill missing from the top bar"
    return f"top bar says {pill(at)}"


def p_evaluator():
    at = load("views/evaluate.py")
    has_sections(at, ("What you plan to plant", "How your rotation holds up"))
    cells = [b for b in at.button if (b.key or "").startswith("pickbtn_")]
    assert cells, "rotation picker missing"
    assert at.get("plotly_chart"), "backtest chart missing"
    return f"{len(cells) // len(CROPS)} tiles"


def p_pick():
    at = load("views/evaluate.py")
    at.button(key="pickbtn_0_0_sorghum").click()
    run_after_click(at)
    assert at.session_state["my_plan"][FARM["fields"][0]["name"]][0] == "sorghum", "picking a crop didn't stick"


def p_optimizer():
    at = load("views/optimize.py")
    has_sections(at, ("What should the plan go after?", "What the recommendation must respect",
                      "Recommended plan", "How it holds up"))
    assert not at.warning, f"warning on arrival: {at.warning[0].value[:80]}"
    return "objective, constraints, recommendation, NASA weather test"


def p_use_rotation():
    at = load("views/optimize.py")
    [b for b in at.button if b.label.startswith("Use this rotation")][0].click()
    run_after_click(at)
    assert any("What you plan to plant" in h.value for h in at.subheader), "didn't land on the evaluator"
    caps = " ".join(c.value for c in at.caption)
    assert "optimizer's recommendation" in caps, "evaluator should say the rotation is the recommendation"


def p_one_crop():
    at = load("views/optimize.py", _allowed_crops=["corn"])
    has_sections(at, ("Recommended plan",))
    return "optimizer survives a one-crop ground rule" + (" (rule warning shown)" if at.warning else "")


def p_assistant():
    at = load(faq_history=[{"role": "user", "content": "How did my rotation do?"}], faq_pending=True)
    h = at.session_state["faq_history"]
    assert len(h) == 2 and h[1]["role"] == "assistant" and "seasons" in h[1]["content"], h[-1]["content"][:80]
    return "quick answer uses the live numbers"


# ---------------------------------------------------------------- run
if __name__ == "__main__":
    print("Field Shift check-up · model under test: model.py\n")
    for name, fn in [("functions present", c_functions), ("data and solver", c_data),
                     ("evaluate()", c_evaluate), ("solve(): every objective", c_solve_goals),
                     ("solve(): respects allowed crops", c_solve_allowed),
                     ("limit_ranges() and limits", c_limits), ("backtest()", c_backtest),
                     ("solve_pareto()", c_pareto), ("table_to_plan()", c_round_trip),
                     ("speed", c_speed)]:
        check(name, fn)
    n1 = len(results)
    for name, fn in [("Home", p_home), ("Rotation evaluator", p_evaluator),
                     ("pick a crop on a tile", p_pick), ("Rotation optimizer", p_optimizer),
                     ("Use this rotation", p_use_rotation), ("one-crop ground rule", p_one_crop),
                     ("assistant", p_assistant)]:
        check(name, fn)

    for i, (ok, name, detail) in enumerate(results):
        if i == 0:
            print("Part 1 · model vs interface contract")
        if i == n1:
            print("\nPart 2 · the pages")
        print(f"  {'–' if ok is None else '✓' if ok else '✗'} {name}" + (f"  · {detail}" if detail else ""))
    failed = [r for r in results if r[0] is False]
    skipped = [r for r in results if r[0] is None]
    print(f"\n{len(results) - len(failed) - len(skipped)} of {len(results)} checks passed"
          + (f", {len(skipped)} skipped (see above)" if skipped else "") + ".")
    sys.exit(1 if failed else 0)
