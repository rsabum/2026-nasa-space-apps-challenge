"""Rotation evaluator: the farmer enters a rotation and sees how it would have done on
every season of NASA weather, 1981-2024 (the team objective). Independent of the optimizer;
its "Use this rotation" button is the only way a plan arrives here from there."""
import streamlit as st

import ui
from contract import ROTATION_LENGTHS, baseline_plan

ss = st.session_state
ui.page_header(
    "Rotation evaluator", "Rotation evaluator",
    "Enter what you plan to plant. We test it on every growing season since 1981.",
    [("On this page", "Enter and test", [
        ("rotation", "rotation", "Your rotation", "Enter what you plan to plant"),
        ("numbers", "money", "Key numbers", "Profit, water shortfall, soil health"),
        ("backtest", "satellite", "NASA weather test", "Every season, 1981–2024"),
        ("details", "table", "Numbers behind it", "Field-by-field table"),
    ]), ui.SETUP_GROUP], compact=True)

ctx = ui.farm_ready()
if ctx is None:
    st.stop()
# ---------- 01 · Your rotation: pick a length, then click a tile to choose its crop ----------
with st.container(key="card_mine"):
    ui.eyebrow("01 · Your rotation")
    st.subheader("What you plan to plant", anchor="rotation")
    st.caption("Your rotation is the optimizer's recommendation. Click a tile to change it, or "
               "reset to start over." if ss.get("applied") else
               "Pick how many years your rotation runs before it repeats, then click any tile to "
               "choose what you'd plant on that field that year. We test it on every season since 1981.")
    len_col, reset_col = st.columns([3, 1], vertical_alignment="bottom")
    with len_col:
        ui.remember("rot_len", 2)
        st.segmented_control(
            "Rotation length", ROTATION_LENGTHS, key="rot_len", on_change=ui.set_length,
            format_func=lambda n: f"{n} years",
            help="How many years before the rotation starts over. Corn–soy is a 2-year "
                 "rotation; corn–soy–wheat is 3. Year 1 follows the last year.")
    farm = ui.with_years(ctx["farm"], ui.rotation_length())
    my_plan = ui.current_plan(ctx["farm"])
    ss["my_plan"] = my_plan
    if ss.get("applied") or my_plan != baseline_plan(farm):
        reset_col.button("↺ Reset to corn–soy", on_click=ui.reset_plan, use_container_width=True)
    ui.rotation_picker(farm, my_plan)

a = ui.or_stop(ui.evaluation, ctx)

# ---------- Key numbers for the farmer's rotation ----------
ui.metric_row(a["table"])

# ---------- 02 · The test, on NASA weather ----------
bt = a["bt"]
with st.container(key="card_test"):
    ui.eyebrow("02 · Tested on NASA weather")
    st.subheader("How your rotation holds up, 1981–2024", anchor="backtest")
    stat_col, chart_col = st.columns([1, 3.4])
    with stat_col:
        profitable = int((bt["total_profit_usd"] > 0).sum())
        ui.show_html(ui.ring_html(profitable, len(bt), "seasons your rotation would have made money"))
        worst = bt.loc[bt["total_profit_usd"].idxmin()]
        best = bt.loc[bt["total_profit_usd"].idxmax()]
        avg = bt["total_profit_usd"].mean()
        st.caption(ui.md_text(f"Each season is run on that year's actual weather. Average season: "
                   f"{ui.money(avg)}. Toughest: {int(worst['year'])} at {ui.money(worst['total_profit_usd'])}. "
                   f"Best: {int(best['year'])} at {ui.money(best['total_profit_usd'])}. "
                   f"The driest was {a['driest']}."))
    with chart_col:
        st.plotly_chart(ui.backtest_chart(bt), key="bt_mine")
        st.caption(ui.BACKTEST_CAPTION)

ui.details_table(a["table"], "See the numbers behind your rotation")

ui.page_end_nav("Rotation evaluator")
