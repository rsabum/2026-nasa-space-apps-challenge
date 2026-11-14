"""Field Shift: Streamlit app (owner: Claude-Thomas, Team Athens)."""
import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import fake_model as model  # switch to `import model` when Robert's model.py is ready
from contract import (CONSTRAINTS, CROP_COLORS, CROP_ICONS, CROP_LABELS, CROPS, FARM,
                      WEIGHTS, baseline_plan, normalize_weights)

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
INK = "#26302A"      # text
ACCENT = "#3F7D6B"   # the suggested plan
MUTED = "#A3AAA4"    # the current rotation
SCENARIO_LABELS = {"average": "A typical year", "dry": "A dry year"}
MAP_WIDTH = 266     # pixels the field map gets inside the sidebar


def crop_name(crop):
    """'winter_wheat' -> icon + 'Winter wheat'. Display only."""
    return f"{CROP_ICONS.get(crop, '')} {CROP_LABELS.get(crop, crop)}".strip()


def show_html(markup):
    """Draw a block of our own HTML on the page."""
    st.markdown(markup, unsafe_allow_html=True)


def eyebrow(text):
    """The small green label above a section title."""
    show_html(f'<div class="fs-eyebrow">{text}</div>')


def rotation_grid_html(grid):
    """Build the fields x years grid as rounded tiles, one per crop."""
    head = '<div></div>' + "".join(f'<div class="rg-year">Year {y}</div>' for y in grid.columns)
    body = ""
    for field, row in grid.iterrows():
        body += f'<div class="rg-field">{html.escape(str(field))}</div>'
        for year, crop in row.items():
            label = html.escape(CROP_LABELS.get(crop, str(crop)))
            body += (f'<div class="rg-cell" style="background:{CROP_COLORS.get(crop, "#EEEEEE")}" '
                     f'title="{html.escape(str(field))}, year {year}: {label}">'
                     f'<span class="rg-icon">{CROP_ICONS.get(crop, "")}</span>'
                     f'<span class="rg-name">{label}</span></div>')
    columns = f"minmax(4.5rem, 6rem) repeat({len(grid.columns)}, 1fr)"
    return f'<div class="rg" style="grid-template-columns:{columns}">{head}{body}</div>'


def year_label(i):
    """0 -> 'Year 1'. Column names for the rotation editor."""
    return f"Year {i + 1}"


def rotation_editor_frame(farm):
    """Starting table for the farmer's own rotation: one row per field, one column
    per year, pre-filled with the corn-soy rotation from contract.baseline_plan()."""
    start = baseline_plan(farm)
    rows = []
    for name, crops in start.items():
        row = {"Field": name}
        for i, crop in enumerate(crops):
            row[year_label(i)] = crop
        rows.append(row)
    return pd.DataFrame(rows)


def editor_to_plan(table, farm):
    """Turn the edited table back into a plan {field: [crop per year]}.
    Any cell the farmer cleared falls back to the corn-soy crop, and we report how many."""
    start = baseline_plan(farm)
    plan, blanks = {}, 0
    for row in table.to_dict("records"):
        crops = []
        for i in range(farm["years"]):
            crop = row.get(year_label(i))
            if crop not in CROPS:
                crop = start[row["Field"]][i]
                blanks += 1
            crops.append(crop)
        plan[row["Field"]] = crops
    return plan, blanks


def field_map_html(fields):
    """Draw the farm from above: one plot per field, sized by its acres and
    tinted by the crop that grew there last season."""
    if fields.empty:
        return '<div class="fm fm-empty">No fields yet.<br>Add one with Edit fields.</div>'
    total = fields["acres"].sum()
    rows = [fields.iloc[i:i + 2] for i in range(0, len(fields), 2)]   # two plots per row
    height = max(150, 96 * len(rows))
    furrows = [115, 25, 65, 155]   # each plot is "ploughed" in its own direction
    out, n = "", 0
    for pair in rows:
        row_acres = pair["acres"].sum()
        plots = ""
        for f in pair.itertuples():
            name = html.escape(str(f.name))
            soil = html.escape(str(f.soil))
            crop = CROP_LABELS.get(f.last_crop, str(f.last_crop))
            # Small plots only have room for the name and the acres.
            roomy = (row_acres / total) * height >= 84 and (f.acres / row_acres) * MAP_WIDTH >= 100
            plots += (
                f'<div class="fm-plot{"" if roomy else " fm-small"}" '
                f'style="flex-grow:{f.acres:g};background-color:{CROP_COLORS.get(f.last_crop, "#EEEEEE")};'
                f'--furrow:{furrows[n % 4]}deg" '
                f'title="{name}: {f.acres:g} acres, {soil}. Last season: {html.escape(crop)}.">'
                f'<div class="fm-name">{name}</div>'
                f'<div><div class="fm-line"><span class="fm-acres">{f.acres:g}<small> ac</small></span>'
                f'<span class="fm-icon">{CROP_ICONS.get(f.last_crop, "")}</span></div>'
                f'<div class="fm-soil">{soil}</div></div></div>')
            n += 1
        out += f'<div class="fm-row" style="flex-grow:{row_acres:g}">{plots}</div>'
    summary = (f'<div class="fm-sum"><b>{total:g}</b> acres across <b>{len(fields)}</b> '
               f'field{"" if len(fields) == 1 else "s"}</div>')
    return f'{summary}<div class="fm" style="height:{height}px">{out}</div>'


st.set_page_config(page_title="Field Shift", page_icon=str(ASSETS / "icon.png"), layout="wide")

# All the styling lives in style.css. The colours and theme base are in .streamlit/config.toml.
show_html(f"<style>{(HERE / 'style.css').read_text()}</style>")

# ---------- Header ----------
logo_svg = (ASSETS / "logo.svg").read_text()
pills = "".join(f'<span style="background:{c}"></span>' for c in CROP_COLORS.values())
show_html(
    '<div class="fs-hero">' + logo_svg +
    '<div><div class="fs-hero-title">Field Shift</div>'
    '<div class="fs-hero-tag">Test your rotation against 44 seasons of NASA weather, '
    "then see if there's a better one.</div></div>"
    '<div class="fs-hero-team">Team Athens</div></div>'
    f'<div class="fs-pills">{pills}</div>'
)

# ---------- Sidebar: inputs ----------
with st.sidebar:
    st.header("Your fields")
    field_map = st.container()   # the map is drawn here, once we know the fields
    with st.popover(":material/edit: Edit fields"):
        show_html('<div class="fm-edit-title">Edit your fields</div>')
        fields = st.data_editor(
            pd.DataFrame(FARM["fields"]),
            column_config={
                "name": st.column_config.TextColumn("Field", required=True),
                "acres": st.column_config.NumberColumn("Acres", min_value=1, step=1, required=True),
                "soil": st.column_config.TextColumn("Soil", required=True),
                "last_crop": st.column_config.SelectboxColumn(
                    "Last crop", options=CROPS, format_func=crop_name, required=True),
            },
            num_rows="dynamic", hide_index=True, key="fields",
        )
        st.caption("Click a cell to change it. To add a field, fill in all four cells of the "
                   "empty bottom row. To remove one, tick the box on its left and press Delete.")
    fields = fields.dropna()   # ignore half-filled rows
    with field_map:
        show_html(field_map_html(fields))
        st.caption("Each plot is sized by its acres and tinted by last season's crop.")

    st.header("What matters most")
    weights = {
        "profit": st.slider(
            "Profit", 0, 10, WEIGHTS["profit"],
            help="Net return after seed, fertilizer and operating costs."),
        "water": st.slider(
            "Water", 0, 10, WEIGHTS["water"],
            help="Favors crops whose water need is covered by the season's rain, "
                 "so the plan is less exposed in a dry year."),
        "soil": st.slider(
            "Soil health", 0, 10, WEIGHTS["soil"],
            help="Favors rotations that build the soil: legumes that fix nitrogen, "
                 "more residue, more variety."),
    }

    st.header("Ground rules")
    allowed = st.multiselect("Crops you'd grow", CROPS, CONSTRAINTS["allowed_crops"],
                             format_func=crop_name)
    no_repeat = st.checkbox(
        "No back-to-back crops", CONSTRAINTS["no_repeat"],
        help="Planting the same crop two years running builds pest and disease "
             "pressure and wears the soil down.")
    scenario = st.radio(
        "Plan for", ["average", "dry"], horizontal=True,
        format_func=SCENARIO_LABELS.get,
        help="A dry-year plan gives up some profit in good seasons to lose less in bad ones.")

# Stop early if there is nothing to plan.
if fields.empty:
    st.info("Add at least one field in the sidebar to get a plan.")
    st.stop()
if not allowed:
    st.info("Pick at least one crop under Ground rules to get a plan.")
    st.stop()

farm = {**FARM, "fields": fields.to_dict("records")}
constraints = {**CONSTRAINTS, "allowed_crops": allowed, "no_repeat": no_repeat}

# ---------- 01 · Your rotation (the farmer types it in) ----------
with st.container(key="card_mine"):
    eyebrow("01 · Your rotation")
    st.subheader("What you plan to plant")
    st.caption("Click a cell to pick a crop. It starts as a plain corn–soy rotation; "
               "change it to what you'd actually plant and we'll test it on every season since 1981.")
    year_columns = {
        year_label(i): st.column_config.SelectboxColumn(
            year_label(i), options=CROPS, format_func=crop_name, required=True)
        for i in range(farm["years"])
    }
    edited = st.data_editor(
        rotation_editor_frame(farm),
        column_config={"Field": st.column_config.TextColumn("Field", disabled=True), **year_columns},
        num_rows="fixed", hide_index=True,
        key="rotation-" + "|".join(fields["name"].astype(str)),   # resets when fields change
    )
    my_plan, blanks = editor_to_plan(edited, farm)
    if blanks:
        st.caption(f":orange[{blanks} empty cell{'' if blanks == 1 else 's'} filled in with "
                   "the corn–soy crop for that year.]")

# ---------- Run the model ----------
try:
    plan_table = model.solve(farm, None, normalize_weights(weights), scenario, constraints)
    base_table = model.evaluate(my_plan, farm, None, scenario)
    bt_plan = model.backtest(model.table_to_plan(plan_table), farm)
    bt_base = model.backtest(my_plan, farm)
except Exception as e:  # never show a traceback to a judge
    st.error(f"The model could not run: {e}")
    st.stop()

# ---------- 01 · The plan ----------
with st.container(key="card_plan"):
    eyebrow("02 · The suggestion")
    st.subheader("Suggested rotation")
    st.caption("One crop per field per year. Read across for each field's next four seasons.")
    grid = (plan_table.pivot(index="field", columns="year", values="crop")
            .reindex(plan_table["field"].unique()))
    show_html(rotation_grid_html(grid))

# ---------- The three key numbers, against the current rotation ----------
def totals(t):
    return (t["profit_usd"].sum(),
            (t["water_shortfall_mm"] * t["acres"]).sum() / 25.4,
            t["soil_score_change"].sum())

p, w, s = totals(plan_table)
bp, bw, bs = totals(base_table)
c1, c2, c3 = st.columns(3)
with c1.container(key="m_profit"):
    st.metric("Net profit, 4 years", f"${p:,.0f}", f"{p - bp:+,.0f} vs your rotation",
              help="Revenue minus seed, fertilizer and operating costs, across all fields.")
with c2.container(key="m_water"):
    st.metric("Water shortfall", f"{w:,.0f} acre-in", f"{w - bw:+,.0f} vs your rotation",
              delta_color="inverse",
              help="How far growing-season rain fell short of what the crops needed. "
                   "One acre-inch is an inch of water over one acre. Lower is better.")
with c3.container(key="m_soil"):
    st.metric("Soil health", f"{s:+.1f}", f"{s - bs:+.1f} vs your rotation",
              help="A score for what the rotation does to your soil: residue, nitrogen "
                   "from legumes and crop variety. Higher is better.")

# ---------- 02 · The test ----------
with st.container(key="card_test"):
    eyebrow("03 · The test")
    st.subheader("How it holds up, 1981–2024")
    wins = int((bt_plan["total_profit_usd"] > bt_base["total_profit_usd"]).sum())
    stat_col, chart_col = st.columns([1, 3.4])
    with stat_col:
        show_html(
            f'<div class="fs-stat"><div class="fs-stat-num">{wins}<small> / {len(bt_plan)}</small></div>'
            '<div class="fs-stat-label">seasons where the suggested rotation out-earned '
            'your rotation</div></div>')
        worst = bt_base.loc[bt_base["total_profit_usd"].idxmin()]
        st.caption(f"Each rotation is run against that season's actual weather. "
                   f"Your rotation's toughest season was {int(worst['year'])}, "
                   f"at ${worst['total_profit_usd']:,.0f}.")
    with chart_col:
        bt = go.Figure()
        bt.add_trace(go.Scatter(
            x=bt_base["year"], y=bt_base["total_profit_usd"], name="Your rotation",
            line=dict(color=MUTED, width=2), hovertemplate="$%{y:,.0f}"))
        bt.add_trace(go.Scatter(
            x=bt_plan["year"], y=bt_plan["total_profit_usd"], name="Suggested rotation",
            line=dict(color=ACCENT, width=3), hovertemplate="$%{y:,.0f}"))
        bt.update_layout(
            height=330, margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(title="Whole-farm net profit", tickprefix="$"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
        st.plotly_chart(bt)

with st.expander("See the numbers behind the plan"):
    details = plan_table.assign(crop=plan_table["crop"].map(crop_name)).rename(columns={
        "field": "Field", "year": "Year", "crop": "Crop", "acres": "Acres",
        "water_need_mm": "Water need (mm)", "water_shortfall_mm": "Shortfall (mm)",
        "soil_score_change": "Soil health", "profit_usd": "Net profit ($)"})
    st.dataframe(details, hide_index=True)

show_html('<div class="fs-footer">Sample numbers for now. NASA POWER climate data and the '
          'optimizer are being connected.<br>Built by Team Athens for NASA Space Apps 2026.</div>')
