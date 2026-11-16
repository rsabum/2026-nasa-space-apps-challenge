"""Home page: what Field Shift does, the two tools, and your farm at a glance."""
import streamlit as st

import ui
from contract import GOALS

ui.page_header(
    "Home", "Field Shift",
    "Test your crop rotation against 44 seasons of NASA weather, then see if there's a better one.",
    [("On this page", "Start here", [
        ("tools", "tools", "Two tools", "Test your rotation, or find the best one"),
        ("how", "satellite", "How it works", "From your fields to a tested plan"),
        ("glance", "chart", "Your farm at a glance", "Today's numbers, in one line"),
        ("sources", "sources", "Data sources", "Where every number comes from"),
    ]), ui.SETUP_GROUP])

# ---------- The two tools ----------
ui.anchor("tools")
left, right = st.columns(2, gap="medium")
with left.container(key="card_tool_eval"):
    ui.eyebrow("Tool 1 · Rotation evaluator")
    st.subheader("How would my rotation have done?", anchor=False)
    st.markdown("Pick your rotation's length (2 to 5 years), then click a field and year to "
                "choose what you'd plant. Field Shift runs "
                "it through **every growing season from 1981 to 2024**: profit, water shortfall "
                "and soil health per year, and the seasons that would have hurt.")
    st.page_link("views/evaluate.py", label="Evaluate my rotation", icon=":material/fact_check:")
with right.container(key="card_tool_opt"):
    ui.eyebrow("Tool 2 · Rotation optimizer")
    st.subheader("What's the best rotation for my goal?", anchor=False)
    st.markdown("Pick **one objective**: most profit, least water, best bad-year profit or "
                "healthiest soil. Set your constraints, such as *profit at least $40,000 a year*, "
                "the rotation length and your ground rules. The optimizer tries every legal "
                "rotation on every field and tests its pick on the same 44 seasons. Like it? "
                "**Use this rotation** loads it into the evaluator.")
    st.page_link("views/optimize.py", label="Find the best rotation", icon=":material/auto_awesome:")

# ---------- How it works ----------
ui.anchor("how")
ui.show_html(
    '<nav class="fs-flow" aria-label="How it works">'
    '<div class="fs-step"><span>1</span>Set up your fields (left panel)</div>'
    '<div class="fs-step"><span>2</span>Enter your rotation in the evaluator</div>'
    '<div class="fs-step"><span>3</span>Run it through NASA weather, 1981–2024</div>'
    '<div class="fs-step"><span>4</span>Let the optimizer find a better one</div></nav>')

# ---------- Your farm at a glance ----------
ui.anchor("glance")
ctx = ui.farm_ready()
if ctx:
    a = ui.or_stop(ui.evaluation, ctx)
    r = ui.or_stop(ui.optimization, ctx)
    bt = a["bt"]
    worst = bt.loc[bt["total_profit_usd"].idxmin()]
    p, _, _ = ui.totals(a["table"])
    rp, _, _ = ui.totals(r["table"])
    acres = sum(float(f["acres"]) for f in a["farm"]["fields"])
    entered = "my_plan" in st.session_state
    st.markdown(f"**Your farm at a glance** · {acres:g} acres in {len(a['farm']['fields'])} fields, "
                "averaged over 1981–2024 weather")
    c1, c2, c3 = st.columns(3)
    with c1.container(key="m_profit"):
        st.metric(f"{'Your' if entered else 'Corn–soy'} rotation, per year", f"${p:,.0f}",
                  help="Net profit of the rotation in the Rotation evaluator (corn–soy until you "
                       "enter your own).")
    with c2.container(key="m_water"):
        st.metric("Its toughest season since 1981", str(int(worst["year"])),
                  f"{ui.money(worst['total_profit_usd'])} that season", delta_color="off",
                  help="The season that rotation would have earned least, across the farm.")
    with c3.container(key="m_soil"):
        st.metric(f"Optimizer's pick: {GOALS[r['goal']]}", f"${rp:,.0f}",
                  f"per year, {r['years']}-year rotation", delta_color="off",
                  help="Net profit per year of the Rotation optimizer's recommendation for its "
                       "current objective and constraints.")

# ---------- Data sources ----------
ui.show_html(ui.sources_html())
