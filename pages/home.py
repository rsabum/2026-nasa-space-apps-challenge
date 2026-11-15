"""Home page: what Field Shift does, the two tools, and your farm at a glance."""
import streamlit as st

import ui
from contract import GOALS

ui.page_header(
    "Home", "Field Shift",
    "Test your crop rotation against 44 seasons of NASA weather, then see if there's a better one.",
    [("On this page", "Start here", [
        ("tools", "🧭", "Two tools", "Evaluate your rotation, or optimize it"),
        ("how", "🛰️", "How it works", "From your fields to a tested plan"),
        ("glance", "📊", "Your farm at a glance", "Today's numbers, in one line"),
        ("sources", "📚", "Data sources", "Where every number comes from"),
    ]), ui.SETUP_GROUP])

# ---------- The two tools ----------
ui.anchor("tools")
left, right = st.columns(2, gap="medium")
with left.container(key="card_tool_eval"):
    ui.eyebrow("Tool 1 · Rotation evaluator")
    st.subheader("How would my rotation have done?", anchor=False)
    st.markdown("Enter what you plan to plant on each field for the next four years. Field Shift "
                "checks it against your ground rules and runs it through **every growing season "
                "from 1981 to 2024**: profit, water shortfall and soil health, and the seasons "
                "that would have hurt.")
    st.page_link("pages/evaluate.py", label="Evaluate my rotation", icon=":material/fact_check:")
with right.container(key="card_tool_opt"):
    ui.eyebrow("Tool 2 · Rotation optimizer")
    st.subheader("Is there a better rotation?", anchor=False)
    st.markdown("Pick **one goal**: most profit, least water, best bad-year profit or healthiest "
                "soil. Set your limits, such as *profit at least 95% of mine*. The optimizer tries "
                "every legal rotation on every field and tests its pick on the same 44 seasons.")
    st.page_link("pages/optimize.py", label="Optimize my rotation", icon=":material/auto_awesome:")

# ---------- How it works ----------
ui.anchor("how")
ui.show_html(
    '<nav class="fs-flow" aria-label="How it works">'
    '<div class="fs-step"><span>1</span>Set up your fields and ground rules (left panel)</div>'
    '<div class="fs-step"><span>2</span>Enter your rotation in the evaluator</div>'
    '<div class="fs-step"><span>3</span>Run it through NASA weather, 1981–2024</div>'
    '<div class="fs-step"><span>4</span>Let the optimizer find a better one</div></nav>')

# ---------- Your farm at a glance ----------
ui.anchor("glance")
ctx = ui.farm_ready()
if ctx:
    a = ui.analysis_or_stop(ctx)
    bt = a["bt_base"]
    worst = bt.loc[bt["total_profit_usd"].idxmin()]
    p, _, _ = ui.totals(a["base_table"])
    rp, _, _ = ui.totals(a["plan_table"])
    acres = sum(float(f["acres"]) for f in a["farm"]["fields"])
    entered = "my_plan" in st.session_state
    st.markdown(f"**Your farm at a glance** · {acres:g} acres in {len(a['farm']['fields'])} fields, "
                f"planning for a {a['season']} year")
    c1, c2, c3 = st.columns(3)
    with c1.container(key="m_profit"):
        st.metric(f"{'Your' if entered else 'Corn–soy'} rotation, 4 {a['season']} years", f"${p:,.0f}",
                  help="Net profit of your rotation (corn–soy until you enter your own in the "
                       "Rotation evaluator).")
    with c2.container(key="m_water"):
        st.metric("Toughest season since 1981", str(int(worst["year"])),
                  f"{ui.money(worst['total_profit_usd'])} that season", delta_color="off",
                  help="The season your rotation would have earned least, per season across the farm.")
    with c3.container(key="m_soil"):
        d = rp - p
        st.metric(f"Optimizer: {GOALS[a['goal']]}", f"{'+' if d >= 0 else '−'}${abs(d):,.0f}",
                  f"ahead in {a['wins']} of {len(a['bt_plan'])} seasons", delta_color="off",
                  help="How the optimizer's pick for your current goal compares with your rotation: "
                       "4-year profit difference, and seasons since 1981 where it out-earned yours.")

# ---------- Data sources ----------
ui.show_html(ui.sources_html())
