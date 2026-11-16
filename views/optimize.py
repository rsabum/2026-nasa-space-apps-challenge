"""Rotation optimizer: card 01 picks the objective, card 02 sets the constraints (rotation
length, absolute limits, ground rules); the optimizer (model.py) finds the best rotation and
tests it on every season, 1981-2024. Independent of the Rotation evaluator: the only link is
"Use this rotation", which loads the plan there and switches to it."""
import streamlit as st

import ui
from contract import GOALS, ROTATION_LENGTHS
from rules import rule_problems

ss = st.session_state
ui.page_header(
    "Rotation optimizer", "Rotation optimizer",
    "Pick one objective and your constraints. We try every legal rotation and test the best one.",
    [("On this page", "Find a better plan", [
        ("goal", "goal", "Your objective", "The one thing the plan goes after"),
        ("constraints", "limits", "Constraints", "Rotation length, limits, ground rules"),
        ("recommendation", "star", "Recommended plan", "The optimizer's pick, and Use this rotation"),
        ("numbers", "money", "Key numbers", "Profit, water shortfall, soil health"),
        ("backtest", "satellite", "NASA weather test", "Every season, 1981–2024"),
        ("details", "table", "Numbers behind the plan", "Field-by-field table"),
    ]), ui.SETUP_GROUP], compact=True)

ctx = ui.farm_ready()
if ctx is None:
    st.stop()

# ---------- 01 · The objective: what the plan goes after ----------
with st.container(key="card_objective"):
    ui.eyebrow("01 · Your objective")
    st.subheader("What should the plan go after?", anchor="goal")
    ui.objective_controls()

# ---------- 02 · Constraints: rotation length, limits, ground rules ----------
goal, _ = ui.read_objective()
ranges = ui.reachable(ctx)
with st.container(key="card_constraints"):
    ui.eyebrow("02 · Constraints")
    st.subheader("What the recommendation must respect", anchor="constraints")
    st.caption("The recommendation must meet every constraint here.")
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown("**Rotation**")
        ui.remember("opt_len", 4)
        st.segmented_control(
            "Rotation length to search", ROTATION_LENGTHS, key="opt_len",
            on_change=ui.save_search_length, format_func=lambda n: f"{n} years",
            help="How many years the recommended rotation runs before it repeats. The numbers "
                 "are per year, so rotations of different lengths compare fairly. 5 years is "
                 "the biggest search (a second or two).")
        ui.anchor("rules")
        st.markdown("**Ground rules**")
        ui.rules_controls()
    with right:
        st.markdown("**Limits** · each slider spans what your farm can reach")
        ui.limit_controls(goal, ranges, ctx["any_irrigated"])
if not ui.read_rules()["allowed_crops"]:
    st.info("Pick at least one crop under **Crops you'd grow** to get a recommendation.")
    st.stop()

r = ui.or_stop(ui.optimization, ctx)
plan_table, plan = r["table"], r["plan"]

# ---------- 03 · The recommendation ----------
with st.container(key="card_plan"):
    ui.eyebrow("03 · Optimized rotation")
    st.subheader("Recommended plan", anchor="recommendation")
    st.caption(f"Objective: **{GOALS[r['goal']]}**, within your constraints.")
    grid = (plan_table.pivot(index="field", columns="year", values="crop")
            .reindex(plan_table["field"].unique()))
    ui.show_html(ui.rotation_grid_html(grid))
    problems = rule_problems(plan, r["farm"], r["constraints"])
    ui.show_html(ui.plan_chips_html(plan_table, len(problems)))
    if problems:
        st.warning("**The recommendation couldn't meet every ground rule**, so these rules may not "
                   "fit together on your farm. Try loosening one under Constraints above.\n\n"
                   + ui.bullet_list(problems), icon="⚠️")
    unmet = plan_table.attrs.get("unmet", [])
    if unmet:
        st.warning("**Your limits can't all be met at once**, so this is the closest plan the "
                   "optimizer found. Try loosening one under Constraints.\n\n"
                   + ui.bullet_list(unmet), icon="⚠️")
    ui.show_html(ui.about_plan_html(plan, plan_table, r["farm"]))
    ui.show_html('<div class="fs-why-title fs-mix-title">Acres by crop, year by year</div>')
    st.plotly_chart(ui.crop_mix_chart({"Recommended": plan}, r["farm"]), key="crop_mix")
    # The one link between the two tools: load this plan into the evaluator and go there.
    if st.button("Use this rotation →", type="primary",
                 help="Loads this plan into the Rotation evaluator (replacing the rotation there) "
                      "and takes you to it."):
        ui.apply_plan(plan)
        st.switch_page("views/evaluate.py")

# ---------- The three key numbers ----------
ui.metric_row(plan_table)

# ---------- 04 · The test, on NASA weather ----------
bt = r["bt"]
with st.container(key="card_test"):
    ui.eyebrow("04 · Tested on NASA weather")
    st.subheader("How it holds up, 1981–2024", anchor="backtest")
    stat_col, chart_col = st.columns([1, 3.4])
    with stat_col:
        profitable = int((bt["total_profit_usd"] > 0).sum())
        ui.show_html(ui.ring_html(profitable, len(bt), "seasons the recommended rotation would "
                                                       "have made money"))
        worst = bt.loc[bt["total_profit_usd"].idxmin()]
        best = bt.loc[bt["total_profit_usd"].idxmax()]
        st.caption(ui.md_text(f"Each season is run on that year's actual weather. Average season: "
                   f"{ui.money(bt['total_profit_usd'].mean())}. Toughest: {int(worst['year'])} at "
                   f"{ui.money(worst['total_profit_usd'])}. Best: {int(best['year'])} at "
                   f"{ui.money(best['total_profit_usd'])}. The driest was {r['driest']}."))
    with chart_col:
        st.plotly_chart(ui.backtest_chart(bt, name="Recommended rotation"), key="bt_rec")
        st.caption(ui.backtest_caption())

ui.details_table(plan_table, "See the numbers behind the plan")

ui.page_end_nav("Rotation optimizer")
