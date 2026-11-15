"""Shared building blocks for the Field Shift pages (owner: Claude-Thomas).

Everything the three pages draw lives here, so they look the same and nothing is copied:
crop colours and icons, the rotation tiles, the field map, charts, chips, the "about this
plan" box, page headers, the shared state (your rotation, the optimizer's objective and
constraints), and the two independent calculations: evaluation() and optimization().

app.py is the entry point: it sets up the page, draws the farm setup in the sidebar,
and runs whichever page is open (views/home.py, views/evaluate.py, views/optimize.py).
"""
import html
import math
import urllib.parse
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import model  # Robert's optimizer. fake_model.py is the old stand-in: `import fake_model as model`
from contract import (CONSTRAINTS, CROP_LABELS, CROPS, DEFAULT_LIMITS, FARM, GOAL_HELP,
                      GOAL_OWN_LIMITS, GOALS, LIMIT_LABELS, WORST_SHARE, baseline_plan)

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
INK = "#E6E9F5"      # text (palette also in style.css and config.toml)
ACCENT = "#BFD7FF"   # the suggested plan: ice blue-white
MUTED = "#7D86AD"    # labels and the average line
MINE = "#5F79C9"     # the farmer's rotation: a deeper, quieter blue so the recommendation stands out
GRID = "rgba(79,139,255,0.10)"   # chart gridlines: faint blue, like a blueprint
DRY = "#FC3D21"      # dry seasons: NASA red
WET = "#4F8BFF"      # wet seasons: NASA blue, brightened
NORMAL = "#2A3466"   # middle seasons
# Crop colours for this app's theme: icy blue-whites stepping down to steel blue, all
# light enough for dark text. contract.py keeps the team's original colours (change
# that file only with the whole team); the app shows these. Always pair with icon + label.
CROP_COLORS = {
    "corn": "#F5C94C",          # golden yellow: ripe kernels
    "soybeans": "#6FD49B",      # fresh green: the legume that builds soil
    "winter_wheat": "#E9A866",  # wheat tan: mature grain
    "sorghum": "#E0879A",       # burgundy-rose: sorghum's reddish seed heads
}
# (The blue-white set from earlier today, if we go back: corn #EEF4FF, soybeans #B5D3F7,
#  winter wheat #93A9EE, sorghum #6F8FD8.)


def crop_word(crop):
    """A crop name in its own colour, with a small dot. For sentences on dark cards."""
    color = CROP_COLORS.get(crop, "#E6E9F5")
    return (f'<span class="fs-crop-word" style="color:{color}">'
            f'<i style="background:{color}"></i>{html.escape(CROP_LABELS.get(crop, crop))}</span>')


def crop_key_html():
    """A small legend: each crop's colour and icon."""
    return '<div class="fs-crop-key">' + "".join(
        f'<span style="--c:{CROP_COLORS[c]}">{CROP_SVG[c]}{CROP_LABELS[c]}</span>' for c in CROPS) + '</div>'


def crop_mix_chart(plans, farm):
    """Acres of each crop, year by year, for each plan side by side: stacked bars in the
    crop colours. Built only from the plans and field acres, so nothing is invented."""
    acres = {f["name"]: f["acres"] for f in farm["fields"]}
    fig = make_subplots(rows=1, cols=len(plans), shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=list(plans))
    for col, plan in enumerate(plans.values(), start=1):
        n_years = len(next(iter(plan.values())))     # each plan's own rotation length
        years = [f"Year {i + 1}" for i in range(n_years)]
        for crop in CROPS:
            ys = [sum(acres.get(f, 0) for f, cs in plan.items() if cs[i] == crop)
                  for i in range(n_years)]
            fig.add_trace(go.Bar(
                x=years, y=ys, name=CROP_LABELS[crop], legendgroup=crop, showlegend=(col == 1),
                marker=dict(color=CROP_COLORS[crop], line=dict(color="#0A0E1F", width=1.5)),
                hovertemplate=f"{CROP_LABELS[crop]}: %{{y:g}} ac<extra></extra>"), row=1, col=col)
    fig.update_layout(
        barmode="stack", height=270, margin=dict(l=0, r=0, t=28, b=0), bargap=0.32,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color=MUTED),
        hoverlabel=dict(bgcolor="#1A2148", bordercolor="#262F5E", font=dict(color=INK)),
        legend=dict(orientation="h", yanchor="bottom", y=-0.28, x=0))
    fig.update_annotations(font=dict(color=INK, size=13))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(title_text="Acres", row=1, col=1)
    return fig
# Our own crop icons: matching line art (24x24, drawn in the text colour, with a light
# duotone fill), so the app doesn't look like stock emoji. contract.py's CROP_ICONS
# emoji stay untouched for the team; dropdowns show the plain label, since they can't
# draw pictures.
_ICON = ('<svg class="fs-crop-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>')
_DUO = 'fill="currentColor" fill-opacity=".2"'
CROP_SVG = {
    "corn": _ICON.format(   # a cob in its husk
        f'<path d="M12 2.5c2.3 0 3.7 2.8 3.7 6.8S14.3 17 12 17s-3.7-3.7-3.7-7.7S9.7 2.5 12 2.5z" {_DUO}/>'
        '<path d="M12 3v13.5M8.6 7.2h6.8M8.4 10.4h7.2M8.9 13.6h6.2"/>'
        '<path d="M12 21.5c-3.4 0-6-2.9-6.6-8 2.4 1.1 4.1 3 4.9 5.6M12 21.5c3.4 0 6-2.9 6.6-8'
        '-2.4 1.1-4.1 3-4.9 5.6"/>'),
    "soybeans": _ICON.format(   # an open pod with three beans
        f'<path d="M4.5 19.5C3.3 16 4.6 11.6 8.3 8.2S16.6 3.4 19.5 4.5c1.2 3.5-.1 7.9-3.8 11.3'
        f'S7.4 20.6 4.5 19.5z" {_DUO}/>'
        '<g fill="currentColor" stroke="none"><circle cx="8.6" cy="15.4" r="1.8"/>'
        '<circle cx="12" cy="12" r="1.8"/><circle cx="15.4" cy="8.6" r="1.8"/></g>'
        '<path d="M19.5 4.5l2-2.2M4.5 19.5c-.9.4-1.6 1.2-2 2.2"/>'),
    "winter_wheat": _ICON.format(   # a wheat head with awns
        '<path d="M12 22V1.8M10.2 6.4L8.4 3.4M13.8 6.4l1.8-3"/>'
        f'<g {_DUO}>' + "".join(
            f'<ellipse cx="{x}" cy="{y}" rx="1.5" ry="2.6" transform="rotate({a} {x} {y})"/>'
            for y in (9, 12.8, 16.6) for x, a in ((9.9, -35), (14.1, 35))) + '</g>'),
    "sorghum": _ICON.format(   # a round seed head on a leafy stalk
        f'<ellipse cx="12" cy="6.8" rx="4.2" ry="5" {_DUO}/>'
        '<g fill="currentColor" stroke="none"><circle cx="12" cy="3.6" r="1.2"/>'
        '<circle cx="10" cy="5.8" r="1.2"/><circle cx="14" cy="5.8" r="1.2"/>'
        '<circle cx="12" cy="7.9" r="1.2"/><circle cx="9.8" cy="9.6" r="1.1"/>'
        '<circle cx="14.2" cy="9.6" r="1.1"/></g><path d="M12 11.8V22"/>'
        f'<path d="M12 17.2c3-.4 5.9-2.4 7.4-5.6-3.1.3-5.9 2.1-7.4 5.6zM12 20c-2.6-.4-5-2-6-4.6'
        f' 2.6.3 4.8 1.8 6 4.6z" {_DUO}/>'),
}
MAP_WIDTH = 266     # pixels the field map gets inside the sidebar


def crop_name(crop):
    """'winter_wheat' -> 'Winter wheat'. Display only (dropdowns and tables)."""
    return CROP_LABELS.get(crop, crop)


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
            body += (f'<div class="rg-cell" style="background:{CROP_COLORS.get(crop, "#EEEEEE")};'
                     f'--cc:{CROP_COLORS.get(crop, "#EEEEEE")}" '
                     f'title="{html.escape(str(field))}, year {year}: {label}">'
                     f'<span class="rg-icon">{CROP_SVG.get(crop, "")}</span>'
                     f'<span class="rg-name">{label}</span></div>')
    columns = f"minmax(4.5rem, 6rem) repeat({len(grid.columns)}, 1fr)"
    return f'<div class="rg" style="grid-template-columns:{columns}">{head}{body}</div>'


def year_label(i):
    """0 -> 'Year 1'. Column names for the rotation editor."""
    return f"Year {i + 1}"


def water_stress(table):
    """How short of water the plan runs: inches of shortfall per acre per season,
    and a plain label. Thresholds: under 1 inch Low, 1-3 Moderate, over 3 High."""
    acres = table.groupby("field")["acres"].first().sum()
    seasons = table["year"].nunique()
    inches = (table["water_shortfall_mm"] * table["acres"]).sum() / 25.4 / acres / seasons
    level = "Low" if inches < 1 else "Moderate" if inches < 3 else "High"
    return level, inches


def plan_chips_html(table, n_broken):
    """The chips under the recommended plan: does it meet the ground rules, and how water-
    stressed is it. Stand-alone: the optimizer never compares with the farmer's rotation."""
    rules = ('<span class="fs-chip fs-chip-good">✓ Meets your ground rules</span>' if n_broken == 0 else
             f'<span class="fs-chip fs-chip-bad">⚠ Breaks {n_broken} rule{"s" if n_broken > 1 else ""}</span>')
    level, inches = water_stress(table)
    stress = (f'<span class="fs-chip fs-stress-{level.lower()}" title="Shortfall per acre per '
              f'season. Under 1 in: Low, 1–3 in: Moderate, over 3 in: High.">💧 Water stress: '
              f'<b>{level}</b> · {inches:.1f} in/acre</span>')
    return f'<div class="fs-chips">{rules}{stress}</div>'


def bullet_list(items, limit=5):
    """Markdown bullets, at most `limit` of them, then '…and N more'."""
    lines = [f"- {item}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"- …and {len(items) - limit} more")
    return "\n".join(lines)


def totals(t):
    """The three headline numbers for a plan table, PER YEAR (averaged over the rotation's
    cycle, so a 2-year and a 5-year rotation compare fairly): profit ($/yr), water
    shortfall (acre-inches/yr) and soil health (points per acre per year, area-weighted, so
    a big field counts more). The optimizer measures them the same way."""
    acres = t.groupby("field")["acres"].first().sum()
    years = t["year"].nunique()
    return (t["profit_usd"].sum() / years,
            (t["water_shortfall_mm"] * t["acres"]).sum() / 25.4 / years,
            (t["soil_score_change"] * t["acres"]).sum() / acres / years)


def about_plan_html(plan, table, farm):
    """A few plain sentences about the recommended plan, built only from model output:
    the biggest field's cycle, what it earns and costs in water and soil per year, rye, and
    how much water its crops need. Stand-alone: no comparison with the farmer's rotation."""
    acres = {f["name"]: f["acres"] for f in farm["fields"]}
    years = len(next(iter(plan.values())))
    field = max(plan, key=lambda f: acres.get(f, 0))
    cycle = " → ".join(crop_word(c) for c in plan[field])
    p, w, s = totals(table)
    body = (f"A {years}-year rotation that repeats. On your biggest field, "
            f"<b>{html.escape(str(field))}</b> ({acres.get(field, 0):g} ac): {cycle}. "
            f"Per year it earns <b>${p:,.0f}</b>, with {w:,.0f} acre-in of water shortfall and "
            f"soil health {s:+.2f}. ")
    if "cover" in table and table["cover"].any():
        n_rye = int(table["cover"].sum())
        body += (f"It sows a cereal-rye cover after {n_rye} field-year{'s' if n_rye > 1 else ''} "
                 "(see the table at the bottom) to build soil. ")
    need = (table["water_need_mm"] * table["acres"]).sum() / table["acres"].sum()
    body += f"Its crops need {need:.0f} mm of water a season on average."
    return f'<div class="fs-why"><div class="fs-why-title">About this plan</div>{body}</div>'


def icon_uri(crop):
    """The crop's line icon as a data URI, for CSS masks (buttons and tags can't hold SVG)."""
    icon = CROP_SVG[crop].replace('<svg class="fs-crop-icon"', '<svg xmlns="http://www.w3.org/2000/svg"')
    return "data:image/svg+xml," + urllib.parse.quote(icon, safe=" =:/,.-()")


def crop_tag_css():
    """Give each tag in "Crops you'd grow" its crop's colour and icon. Streamlit marks each
    tag with the crop's label (title="Corn"), which is what the selectors match on. Tags are
    [data-baseweb="tag"] on older Streamlit and [data-tag] on newer; both are matched."""
    rules = ""
    for crop in CROP_SVG:
        uri = icon_uri(crop)
        tag = (f'.st-key-allowed_crops :is([data-baseweb="tag"], [data-tag])'
               f':has(span[title="{CROP_LABELS[crop]}"])')
        rules += (f'{tag} {{background: {CROP_COLORS[crop]} !important;}}'
                  f'{tag}::before {{-webkit-mask-image: url("{uri}"); mask-image: url("{uri}");}}')
    return f"<style>{rules}</style>"


def cell_css():
    """Colour the rotation picker: each cell tile (key "cell-<crop>-…") and each crop choice
    in its menu (key "pick-<crop>-…") gets its crop's colour and line icon."""
    rules = ""
    for crop in CROP_SVG:
        uri = icon_uri(crop)
        for kind in ("cell", "pick"):
            sel = f'[class*="st-key-{kind}-{crop}-"] button'
            rules += (f'{sel} {{background: {CROP_COLORS[crop]} !important; '
                      f'border-color: {CROP_COLORS[crop]} !important; color: var(--on-crop) !important;}}'
                      f'{sel}::before {{content: ""; flex: none; width: 1.15em; height: 1.15em; '
                      f'margin-right: .45em; background: currentColor; '
                      f'-webkit-mask: url("{uri}") center / contain no-repeat; '
                      f'mask: url("{uri}") center / contain no-repeat;}}')
    return f"<style>{rules}</style>"


def faq_context(farm, mine, rec):
    """What the farmer is looking at, for the assistant: the evaluator's rotation and the
    optimizer's plan, each on its own (the two tools are independent). Only numbers the app
    shows. `mine` = evaluation(), `rec` = optimization() (or None)."""
    def rotation_text(plan):
        return "; ".join(f"{f}: " + " → ".join(CROP_LABELS[c] for c in cs) for f, cs in plan.items())

    bt = mine["bt"]
    p, w, s = totals(mine["table"])
    worst = bt.loc[bt["total_profit_usd"].idxmin()]
    ctx = {
        "farm_location": f"lat {farm['lat']}, lon {farm['lon']}" if "lat" in farm else "central Illinois",
        "fields": ", ".join(f"{f['name']} ({f['acres']:g} ac, {f['soil']})" for f in farm["fields"]),
        "total_acres": f"{sum(f['acres'] for f in farm['fields']):g}",
        "weather": "every number averages all 44 growing seasons, 1981-2024, wet and dry",
        "your_rotation": f"{len(next(iter(mine['plan'].values())))} years, repeating: " + rotation_text(mine["plan"]),
        "your_profit_per_year": money(p),
        "your_water_shortfall_per_year": f"{w:,.0f} acre-inches",
        "your_soil_health_per_year": f"{s:+.2f}",
        "seasons_tested": len(bt),
        "your_profitable_seasons": f"{int((bt['total_profit_usd'] > 0).sum())} of {len(bt)}",
        "your_toughest_season": f"{int(worst['year'])} ({money(worst['total_profit_usd'])})",
        "driest_season": mine["driest"],
        "data_status": ("the optimizer is real, but it runs on synthetic sample weather and crop "
                        "data until the NASA POWER data is connected"),
    }
    if rec:
        rp, rw, rs = totals(rec["table"])
        rbt = rec["bt"]
        ctx.update({
            "optimizer_objective": f"{GOALS[rec['goal']]}: {GOAL_HELP[rec['goal']]}",
            "optimizer_limits": "; ".join(limit_text(k, v) for k, v in rec["limits"].items()) or "none",
            "optimizer_limits_not_met": "; ".join(rec["table"].attrs.get("unmet", [])) or "none",
            "recommended_rotation": f"{rec['years']} years, repeating: " + rotation_text(rec["plan"]),
            "recommended_profit_per_year": money(rp),
            "recommended_water_shortfall_per_year": f"{rw:,.0f} acre-inches",
            "recommended_soil_health_per_year": f"{rs:+.2f}",
            "recommended_profitable_seasons": f"{int((rbt['total_profit_usd'] > 0).sum())} of {len(rbt)}",
        })
    return ctx


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
            irrigated = str(getattr(f, "irrigated", False)) == "True"   # also handles numpy bools and blanks
            soil = html.escape(str(f.soil)) + (" · irrigated" if irrigated else "")
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
                f'<span class="fm-icon">{CROP_SVG.get(f.last_crop, "")}</span></div>'
                f'<div class="fm-soil">{soil}</div></div></div>')
            n += 1
        out += f'<div class="fm-row" style="flex-grow:{row_acres:g}">{plots}</div>'
    summary = (f'<div class="fm-sum"><b>{total:g}</b> acres across <b>{len(fields)}</b> '
               f'field{"" if len(fields) == 1 else "s"}</div>')
    return f'{summary}<div class="fm" style="height:{height}px">{out}</div>'



# ================================================================ shared state across pages
# Streamlit wipes a widget's value when you switch to a page that doesn't draw it. So each
# page-only widget (weather switch, goal, limits) keeps a copy of its value under the same
# key with a leading "_" ("goal" -> "_goal"), which Streamlit never wipes:
#   remember(key, default)  before drawing the widget: give it back its saved value
#   on_change=save, args=(key,)  when the farmer changes it: save the new value
# Everything else reads the "_" copy. Your rotation is stored under "my_plan", and its
# length under "_rot_len" (the optimizer's search length under "_opt_len").
def keep_state():
    """Called by app.py at the top of every run: defaults for the saved values."""
    ss = st.session_state
    ss.setdefault("_goal", "max_profit")
    ss.setdefault("_worst_share_sel", WORST_SHARE)


def remember(key, default):
    """Before drawing widget `key`: restore its value from the saved copy."""
    ss = st.session_state
    ss.setdefault("_" + key, default)
    ss[key] = ss["_" + key]


def save(key):
    """Widget on_change callback: keep a copy of the new value."""
    st.session_state["_" + key] = st.session_state[key]


def saved(key, default=None):
    """A widget's last value, from any page."""
    return st.session_state.get("_" + key, default)


def rotation_length():
    """The farmer's rotation length (years in the repeating cycle), as set in the evaluator."""
    return int(saved("rot_len", 2))


def search_length():
    """The rotation length the optimizer searches (its own choice, 4 years to start)."""
    return int(saved("opt_len") or 4)


def save_search_length():
    """Optimizer length switch callback (ignores un-selecting the active option)."""
    if st.session_state.get("opt_len") is not None:
        save("opt_len")


def with_years(farm, years):
    return {**farm, "years": int(years)}


def resize_plan(plan, years):
    """Each field's rotation cut to `years`, or lengthened by alternating corn and soybeans
    after its last crop (the farmer then clicks the new cells to change them)."""
    out = {}
    for field, crops in plan.items():
        crops = list(crops)[:years]
        while len(crops) < years:
            crops.append("soybeans" if crops and crops[-1] == "corn" else "corn")
        out[field] = crops
    return out


def fit_plan(plan, farm):
    """`plan` fitted to the current fields and farm["years"]: fields it doesn't cover (new,
    renamed, or an unknown crop) get the plain corn-soy rotation; others are resized."""
    base = baseline_plan(farm)
    out = {}
    for f in farm["fields"]:
        crops = (plan or {}).get(f["name"])
        ok = crops is not None and len(crops) > 0 and all(c in CROPS for c in crops)
        out[f["name"]] = resize_plan({0: crops}, farm["years"])[0] if ok else base[f["name"]]
    return out


def current_plan(farm):
    """The farmer's rotation at their chosen length: what they set in the evaluator, else
    corn-soy. `farm` is the shared farm; its years are replaced by the farmer's length."""
    return fit_plan(st.session_state.get("my_plan"), with_years(farm, rotation_length()))


def set_length():
    """Rotation-length switch callback: save it and resize the rotation to match."""
    if st.session_state.get("rot_len") is None:        # clicking the active option un-selects it:
        return                                         # keep the old length (restored next run)
    save("rot_len")
    if "my_plan" in st.session_state:
        st.session_state["my_plan"] = resize_plan(st.session_state["my_plan"], rotation_length())


def set_cell(field, t, crop):
    """Cell-menu callback: plant `crop` on `field` in year t+1 of the rotation."""
    farm = st.session_state["_farm_ctx"]["farm"]
    plan = current_plan(farm)
    plan[field][t] = crop
    st.session_state["my_plan"] = plan
    st.session_state["applied"] = False


def apply_plan(plan):
    """"Use this rotation": make the recommendation the farmer's rotation (and its length).
    The optimizer page then switches to the evaluator. The only link between the two tools."""
    st.session_state["my_plan"] = plan
    st.session_state["_rot_len"] = len(next(iter(plan.values())))
    st.session_state["applied"] = True


def reset_plan():
    """Button callback: go back to the plain corn-soy rotation, at the current length."""
    st.session_state.pop("my_plan", None)
    st.session_state["applied"] = False


def rotation_picker(farm, plan):
    """The rotation as a grid of crop tiles: one row per field, one column per year of the
    cycle. Click a tile to open a small menu of crops; pick one to plant it there.
    Tiles and choices are coloured by cell_css() through their container keys."""
    years = len(next(iter(plan.values())))
    widths = [1.1] + [1] * years
    head = st.columns(widths)
    head[0].markdown('<div class="rp-head">Field</div>', unsafe_allow_html=True)
    for t in range(years):
        head[t + 1].markdown(f'<div class="rp-head">Year {t + 1}</div>', unsafe_allow_html=True)
    for fi, f in enumerate(farm["fields"]):
        name = str(f["name"])
        row = st.columns(widths, vertical_alignment="center")
        row[0].markdown(f'<div class="rp-field"><b>{html.escape(name)}</b>'
                        f'<small>{f["acres"]:g} ac</small></div>', unsafe_allow_html=True)
        for t, crop in enumerate(plan[name]):
            with row[t + 1].container(key=f"cell-{crop}-{fi}-{t}"):
                with st.popover(crop_name(crop), use_container_width=True,
                                help=f"{name}, year {t + 1}: click to change the crop"):
                    st.markdown(f"**{html.escape(name)} · Year {t + 1}**")
                    for c in CROPS:
                        with st.container(key=f"pick-{c}-{fi}-{t}"):
                            st.button(crop_name(c) + ("  ✓" if c == crop else ""),
                                      key=f"pickbtn_{fi}_{t}_{c}", use_container_width=True,
                                      on_click=set_cell, args=(name, t, c))
    show_html(f'<div class="rp-cycle">↻ The rotation repeats: after year {years} comes year 1 again.</div>')


def farm_ready():
    """The farm from the left panel, or None (with a message) if there are no fields yet."""
    ctx = st.session_state.get("_farm_ctx")
    if ctx is None or not ctx["farm"]["fields"]:
        st.info("Add at least one field under **Your fields** in the left panel to get started.")
        return None
    return ctx


# ================================================================ ground rules (optimizer only)
# The farmer's own rotation is what they plan to plant, so it isn't checked against rules;
# the rules only limit which rotations the optimizer may suggest. Saved like the goal.
RULE_HELP = {
    "allowed_crops": "The optimizer only suggests crops on this list.",
    "no_repeat": "Planting the same crop two years running builds pest and disease pressure "
                 "and wears the soil down. Counts last season → year 1 and, since the rotation "
                 "repeats, the last year → year 1.",
    "min_soy": "Soybeans are a legume: they fix nitrogen in the soil, so the crop after them "
               "needs less fertilizer.",
    "max_share": "The largest share of your land any one crop can take in a single year, so one "
                 "bad price or one bad season can't hit every acre. Set it at or above your "
                 "biggest field's share, or no plan can meet it.",
}


def read_rules():
    """The ground rules as last set on the optimizer page (or the team defaults)."""
    return {**CONSTRAINTS,
            "allowed_crops": list(saved("allowed_crops", list(CONSTRAINTS["allowed_crops"]))),
            "no_repeat": bool(saved("no_repeat", CONSTRAINTS["no_repeat"])),
            "min_legume_years": 1 if saved("min_soy", CONSTRAINTS["min_legume_years"] >= 1) else 0,
            "max_crop_share": saved("max_share", int(CONSTRAINTS["max_crop_share"] * 100)) / 100}


def rules_controls():
    """The ground-rule widgets (inside the optimizer's Constraints card; values saved with
    remember/save). Stacked, because they already sit in a column."""
    remember("allowed_crops", list(CONSTRAINTS["allowed_crops"]))
    st.multiselect("Crops you'd grow", CROPS, key="allowed_crops", format_func=crop_name,
                   on_change=save, args=("allowed_crops",), help=RULE_HELP["allowed_crops"])
    remember("max_share", int(CONSTRAINTS["max_crop_share"] * 100))
    st.slider("Most acres in one crop", 30, 100, step=1, format="%d%%", key="max_share",
              on_change=save, args=("max_share",), help=RULE_HELP["max_share"])
    remember("no_repeat", CONSTRAINTS["no_repeat"])
    st.checkbox("No back-to-back crops", key="no_repeat", on_change=save, args=("no_repeat",),
                help=RULE_HELP["no_repeat"])
    remember("min_soy", CONSTRAINTS["min_legume_years"] >= 1)
    st.checkbox("At least one soybean year per field", key="min_soy", on_change=save,
                args=("min_soy",), help=RULE_HELP["min_soy"])


# ================================================================ objective and limits
LIMIT_HELP = {
    "profit_min": "The plan must earn at least this much a year, on average over 1981–2024.",
    "worst_profit_min": "Average profit across your worst seasons (the worst 10% of 1981–2024 "
                        "by default) can't fall below this.",
    "shortfall_max": "Water the crops lack (need minus rain and soil water), farm total per year. "
                     "Lower is safer in a drought.",
    "irrigation_max": "No season may pump more than this across your irrigated fields.",
    "soil_min": "Soil-health points per acre per year: residue, legumes, small grains, rye.",
    "production_min": "Bushels a year the plan must still harvest of each crop you pick here "
                      "(for feed or contracts).",
}
# Slider step and display format per limit (values are farm totals per year).
LIMIT_SPEC = {
    "profit_min": (100, "$%d a year"),
    "worst_profit_min": (100, "$%d a year"),
    "shortfall_max": (1, "%d acre-in a year"),
    "irrigation_max": (1, "%d acre-in"),
    "soil_min": (0.01, "%.2f a year"),
    "production_min": (100, "%d bu a year"),
}


def read_objective():
    """The goal and bad-years share, as last set on the optimizer page (or defaults)."""
    goal = saved("goal") if saved("goal") in GOALS else "max_profit"
    worst = saved("worst_share_sel", WORST_SHARE) if goal == "max_worst_profit" else WORST_SHARE
    return goal, worst


def objective_controls():
    """Card 01 on the optimizer: the goal picker (and, for the bad-year goal, which seasons
    count as bad). Values are saved with remember/save so they survive page changes."""
    remember("goal", "max_profit")
    st.selectbox("Your objective", list(GOALS), format_func=GOALS.get, key="goal",
                 on_change=save, args=("goal",),
                 help="The optimizer pursues one objective. Everything else is a constraint below.")
    goal = st.session_state["goal"]
    st.caption(GOAL_HELP[goal])
    if goal == "max_worst_profit":
        remember("worst_share_sel", WORST_SHARE)
        st.select_slider(
            "Bad years to protect", options=[1 / 44, 0.10, 0.25], key="worst_share_sel",
            on_change=save, args=("worst_share_sel",),
            format_func=lambda v: "Worst single season" if v < 0.05 else f"Worst {v:.0%} of seasons",
            help="Which seasons count as bad years: the plan's average profit across them is "
                 "what this objective makes as high as possible.")


def reachable(ctx):
    """What the farm can reach on each limit's measure (slider ranges), for the optimizer's
    rotation length and ground rules. Empty when the model doesn't offer it (fake_model)."""
    if not hasattr(model, "limit_ranges"):
        return {}
    _, worst = read_objective()
    return model.limit_ranges(with_years(ctx["farm"], search_length()), None, "average",
                              {**read_rules(), "worst_share": worst})


def _offered_limits(goal, ranges, any_irrigated):
    """Limits that make sense for this goal (never the goal's own measure)."""
    return [k for k in LIMIT_LABELS
            if k not in GOAL_OWN_LIMITS[goal] and k in ranges
            and not (k == "irrigation_max" and not any_irrigated)
            and not (k == "production_min" and not ranges.get(k))]


def _slider_range(lo, hi, key):
    """Slider ends snapped inward to the limit's step, so both ends are reachable (never
    empty: a range narrower than one step gets one step)."""
    step = LIMIT_SPEC[key][0]
    lo, hi = math.ceil(lo / step - 1e-9) * step, math.floor(hi / step + 1e-9) * step
    if hi <= lo:
        hi = lo + step
    if step >= 1:
        return int(lo), int(hi), int(step)
    return round(lo, 2), round(hi, 2), step


def _start(goal, key, lo, hi, step):
    """Where a limit's slider starts: DEFAULT_LIMITS gives a position along the range;
    limits a goal doesn't switch on start at their loosest end."""
    pos = DEFAULT_LIMITS[goal].get(key, 1.0 if key.endswith("_max") else 0.0)
    v = round((lo + pos * (hi - lo)) / step) * step
    return int(v) if isinstance(step, int) else round(v, 2)


def _limit_slots(goal, ranges, any_irrigated):
    """(limit key, crop or None, saved-value key, lo, hi, step) for every slider."""
    for key in _offered_limits(goal, ranges, any_irrigated):
        if key == "production_min":
            for crop, (lo, hi) in ranges[key].items():
                yield (key, crop, f"cap_{goal}_{key}_{crop}") + _slider_range(lo, hi, key)
        else:
            yield (key, None, f"cap_{goal}_{key}") + _slider_range(*ranges[key], key)


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


def read_limits(goal, ranges, any_irrigated):
    """The absolute limits as last set on the optimizer page (defaults per DEFAULT_LIMITS),
    each kept inside what the farm can currently reach."""
    limits = {}
    for key, crop, vkey, lo, hi, step in _limit_slots(goal, ranges, any_irrigated):
        if not saved(f"cap_on_{goal}_{key}", key in DEFAULT_LIMITS[goal]):
            continue
        v = _clamp(saved(vkey, _start(goal, key, lo, hi, step)), lo, hi)
        if crop is None:
            limits[key] = v
        else:
            limits.setdefault(key, {})[crop] = v
    return limits


def limit_controls(goal, ranges, any_irrigated):
    """The limit checkboxes and sliders (inside card 02). Each slider spans what the farm can
    reach; its saved value is kept inside that range as fields, rules or length change."""
    ss = st.session_state
    shown = set()
    for key, crop, vkey, lo, hi, step in _limit_slots(goal, ranges, any_irrigated):
        on_key = f"cap_on_{goal}_{key}"
        if key not in shown:
            shown.add(key)
            remember(on_key, key in DEFAULT_LIMITS[goal])
            st.checkbox(LIMIT_LABELS[key], key=on_key, help=LIMIT_HELP[key],
                        on_change=save, args=(on_key,))
        if not ss[on_key]:
            continue
        remember(vkey, _start(goal, key, lo, hi, step))
        ss[vkey] = _clamp(ss[vkey], lo, hi)
        label = crop_name(crop) if crop else LIMIT_LABELS[key]
        st.slider(label, lo, hi, step=step, format=LIMIT_SPEC[key][1], key=vkey,
                  label_visibility="visible" if crop else "collapsed",
                  on_change=save, args=(vkey,))


def limit_text(key, value):
    """'Profit at least $45,000 a year' for the assistant and messages."""
    if key == "production_min":
        return "; ".join(f"{LIMIT_LABELS[key]} {v:,.0f} bu of {crop_name(c)} a year" for c, v in value.items())
    if key in ("profit_min", "worst_profit_min"):
        return f"{LIMIT_LABELS[key]} {money(value)} a year"
    if key == "soil_min":
        return f"{LIMIT_LABELS[key]} {value:+.2f} a year"
    return f"{LIMIT_LABELS[key]} {value:,.0f} acre-in" + (" a year" if key == "shortfall_max" else "")


# ================================================================ the two calculations
# The evaluator and the optimizer are independent: neither reads the other's results.
# The one link is the optimizer's "Use this rotation" button (apply_plan + switch page).
def evaluation(ctx):
    """The farmer's rotation (evaluator): scored and backtested on 1981-2024 weather."""
    farm = with_years(ctx["farm"], rotation_length())
    plan = current_plan(farm)
    bt = model.backtest(plan, farm)
    return {"farm": farm, "plan": plan, "table": model.evaluate(plan, farm, None, "average"),
            "bt": bt, "driest": int(bt.loc[bt["growing_season_rain_mm"].idxmin(), "year"])}


def optimization(ctx):
    """The optimizer's recommendation for its objective and constraints, scored and
    backtested the same way. Nothing here depends on the farmer's own rotation."""
    farm = with_years(ctx["farm"], search_length())
    goal, worst = read_objective()
    ranges = reachable(ctx)
    limits = read_limits(goal, ranges, ctx["any_irrigated"])
    constraints = {**read_rules(), "worst_share": worst}
    table = model.solve(farm, None, goal, "average", {**constraints, "limits": limits})
    plan = model.table_to_plan(table)
    covers = model.table_to_covers(table) if hasattr(model, "table_to_covers") else None
    bt = model.backtest(plan, farm, covers=covers) if covers else model.backtest(plan, farm)
    return {"farm": farm, "goal": goal, "limits": limits, "ranges": ranges,
            "constraints": constraints, "years": search_length(), "table": table, "plan": plan,
            "bt": bt, "driest": int(bt.loc[bt["growing_season_rain_mm"].idxmin(), "year"])}


def or_stop(calc, ctx):
    """Run evaluation/optimization, or show a friendly error and stop the page."""
    try:
        return calc(ctx)
    except Exception as e:  # never show a traceback to a judge
        st.error(f"The model could not run: {e}")
        st.stop()


# ================================================================ page furniture
def load_styles():
    """All the styling lives in style.css; colours for Streamlit's widgets in config.toml."""
    show_html(f"<style>{(HERE / 'style.css').read_text()}</style>")
    show_html(crop_tag_css())
    show_html(cell_css())


def anchor(name):
    """An invisible marker the logo directory can jump to."""
    show_html(f'<div id="{name}" class="fs-anchor"></div>')


# The logo doubles as a directory of the open page: click it and a panel lists its parts.
# Links jump within the page only (a plain link to another page would reload the app and
# lose your inputs; the page menu in the left panel switches pages safely).
SETUP_GROUP = ("Set up", "In the left panel (open it with » if hidden)", [
    ("fields", "🗺️", "Your fields", "Acres, soil, irrigation, last crop"),
])


def directory_html(logo, groups):
    """The clickable logo and the directory panel that opens under it."""
    out = ""
    for title, note, items in groups:
        links = "".join(
            f'<a class="fs-dir-link" href="#{anchor_id}"><span class="fs-dir-icon">{icon}</span>'
            f'<span><b>{name}</b><small>{desc}</small></span></a>'
            for anchor_id, icon, name, desc in items)
        out += (f'<div class="fs-dir-group"><div class="fs-dir-head">{title}'
                f'<span>{note}</span></div>{links}</div>')
    return (f'<details class="fs-dir"><summary title="Open the page directory" '
            f'aria-label="Field Shift menu: jump to a section">{logo}'
            f'<span class="fs-dir-hint">☰</span></summary>'
            f'<nav class="fs-dir-panel"><div class="fs-dir-top">Jump to'
            f'<span>Click the logo again to close</span></div>{out}</nav></details>')


def page_header(crumb, title, tag, groups, compact=False):
    """Top bar, then the hero: logo (directory), title, tagline and badges."""
    logo = (ASSETS / "logo.svg").read_text()
    show_html(
        '<div class="fs-topbar">'
        f'<div class="fs-crumb">Field Shift<span>›</span><b>{crumb}</b></div>'
        f'<div class="fs-status"><span class="fs-live"><i></i>Lat {FARM["lat"]} · Lon {FARM["lon"]}</span>'
        '<span class="fs-live">Sample data</span></div></div>'
        f'<div class="fs-hero{" fs-hero-compact" if compact else ""}">' + directory_html(logo, groups) +
        '<div><div class="fs-hero-sub">NASA <em>climate</em>-powered crop rotation planner</div>'
        f'<div class="fs-hero-title">{title}</div>'
        f'<div class="fs-hero-tag">{tag}</div></div>'
        '<div class="fs-hero-badges">'
        '<span class="fs-badge fs-badge-data">🛰️ NASA POWER weather · 1981–2024</span>'
        '<span class="fs-badge">Team Athens</span></div></div>')


def money(v):
    """$12,345 or −$8,208 (minus sign before the dollar sign)."""
    return f"{'−' if v < 0 else ''}${abs(v):,.0f}"


def metric_row(table):
    """Profit, water shortfall and soil health per year for one plan."""
    p, w, s = totals(table)
    anchor("numbers")
    c1, c2, c3 = st.columns(3)
    with c1.container(key="m_profit"):
        st.metric("Net profit per year", f"${p:,.0f}",
                  help="Revenue minus seed, fertilizer, rye and pumping costs, across all fields: "
                       "the average over the rotation's years and over 1981–2024 weather.")
    with c2.container(key="m_water"):
        st.metric("Water shortfall per year", f"{w:,.0f} acre-in",
                  help="How far rain and stored soil water fell short of what the crops needed. "
                       "One acre-inch is an inch of water over one acre. Lower is better.")
    with c3.container(key="m_soil"):
        st.metric("Soil health per year", f"{s:+.2f}",
                  help="Soil-health points per acre per year: residue, nitrogen from legumes, "
                       "small grains and rye cover. Higher is better.")


def ring_html(n, total, label):
    """The big 'N / 44' ring."""
    pct = 100 * n / total
    return (f'<div class="fs-stat"><div class="fs-ring" style="--pct:{pct:.1f}"><div class="fs-ring-inner">'
            f'<div class="fs-stat-num">{n}<small> / {total}</small></div>'
            f'<div class="fs-stat-pct">{pct:.0f}% OF SEASONS</div></div></div>'
            f'<div class="fs-stat-label">{label}</div></div>')


def backtest_chart(mine, rec=None, name="Your rotation"):
    """Profit per season (top panel) over NASA growing-season rain (bottom), 1981-2024,
    with a replay: ▶ plays the seasons one at a time and a slider jumps to any year.
    `mine` is one rotation's backtest, labelled `name`. (`rec` draws a second line for a
    head-to-head; the pages don't use it, since the two tools are independent.)"""
    years = list(mine["year"])
    rain = list(mine["growing_season_rain_mm"])
    mm = mine["growing_season_rain_mm"]
    driest = int(mine.loc[mm.idxmin(), "year"])
    lines = ([(name, list(mine["total_profit_usd"]), ACCENT, 3, True)] if rec is None else
             [("Your rotation", list(mine["total_profit_usd"]), MINE, 2, False),
              ("Recommendation", list(rec["total_profit_usd"]), ACCENT, 3, True)])
    floor = min(min(y) for _, y, *_ in lines)
    floor -= 0.08 * abs(floor) + 1
    top = max(max(y) for _, y, *_ in lines)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.66, 0.34], vertical_spacing=0.07)
    animated = []   # (trace index, data for the frame at season k)
    for name, ys, color, width, star in lines:
        if star:   # the starring line: soft fill down to the floor, plus a glow
            fig.add_trace(go.Scatter(x=years, y=[floor] * len(years), line=dict(width=0),
                                     hoverinfo="skip", showlegend=False), row=1, col=1)
            animated.append((len(fig.data) - 1, lambda k: [floor] * (k + 1)))
        fig.add_trace(go.Scatter(
            x=years, y=ys, name=name, line=dict(color=color, width=width, shape="spline", smoothing=0.6),
            fill="tonexty" if star else None, fillcolor="rgba(191,215,255,0.12)" if star else None,
            hovertemplate="$%{y:,.0f}"), row=1, col=1)
        animated.append((len(fig.data) - 1, lambda k, ys=ys: ys[:k + 1]))
        if star:
            fig.add_trace(go.Scatter(x=years, y=ys, hoverinfo="skip", showlegend=False,
                                     line=dict(color="rgba(191,215,255,0.15)", width=7, shape="spline",
                                               smoothing=0.6)), row=1, col=1)
            animated.append((len(fig.data) - 1, lambda k, ys=ys: ys[:k + 1]))

    # Rain bars: driest quarter of seasons NASA red, wettest quarter NASA blue, the rest navy.
    low, high = mm.quantile(0.25), mm.quantile(0.75)
    fig.add_trace(go.Bar(x=years, y=rain, name="Growing-season rain",
                         marker=dict(color=[DRY if v <= low else WET if v >= high else NORMAL for v in mm]),
                         hovertemplate="%{y:.0f} mm rain", showlegend=False), row=2, col=1)
    animated.append((len(fig.data) - 1, lambda k: rain[:k + 1]))
    fig.add_hline(y=mm.mean(), line=dict(color=MUTED, width=1, dash="dot"), row=2, col=1)
    fig.add_vrect(x0=driest - 0.5, x1=driest + 0.5, fillcolor=DRY, opacity=0.12, line_width=0)

    # A marker on each line at the current season (empty until the replay runs).
    fig.add_trace(go.Scatter(x=[], y=[], mode="markers", hoverinfo="skip", showlegend=False,
                             marker=dict(size=[10, 13][-len(lines):], color=[c for _, _, c, *_ in lines],
                                         line=dict(color="#0A0E1F", width=2))), row=1, col=1)
    marker = len(fig.data) - 1

    driest_note = dict(x=driest + 0.6, y=0.995, xref="x", yref="paper", xanchor="left", yanchor="top",
                       showarrow=False, text=f"Driest: {driest}", font=dict(color=DRY, size=11))

    def tally(k):
        so_far = " so far" if k < len(years) - 1 else ""
        if rec is None:
            n = sum(v > 0 for v in lines[0][1][:k + 1])
            text = f"<b>{years[k]}</b> · Profitable in <b>{n}</b> of {k + 1} seasons{so_far}"
        else:
            n = sum(r > m for r, m in zip(lines[1][1][:k + 1], lines[0][1][:k + 1]))
            text = f"<b>{years[k]}</b> · Recommendation ahead in <b>{n}</b> of {k + 1} seasons{so_far}"
        return dict(x=1, y=1.06, xref="paper", yref="paper", xanchor="right", yanchor="bottom",
                    showarrow=False, font=dict(color=INK, size=12), text=text)

    fig.frames = [go.Frame(
        name=str(years[k]), traces=[i for i, _ in animated] + [marker],
        data=[(go.Bar if i == animated[-1][0] else go.Scatter)(x=years[:k + 1], y=f(k)) for i, f in animated]
        + [go.Scatter(x=[years[k]] * len(lines), y=[y[k] for _, y, *_ in lines])],
        layout=dict(annotations=[driest_note, tally(k)])) for k in range(len(years))]

    step = dict(frame=dict(duration=0, redraw=True), mode="immediate", transition=dict(duration=0))
    fig.update_layout(
        annotations=[driest_note, tally(len(years) - 1)],
        height=500, margin=dict(l=0, r=6, t=34, b=0), hovermode="x unified", bargap=0.25,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color=MUTED),
        hoverlabel=dict(bgcolor="#1A2148", bordercolor="#262F5E", font=dict(color=INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0),
        updatemenus=[dict(
            type="buttons", direction="left", x=0, y=-0.13, xanchor="left", yanchor="top",
            pad=dict(r=10, t=0), showactive=False, bgcolor="#1A2148", bordercolor="#3A4A8C",
            font=dict(color=INK, size=12),
            buttons=[
                dict(label="▶ Replay 1981–2024", method="animate",
                     args=[None, dict(frame=dict(duration=120, redraw=True), fromcurrent=False,
                                      mode="immediate", transition=dict(duration=0))]),
                dict(label="❚❚ Pause", method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
            ])],
        sliders=[dict(
            active=len(years) - 1, x=0.37, len=0.63, y=-0.06, yanchor="top", pad=dict(t=0, b=0),
            bgcolor="#1A2148", activebgcolor=ACCENT, bordercolor="#262F5E", borderwidth=1,
            # Tick labels hidden (44 years won't fit); the current year shows above the slider.
            tickcolor="#262F5E", ticklen=3, font=dict(color="rgba(0,0,0,0)", size=1),
            currentvalue=dict(prefix="Season: ", font=dict(color=INK, size=12), xanchor="right"),
            steps=[dict(label=str(y), method="animate", args=[[str(y)], step]) for y in years])])
    # Fixed axes, so nothing jumps around while the replay runs.
    fig.update_xaxes(gridcolor=GRID, zeroline=False, range=[years[0] - 0.7, years[-1] + 0.7])
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(title_text="Net profit", tickprefix="$", range=[floor, top + 0.06 * abs(top)], row=1, col=1)
    fig.update_yaxes(title_text="Rain (mm)", range=[0, max(rain) * 1.12], row=2, col=1)
    return fig


BACKTEST_CAPTION = ("Press ▶ Replay to watch the seasons play out one by one, or drag the slider "
                    "to any year. Bottom panel: growing-season rain (May–Sep), dotted line = "
                    "average, :red[red] = driest quarter of seasons, :blue[blue] = wettest. "
                    "Sample weather until the NASA POWER data is connected.")


def details_table(table, title):
    """The field-by-field numbers, in an expander."""
    anchor("details")
    with st.expander(title):
        details = table.assign(crop=table["crop"].map(crop_name)).rename(columns={
            "field": "Field", "year": "Year", "crop": "Crop", "acres": "Acres",
            "water_need_mm": "Water need (mm)", "water_shortfall_mm": "Shortfall (mm)",
            "soil_score_change": "Soil health", "profit_usd": "Net profit ($)",
            "cover": "Rye cover after", "irrigation_mm": "Irrigation (mm)"})
        st.dataframe(details, hide_index=True)


SOURCES = [
    ("🛰️", "NASA POWER", "https://power.larc.nasa.gov/", True,
     "Daily weather for the farm's location since 1981: rain, temperature and the evaporation "
     "they drive. Every rotation is scored and backtested on it."),
    ("🧱", "Web Soil Survey (USDA)", "https://websoilsurvey.nrcs.usda.gov/", False,
     "Soil type and how much water each field's soil can hold."),
    ("🗺️", "CropScape (USDA)", "https://nassgeodata.gmu.edu/CropScape/", False,
     "What was actually planted here in recent years: each field's last crop."),
    ("📊", "USDA NASS QuickStats", "https://quickstats.nass.usda.gov/", False,
     "County yields, used to check that the model's numbers are realistic."),
]


def sources_html():
    rows = "".join(
        f'<div class="fs-src{" fs-src-nasa" if nasa else ""}"><span class="fs-src-icon">{icon}</span>'
        f'<div><a href="{url}" target="_blank">{name} ↗</a><div class="fs-src-note">{note}</div></div></div>'
        for icon, name, url, nasa, note in SOURCES)
    return (f'<div id="sources" class="fs-sources"><div class="fs-sources-title">Data sources</div>{rows}'
            '<div class="fs-src-sample">Sample numbers for now: the optimizer is real, but it runs on '
            'synthetic weather and crop data until the NASA POWER data is connected.</div></div>')


def footer():
    show_html('<div class="fs-footer">Built by Team Athens for NASA Space Apps 2026.</div>')
