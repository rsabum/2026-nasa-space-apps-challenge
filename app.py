"""Field Shift: Streamlit app entry point (owner: Claude-Thomas, Team Athens).

Run with:  streamlit run app.py

Three pages, picked from the menu at the top of the left panel:
    pages/home.py       Home: what Field Shift does, your farm at a glance
    pages/evaluate.py   Rotation evaluator: enter your rotation, test it on 1981-2024
    pages/optimize.py   Rotation optimizer: pick a goal and limits, get a better rotation

This file runs first on every click, whichever page is open. It sets up the page, keeps
the shared choices alive (ui.keep_state), draws the farm setup in the left panel (your
fields and ground rules, the same on every page), runs the open page, and adds the
chat assistant. The drawing code all three pages share lives in ui.py.
"""
import pandas as pd
import streamlit as st

import assistant
import ui
from contract import CONSTRAINTS, CROPS, FARM

st.set_page_config(page_title="Field Shift", page_icon=str(ui.ASSETS / "icon.png"), layout="wide")
ui.load_styles()
ui.keep_state()

pages = st.navigation([
    st.Page("pages/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("pages/evaluate.py", title="Rotation evaluator", icon=":material/fact_check:",
            url_path="evaluate"),
    st.Page("pages/optimize.py", title="Rotation optimizer", icon=":material/auto_awesome:",
            url_path="optimize"),
])

# ---------- Left panel: the farm setup, shared by every page ----------
with st.sidebar:
    ui.anchor("fields")   # sidebar headings get no id from Streamlit, so add our own
    st.header("Your fields", anchor=False)
    field_map = st.container()   # the map is drawn here, once we know the fields
    with st.popover(":material/edit: Edit fields"):
        ui.show_html('<div class="fm-edit-title">Edit your fields</div>')
        fields = st.data_editor(
            pd.DataFrame(FARM["fields"]).assign(irrigated=False),
            column_config={
                "name": st.column_config.TextColumn("Field", required=True),
                "acres": st.column_config.NumberColumn("Acres", min_value=1, step=1, required=True),
                "soil": st.column_config.TextColumn("Soil", required=True),
                "last_crop": st.column_config.SelectboxColumn(
                    "Last crop", options=CROPS, format_func=ui.crop_name, required=True),
                "irrigated": st.column_config.CheckboxColumn(
                    "Irrigated", help="Tick if the field has irrigation (e.g. a centre pivot). "
                                      "The model then pumps water when the crop runs short."),
            },
            num_rows="dynamic", hide_index=True, key="fields",
        )
        st.caption("Click a cell to change it. To add a field, fill in the first four cells of "
                   "the empty bottom row. To remove one, tick the box on its left and press Delete.")
    fields = fields.assign(irrigated=fields["irrigated"].fillna(False).astype(bool)).dropna()   # ignore half-filled rows
    with field_map:
        ui.show_html(ui.field_map_html(fields))
        st.caption("Each plot is sized by its acres and tinted by last season's crop.")

    ui.anchor("rules")
    st.header("Ground rules", anchor=False)
    allowed = st.multiselect("Crops you'd grow", CROPS, CONSTRAINTS["allowed_crops"], key="allowed_crops",
                             format_func=ui.crop_name)
    no_repeat = st.checkbox(
        "No back-to-back crops", CONSTRAINTS["no_repeat"],
        help="Planting the same crop two years running builds pest and disease "
             "pressure and wears the soil down. Last season's crop counts too.")
    min_soy = st.checkbox(
        "At least one soybean year per field", CONSTRAINTS["min_legume_years"] >= 1,
        help="Soybeans are a legume: they fix nitrogen in the soil, so the crop "
             "after them needs less fertilizer.")
    max_share = st.slider(
        "Most acres in one crop", 30, 100, int(CONSTRAINTS["max_crop_share"] * 100), step=1,
        format="%d%%",
        help="The largest share of your land any one crop can take in a single year, "
             "so one bad price or one bad season can't hit every acre. "
             "Set it at or above your biggest field's share, or no plan can meet it.")

# What the pages read (through ui.farm_ready). Rebuilt on every run, so it's never stale.
st.session_state["_farm_ctx"] = {
    "farm": {**FARM, "fields": fields.to_dict("records")},
    "constraints": {**CONSTRAINTS, "allowed_crops": allowed, "no_repeat": no_repeat,
                    "min_legume_years": 1 if min_soy else 0, "max_crop_share": max_share / 100},
    "any_irrigated": bool(fields["irrigated"].any()),
}

# ---------- The open page ----------
pages.run()
ui.footer()

# ---------- The assistant: floating chat bubble, bottom right, on every page ----------
ctx = st.session_state["_farm_ctx"]
if ctx["farm"]["fields"] and ctx["constraints"]["allowed_crops"]:
    try:
        a = ui.analysis(ctx)
    except Exception:   # the page has already shown the error; skip the assistant
        a = None
    if a:
        assistant.render(
            ui.faq_context(a["farm"], a["scenario"], a["goal"], a["limits"], a["plan_table"],
                           a["base_table"], a["wins"], len(a["bt_plan"]), a["driest"],
                           a["my_problems"], a["suggested"], a["my_plan"]),
            avatar=str(ui.ASSETS / "icon.png"))
