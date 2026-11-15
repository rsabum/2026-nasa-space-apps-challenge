"""Field Shift: Streamlit app (owner: Claude-Thomas, Team Athens)."""
import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import fake_model as model  # switch to `import model` when Robert's model.py is ready
from contract import (CONSTRAINTS, CROP_COLORS, CROP_ICONS, CROP_LABELS, CROPS, FARM,
                      WEIGHTS, baseline_plan, normalize_weights)
from rules import rule_problems

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
INK = "#E8EAED"      # text (dark theme; palette also in style.css and config.toml)
ACCENT = "#5DD6B0"   # the suggested plan
MUTED = "#8B93A1"    # the farmer's rotation
GRID = "#2A2F3A"     # chart gridlines
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


def bullet_list(items, limit=5):
    """Markdown bullets, at most `limit` of them, then '…and N more'."""
    lines = [f"- {item}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"- …and {len(items) - limit} more")
    return "\n".join(lines)


def totals(t):
    """The three headline numbers for a plan table: profit ($), water shortfall
    (acre-inches, area-weighted) and soil health change."""
    return (t["profit_usd"].sum(),
            (t["water_shortfall_mm"] * t["acres"]).sum() / 25.4,
            t["soil_score_change"].sum())


def why_this_plan_html(suggested, mine, plan_table, base_table, farm, scenario):
    """Up to three sentences on how the suggestion differs from the farmer's rotation
    and what that buys. Built only from model output, so it never claims more than
    the numbers show."""
    acres = {f["name"]: f["acres"] for f in farm["fields"]}
    changed = {f: sum(a != b for a, b in zip(crops, mine.get(f, []))) for f, crops in suggested.items()}
    n_changed = sum(changed.values())
    if n_changed == 0:
        body = ("The optimizer couldn't find anything better for your priorities and ground rules, "
                "so it suggests keeping your rotation as it is.")
    else:
        # Sentence 1: the field where the change is biggest (most years changed, then most acres).
        field = max(changed, key=lambda f: (changed[f], acres.get(f, 0)))
        new = " → ".join(CROP_LABELS.get(c, c) for c in suggested[field])
        old = " → ".join(CROP_LABELS.get(c, c) for c in mine[field])
        n_total = sum(len(c) for c in suggested.values())
        body = (f"It changes {n_changed} of your {n_total} field-years. The biggest change is on "
                f"<b>{html.escape(str(field))}</b> ({acres.get(field, 0):g} ac): {new}, "
                f"instead of your {old}. ")

        # Sentence 2: what the change buys, honest in both directions.
        p, w, s = totals(plan_table)
        bp, bw, bs = totals(base_table)
        profit = f"earns ${p - bp:,.0f} more" if p >= bp else f"earns ${bp - p:,.0f} less"
        water = (f"{bw - w:,.0f} acre-in less water shortfall" if w <= bw
                 else f"{w - bw:,.0f} acre-in more water shortfall")
        soil = ("better soil health" if s > bs else "lower soil health" if s < bs
                else "the same soil health")
        body += f"Over four years it {profit}, with {water} and {soil} ({s - bs:+.1f}). "

    # Sentence 3: average water need of the crops, weighted by acres.
    def need(t):
        return (t["water_need_mm"] * t["acres"]).sum() / t["acres"].sum()
    sn, bn = need(plan_table), need(base_table)
    if abs(sn - bn) >= 5:
        lead = "Because you're planning for a dry year, water need matters: its" if scenario == "dry" else "Its"
        body += (f"{lead} crops need {sn:.0f} mm of water a season on average, "
                 f"against {bn:.0f} mm for your rotation.")
    return f'<div class="fs-why"><div class="fs-why-title">Why this plan</div>{body}</div>'


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
             "pressure and wears the soil down. Last season's crop counts too.")
    min_soy = st.checkbox(
        "At least one soybean year per field", CONSTRAINTS["min_legume_years"] >= 1,
        help="Soybeans are a legume: they fix nitrogen in the soil, so the crop "
             "after them needs less fertilizer.")
    max_share = st.slider(
        "Most acres in one crop", 30, 100, int(CONSTRAINTS["max_crop_share"] * 100), step=5,
        format="%d%%",
        help="The largest share of your land any one crop can take in a single year, "
             "so one bad price or one bad season can't hit every acre. "
             "Set it at or above your biggest field's share, or no plan can meet it.")
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
constraints = {**CONSTRAINTS, "allowed_crops": allowed, "no_repeat": no_repeat,
               "min_legume_years": 1 if min_soy else 0, "max_crop_share": max_share / 100}

# ---------- Which weather the plan assumes (the "Plan for" switch) ----------
if scenario == "dry":
    show_html('<div class="fs-scenario fs-scenario-dry"><span class="fs-scenario-icon">🌵</span><div>'
              '<b>Planning for a dry year.</b> The suggestion and the four-year numbers assume '
              'growing-season rain like a dry season from the NASA record, so they favor crops '
              'that hold up when rain runs short. The 1981–2024 test below still runs every real year.'
              '</div></div>')
else:
    show_html('<div class="fs-scenario"><span class="fs-scenario-icon">☀️</span><div>'
              '<b>Planning for a typical year.</b> The suggestion and the four-year numbers assume '
              'average growing-season rain from the NASA record. The 1981–2024 test below runs '
              'every real year, wet and dry. Switch to <i>A dry year</i> in the sidebar to plan for drought.'
              '</div></div>')
season = "dry" if scenario == "dry" else "typical"

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
    my_problems = rule_problems(my_plan, farm, constraints)
    if my_problems:
        st.warning("**Your rotation breaks some of your ground rules.** We'll still test it "
                   "as you entered it.\n\n" + bullet_list(my_problems),
                   icon="⚠️")
    else:
        st.caption(":green[✓ Follows all your ground rules.]")

# ---------- Run the model ----------
try:
    plan_table = model.solve(farm, None, normalize_weights(weights), scenario, constraints)
    base_table = model.evaluate(my_plan, farm, None, scenario)
    suggested = model.table_to_plan(plan_table)
    bt_plan = model.backtest(suggested, farm)
    bt_base = model.backtest(my_plan, farm)
except Exception as e:  # never show a traceback to a judge
    st.error(f"The model could not run: {e}")
    st.stop()

# ---------- 01 · The plan ----------
with st.container(key="card_plan"):
    eyebrow("02 · The suggestion")
    st.subheader(f"Suggested rotation for a {season} year")
    st.caption("One crop per field per year. Read across for each field's next four seasons.")
    grid = (plan_table.pivot(index="field", columns="year", values="crop")
            .reindex(plan_table["field"].unique()))
    show_html(rotation_grid_html(grid))
    sug_problems = rule_problems(suggested, farm, constraints)
    if sug_problems:
        st.warning("**The suggestion couldn't meet every ground rule**, so these rules may not "
                   "fit together on your farm. Try loosening one in the sidebar.\n\n"
                   + bullet_list(sug_problems), icon="⚠️")
    show_html(why_this_plan_html(suggested, my_plan, plan_table, base_table, farm, scenario))

# ---------- The three key numbers, against the farmer's rotation ----------
p, w, s = totals(plan_table)
bp, bw, bs = totals(base_table)
c1, c2, c3 = st.columns(3)
with c1.container(key="m_profit"):
    st.metric(f"Net profit, 4 {season} years", f"${p:,.0f}", f"{p - bp:+,.0f} vs your rotation",
              help="Revenue minus seed, fertilizer and operating costs, across all fields.")
with c2.container(key="m_water"):
    st.metric(f"Water shortfall, 4 {season} years", f"{w:,.0f} acre-in", f"{w - bw:+,.0f} vs your rotation",
              delta_color="inverse",
              help="How far growing-season rain fell short of what the crops needed. "
                   "One acre-inch is an inch of water over one acre. Lower is better.")
with c3.container(key="m_soil"):
    st.metric(f"Soil health, 4 {season} years", f"{s:+.1f}", f"{s - bs:+.1f} vs your rotation",
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
            font=dict(family="Inter, sans-serif", color=MUTED),
            hoverlabel=dict(bgcolor="#1E222B", bordercolor=GRID, font=dict(color=INK)),
            xaxis=dict(gridcolor=GRID, zeroline=False),
            yaxis=dict(title="Whole-farm net profit", tickprefix="$", gridcolor=GRID, zeroline=False),
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
