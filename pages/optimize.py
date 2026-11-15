"""Rotation optimizer: pick one goal and limits; the optimizer (model.py) finds the best
rotation and tests it against the farmer's own on every season, 1981-2024."""
import streamlit as st

import ui
from contract import GOALS
from rules import rule_problems

ss = st.session_state
ui.page_header(
    "Rotation optimizer", "Rotation optimizer",
    "Pick one goal and your limits. We try every legal rotation and test the best one.",
    [("On this page", "Find a better plan", [
        ("goal", "🎯", "Your goal", "One goal, then your limits"),
        ("weather", "🌵", "Drought check", "Plan for a typical or a dry year"),
        ("recommendation", "⭐", "Recommended plan", "The optimizer's pick, and why"),
        ("numbers", "💵", "Key numbers", "Against your rotation"),
        ("backtest", "🛰️", "NASA weather test", "Both rotations, 1981–2024"),
        ("details", "📋", "Numbers behind the plan", "Field-by-field table"),
    ]), ui.SETUP_GROUP], compact=True)

ctx = ui.farm_ready()
if ctx is None:
    st.stop()
farm = ctx["farm"]

# ---------- 01 · Your goal and limits ----------
with st.container(key="card_goal"):
    ui.eyebrow("01 · Your goal")
    st.subheader("What should the plan go after?", anchor="goal")
    entered = "my_plan" in ss
    st.caption("Limits are measured against your rotation from the Rotation evaluator."
               if entered else
               "Limits are measured against a plain corn–soy rotation until you enter your own "
               "in the Rotation evaluator.")
    ui.goal_controls(ctx["any_irrigated"])

ui.scenario_card("The recommendation and the four-year numbers")
a = ui.analysis_or_stop(ctx)
plan_table, base_table = a["plan_table"], a["base_table"]
suggested, my_plan = a["suggested"], a["my_plan"]

# ---------- 02 · The recommendation ----------
with st.container(key="card_plan"):
    ui.eyebrow("02 · Optimized rotation")
    st.subheader(f"Recommended plan for a {a['season']} year", anchor="recommendation")
    st.caption(f"Goal: **{GOALS[a['goal']]}**, within your limits and ground rules. "
               "The chips compare it with your rotation.")
    grid = (plan_table.pivot(index="field", columns="year", values="crop")
            .reindex(plan_table["field"].unique()))
    ui.show_html(ui.rotation_grid_html(grid))
    sug_problems = rule_problems(suggested, farm, a["constraints"])
    ui.show_html(ui.result_chips_html(plan_table, base_table, len(sug_problems)))
    if sug_problems:
        st.warning("**The recommendation couldn't meet every ground rule**, so these rules may not "
                   "fit together on your farm. Try loosening one in the left panel.\n\n"
                   + ui.bullet_list(sug_problems), icon="⚠️")
    unmet = plan_table.attrs.get("unmet", [])
    if unmet:
        st.warning("**Your limits can't all be met at once**, so this is the closest plan the "
                   "optimizer found. Try loosening one under Your goal.\n\n"
                   + ui.bullet_list(unmet), icon="⚠️")
    ui.show_html(ui.why_this_plan_html(suggested, my_plan, plan_table, base_table, farm, a["scenario"]))
    ui.show_html('<div class="fs-why-title fs-mix-title">Acres by crop, year by year</div>')
    st.plotly_chart(ui.crop_mix_chart({"Your rotation": my_plan, "Recommended": suggested}, farm),
                    key="crop_mix")
    if suggested != my_plan:
        st.button("Apply recommendation →", type="primary", on_click=ui.apply_plan, args=(suggested,),
                  help="Makes this plan your rotation, so you can tweak it in the Rotation evaluator.")
    else:
        st.caption(":blue[✓ This is your rotation now.]")
        st.page_link("pages/evaluate.py", label="Tweak it in the Rotation evaluator",
                     icon=":material/fact_check:")

# ---------- The three key numbers, against the farmer's rotation ----------
ui.metric_row(plan_table, a["season"], base=base_table)

# ---------- 03 · The test, on NASA weather ----------
bt_plan, bt_base = a["bt_plan"], a["bt_base"]
with st.container(key="card_test"):
    ui.eyebrow("03 · Tested on NASA weather")
    st.subheader("How it holds up, 1981–2024", anchor="backtest")
    stat_col, chart_col = st.columns([1, 3.4])
    with stat_col:
        ui.show_html(ui.ring_html(a["wins"], len(bt_plan),
                                  "seasons where the recommendation out-earned your rotation"))
        worst_mine = bt_base.loc[bt_base["total_profit_usd"].idxmin()]
        worst_rec = bt_plan.loc[bt_plan["total_profit_usd"].idxmin()]
        st.caption(f"Each rotation is run on that season's actual weather. Toughest season: "
                   f"yours {int(worst_mine['year'])} at {ui.money(worst_mine['total_profit_usd'])}, "
                   f"the recommendation's {int(worst_rec['year'])} at "
                   f"{ui.money(worst_rec['total_profit_usd'])}. The driest was {a['driest']}.")
    with chart_col:
        st.plotly_chart(ui.backtest_chart(bt_base, bt_plan), key="bt_both")
        st.caption(ui.BACKTEST_CAPTION)

ui.details_table(plan_table, "See the numbers behind the plan")
