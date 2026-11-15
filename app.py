"""Field Shift: Streamlit app entry point (owner: Claude-Thomas, Team Athens).

Run with:  streamlit run app.py

Three pages, picked from the menu at the top of the left panel. They live in views/, NOT
pages/: Streamlit treats a folder named pages/ as its older automatic page list and runs
those files without this entry point (no farm setup, no shared state).
    views/home.py       Home: what Field Shift does, your farm at a glance
    views/evaluate.py   Rotation evaluator: enter your rotation, test it on 1981-2024
    views/optimize.py   Rotation optimizer: pick a goal and limits, get a better rotation

This file runs first on every click, whichever page is open. It sets up the page, keeps
the shared choices alive (ui.keep_state), draws your fields in the left panel (the same
on every page), runs the open page, and adds the chat assistant. The ground rules only
shape the optimizer's search, so they live on the Rotation optimizer page. The drawing code all three pages share lives in ui.py.
"""
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import assistant
import ui
from contract import CROPS, FARM

st.set_page_config(page_title="Field Shift", page_icon=str(ui.ASSETS / "icon.png"), layout="wide")
ui.load_styles()
ui.keep_state()

@st.dialog("Your rotation in 3D", width="large")
def rotation_3d_fullscreen(farm):
    """The 3D rotation model, big: opened by the Full screen button in the left panel."""
    components.html(ui.farm_3d_html(farm, ui.current_plan(farm), big=True), height=640)
    st.caption("Drag to turn, scroll to zoom, right-drag to move. Y1, Y2… show each year of your "
               "rotation (▶ plays through it); hover a field for its whole rotation. Slide the time "
               "of day, or let ↻ Day cycle run. Close with ✕ or Esc.")


pages = st.navigation([
    st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/evaluate.py", title="Rotation evaluator", icon=":material/fact_check:",
            url_path="evaluate"),
    st.Page("views/optimize.py", title="Rotation optimizer", icon=":material/auto_awesome:",
            url_path="optimize"),
])

# ---------- Left panel: your fields, shared by every page ----------
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

    # ---------- Your rotation in 3D: the evaluator's rotation as stacked layers ----------
    if not fields.empty:
        with st.container(key="rot3d"):
            st.header("Your rotation in 3D", anchor=False)
            farm3d = {**FARM, "fields": fields.to_dict("records")}
            plan3d = ui.current_plan(farm3d)
            if plan3d:
                components.html(ui.farm_3d_html(farm3d, plan3d), height=270)
                if st.button(":material/open_in_full: Full screen", key="rot3d_full",
                             use_container_width=True,
                             help="Open the 3D model big, to spin and zoom it."):
                    rotation_3d_fullscreen(farm3d)
                st.caption("Your rotation from the Rotation evaluator, planted. Y1, Y2… switch "
                           "years, ☀/☾ day or night, drag to turn, hover a field for details.")

# What the pages read (through ui.farm_ready). Rebuilt on every run, so it's never stale.
st.session_state["_farm_ctx"] = {
    "farm": {**FARM, "fields": fields.to_dict("records")},
    "any_irrigated": bool(fields["irrigated"].any()),
}

# ---------- The open page ----------
pages.run()
ui.footer()

# ---------- The assistant: floating chat bubble, bottom right, on every page ----------
ctx = st.session_state["_farm_ctx"]
if ctx["farm"]["fields"]:
    try:
        mine = ui.evaluation(ctx)
    except Exception:   # the page has already shown the error; skip the assistant
        mine = None
    try:
        rec = ui.optimization(ctx) if ui.read_rules()["allowed_crops"] else None
    except Exception:
        rec = None
    if mine:
        assistant.render(ui.faq_context(mine["farm"], mine, rec), avatar=str(ui.ASSETS / "icon.png"))
