"""Rotation evaluator: the farmer enters a rotation and sees how it would have done on
every season of NASA weather, 1981-2024 (the team objective)."""
import pandas as pd
import streamlit as st

import ui
from contract import CROPS, baseline_plan
from rules import rule_problems

ss = st.session_state
ui.page_header(
    "Rotation evaluator", "Rotation evaluator",
    "Enter what you plan to plant. We test it on every growing season since 1981.",
    [("On this page", "Enter and test", [
        ("weather", "🌵", "Drought check", "Plan for a typical or a dry year"),
        ("rotation", "🌽", "Your rotation", "Enter what you plan to plant"),
        ("numbers", "💵", "Key numbers", "Profit, water shortfall, soil health"),
        ("backtest", "🛰️", "NASA weather test", "Every season, 1981–2024"),
        ("details", "📋", "Numbers behind it", "Field-by-field table"),
    ]), ui.SETUP_GROUP], compact=True)

ctx = ui.farm_ready()
if ctx is None:
    st.stop()
farm = ctx["farm"]

ui.scenario_card("The four-year numbers")

# ---------- 01 · Your rotation (the farmer types it in) ----------
with st.container(key="card_mine"):
    ui.eyebrow("01 · Your rotation")
    st.subheader("What you plan to plant", anchor="rotation")
    st.caption("Your rotation is the optimizer's recommendation. Edit it, or reset to start over."
               if ss.get("applied") else
               "It starts as a plain corn–soy rotation. Press Edit rotation and change it to what "
               "you'd actually plant; we'll test it on every season since 1981.")
    ui.show_html(ui.crop_key_html())
    tiles = st.container()   # the tiles go here, once we know the rotation
    b1, b2, _ = st.columns([1, 1, 2.6])
    # A new key restarts the editor: when fields change, or a plan is applied or reset.
    editor_key = (f"rotation-{'|'.join(str(f['name']) for f in farm['fields'])}"
                  f"-v{ss.get('editor_version', 0)}")
    if editor_key not in ss:
        # The editor is starting fresh (first visit, back from another page, or restarted):
        # start it from the rotation entered last time.
        ss["rotation_base"] = ui.current_plan(farm)
    start = ui.fit_plan(ss.get("rotation_base"), farm)
    with b1.popover(":material/edit: Edit rotation"):
        ui.show_html('<div class="fm-edit-title">Edit your rotation</div>')
        year_columns = {
            ui.year_label(i): st.column_config.SelectboxColumn(
                ui.year_label(i), options=CROPS, format_func=ui.crop_name, required=True)
            for i in range(farm["years"])
        }
        edited = st.data_editor(
            ui.rotation_editor_frame(start),
            column_config={"Field": st.column_config.TextColumn("Field", disabled=True), **year_columns},
            num_rows="fixed", hide_index=True, key=editor_key,
        )
        st.caption("Click a cell to pick a crop.")
    if ss.get("applied") or start != baseline_plan(farm):
        b2.button("↺ Reset to corn–soy", on_click=ui.reset_plan)
    my_plan, blanks = ui.editor_to_plan(edited, farm, start)
    ss["my_plan"] = my_plan   # the optimizer compares against this
    with tiles:
        ui.show_html(ui.rotation_grid_html(pd.DataFrame(my_plan).T.rename(columns=lambda i: i + 1)))
    if blanks:
        st.caption(f":orange[{blanks} empty cell{'' if blanks == 1 else 's'} filled in with "
                   "the starting crop for that year.]")
    problems = rule_problems(my_plan, farm, ctx["constraints"])
    if problems:
        st.warning("**Your rotation breaks some of your ground rules.** We'll still test it "
                   "as you entered it.\n\n" + ui.bullet_list(problems), icon="⚠️")
    else:
        st.caption(":blue[✓ Follows all your ground rules.]")

a = ui.analysis_or_stop(ctx)

# ---------- Key numbers for the farmer's rotation ----------
ui.metric_row(a["base_table"], a["season"])

# ---------- 02 · The test, on NASA weather ----------
bt = a["bt_base"]
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
        st.caption(f"Each season is run on that year's actual weather. Average season: "
                   f"{ui.money(avg)}. Toughest: {int(worst['year'])} at {ui.money(worst['total_profit_usd'])}. "
                   f"Best: {int(best['year'])} at {ui.money(best['total_profit_usd'])}. "
                   f"The driest was {a['driest']}.")
    with chart_col:
        st.plotly_chart(ui.backtest_chart(bt), key="bt_mine")
        st.caption(ui.BACKTEST_CAPTION)

ui.details_table(a["base_table"], "See the numbers behind your rotation")

# ---------- Next step ----------
with st.container(key="card_next"):
    st.markdown("**Could another rotation do better?** The optimizer tries every legal rotation "
                "on your fields, for the goal you pick, and tests it on the same 44 seasons.")
    st.page_link("pages/optimize.py", label="Open the rotation optimizer", icon=":material/auto_awesome:")
