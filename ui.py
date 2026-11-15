"""Shared building blocks for the Field Shift pages (owner: Claude-Thomas).

Everything the three pages draw lives here, so they look the same and nothing is copied:
crop colours and icons, the rotation tiles, the field map, charts, chips, the "why this
plan" box, page headers, and the shared state (your rotation, the weather switch, your goal).

app.py is the entry point: it sets up the page, draws the farm setup in the sidebar,
and runs whichever page is open (pages/home.py, pages/evaluate.py, pages/optimize.py).
"""
import html
import urllib.parse
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import model  # Robert's optimizer. fake_model.py is the old stand-in: `import fake_model as model`
from contract import (CONSTRAINTS, CROP_LABELS, CROPS, DEFAULT_LIMITS, FARM, GOAL_HELP,
                      GOAL_OWN_LIMITS, GOALS, LIMIT_LABELS, WORST_SHARE, baseline_plan)
from rules import rule_problems

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
        years = [f"Year {i + 1}" for i in range(farm["years"])]
        for crop in CROPS:
            ys = [sum(acres.get(f, 0) for f, cs in plan.items() if cs[i] == crop)
                  for i in range(farm["years"])]
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
# Weather icons in the same line-art style, animated by style.css: for a typical year
# rain falls from a cloud while the sun's rays turn; for a dry year the sun blazes
# and heat shimmers over cracked ground.
WEATHER_SVG = {
    "average": _ICON.format(
        '<g class="wx-spin" style="transform-origin:8px 7.5px">'
        '<path d="M8 2.2v1.2M3.3 4.2l.9.8M2.7 7.5h1.2M12.7 4.2l-.9.8"/></g>'
        f'<circle cx="8" cy="7.5" r="3" {_DUO}/>'
        '<path class="wx-cloud" d="M7 17h10.2a3.6 3.6 0 0 0 .3-7.2 5 5 0 0 0-9.6 1.4A2.9 2.9 0 0 0 7 17z"/>'
        f'<path d="M7 17h10.2a3.6 3.6 0 0 0 .3-7.2 5 5 0 0 0-9.6 1.4A2.9 2.9 0 0 0 7 17z" {_DUO}/>'
        '<path class="wx-drop" d="M9.5 19.4l-.7 1.6"/>'
        '<path class="wx-drop" style="animation-delay:-.4s" d="M13 19.4l-.7 1.6"/>'
        '<path class="wx-drop" style="animation-delay:-.8s" d="M16.5 19.4l-.7 1.6"/>'),
    "dry": _ICON.format(
        '<g class="wx-spin wx-blaze" style="transform-origin:12px 9px">'
        '<path d="M12 2.3v1.4M12 14.3v1.4M5.3 9h1.4M17.3 9h1.4M7.3 4.3l1 1M15.7 12.7l1 1'
        'M16.7 4.3l-1 1M8.3 12.7l-1 1"/></g>'
        f'<circle cx="12" cy="9" r="3.6" {_DUO}/>'
        '<path class="wx-heat" stroke-width="1.1" d="M4.5 16.6c.8-.6 1.6.6 2.4 0M17 16.6c.8-.6 1.6.6 2.4 0"/>'
        '<path d="M3 19h18M8.5 19l1 2.4M14 19l-.9 1.3.9 1.3M18.6 19l.7 1.9"/>'),
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


def result_chips_html(plan_table, base_table, n_broken):
    """The row of chips under the recommendation: each one says how it compares with
    the farmer's rotation, green when better and red when worse."""
    p, w, s = totals(plan_table)
    bp, bw, bs = totals(base_table)

    def chip(text, good):
        kind = "good" if good else "bad"
        return f'<span class="fs-chip fs-chip-{kind}">{text}</span>'

    def compare(diff, amount, name, higher_is_better=True, tiny=0.05):
        """'↑ $2,628 profit' in green or red, or '= Same profit' in grey when there's no difference."""
        if abs(diff) < tiny:
            return f'<span class="fs-chip">= Same {name}</span>'
        good = diff > 0 if higher_is_better else diff < 0
        return chip(f"{'↑' if diff > 0 else '↓'} {amount} {name}", good)

    chips = [
        compare(p - bp, f"${abs(p - bp):,.0f}", "profit", tiny=0.5),
        compare(w - bw, f"{abs(w - bw):,.0f} acre-in", "water shortfall", higher_is_better=False, tiny=0.5),
        compare(s - bs, f"{abs(s - bs):.1f}", "soil health"),
        chip("✓ Meets your ground rules", True) if n_broken == 0
        else chip(f"⚠ Breaks {n_broken} rule{'s' if n_broken > 1 else ''}", False),
    ]
    level, inches = water_stress(plan_table)
    chips.append(f'<span class="fs-chip fs-stress-{level.lower()}" title="Shortfall per acre per '
                 f'season. Under 1 in: Low, 1–3 in: Moderate, over 3 in: High.">💧 Water stress: '
                 f'<b>{level}</b> · {inches:.1f} in/acre</span>')
    return f'<div class="fs-chips">{"".join(chips)}</div>'


def bullet_list(items, limit=5):
    """Markdown bullets, at most `limit` of them, then '…and N more'."""
    lines = [f"- {item}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"- …and {len(items) - limit} more")
    return "\n".join(lines)


def totals(t):
    """The three headline numbers for a plan table: profit ($), water shortfall
    (acre-inches, area-weighted) and soil health (points per acre over the four years,
    area-weighted, so a big field counts more; the optimizer measures it the same way)."""
    acres = t.groupby("field")["acres"].first().sum()
    return (t["profit_usd"].sum(),
            (t["water_shortfall_mm"] * t["acres"]).sum() / 25.4,
            (t["soil_score_change"] * t["acres"]).sum() / acres)


def why_this_plan_html(suggested, mine, plan_table, base_table, farm, scenario):
    """Up to three sentences on how the suggestion differs from the farmer's rotation
    and what that buys. Built only from model output, so it never claims more than
    the numbers show."""
    acres = {f["name"]: f["acres"] for f in farm["fields"]}
    changed = {f: sum(a != b for a, b in zip(crops, mine.get(f, []))) for f, crops in suggested.items()}
    n_changed = sum(changed.values())
    if n_changed == 0:
        body = ("Your rotation already matches the recommendation: nothing better turned up "
                "for your goal, limits and ground rules. ")
    else:
        # Sentence 1: the field where the change is biggest (most years changed, then most acres).
        field = max(changed, key=lambda f: (changed[f], acres.get(f, 0)))
        new = " → ".join(crop_word(c) for c in suggested[field])
        old = " → ".join(crop_word(c) for c in mine[field])
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

    # Rye cover isn't drawn on the tiles yet, so say it in words.
    if "cover" in plan_table and plan_table["cover"].any():
        n_rye = int(plan_table["cover"].sum())
        body += (f"It also sows a cereal-rye cover after {n_rye} field-year{'s' if n_rye > 1 else ''} "
                 "(see the table at the bottom) to build soil. ")

    # Sentence 3: average water need of the crops, weighted by acres.
    def need(t):
        return (t["water_need_mm"] * t["acres"]).sum() / t["acres"].sum()
    sn, bn = need(plan_table), need(base_table)
    if abs(sn - bn) >= 5:
        lead = "Because you're planning for a dry year, water need matters: its" if scenario == "dry" else "Its"
        body += (f"{lead} crops need {sn:.0f} mm of water a season on average, "
                 f"against {bn:.0f} mm for your rotation.")
    return f'<div class="fs-why"><div class="fs-why-title">Why this plan</div>{body}</div>'


def crop_tag_css():
    """Give each tag in "Crops you'd grow" its crop's colour and icon. Streamlit marks each
    tag with the crop's label (title="Corn"), which is what the selectors match on."""
    rules = ""
    for crop, svg in CROP_SVG.items():
        icon = svg.replace('<svg class="fs-crop-icon"', '<svg xmlns="http://www.w3.org/2000/svg"')
        uri = "data:image/svg+xml," + urllib.parse.quote(icon, safe=" =:/,.-()")
        tag = f'.st-key-allowed_crops [data-baseweb="tag"]:has(span[title="{CROP_LABELS[crop]}"])'
        rules += (f'{tag} {{background: {CROP_COLORS[crop]} !important;}}'
                  f'{tag}::before {{-webkit-mask-image: url("{uri}"); mask-image: url("{uri}");}}')
    return f"<style>{rules}</style>"


def faq_context(farm, scenario, goal, limits, plan_table, base_table, wins, n_seasons, driest_year,
                my_problems, suggested, my_plan):
    """What the farmer is looking at, for the assistant. Only numbers the app shows."""
    p, w, s = totals(plan_table)
    bp, bw, bs = totals(base_table)
    changed = sum(a != b for f, crops in suggested.items() for a, b in zip(crops, my_plan.get(f, [])))
    return {
        "farm_location": f"lat {farm['lat']}, lon {farm['lon']}" if "lat" in farm else "central Illinois",
        "fields": ", ".join(f"{f['name']} ({f['acres']:g} ac, {f['soil']})" for f in farm["fields"]),
        "total_acres": f"{sum(f['acres'] for f in farm['fields']):g}",
        "planning_for": "dry" if scenario == "dry" else "typical",
        "goal": f"{GOALS[goal]}: {GOAL_HELP[goal]}",
        "limits": ("; ".join(f"{LIMIT_LABELS[k]} {v:.0%} of your rotation" for k, v in limits.items())
                   or "none"),
        "limits_not_met": "; ".join(plan_table.attrs.get("unmet", [])) or "none",
        "your_rotation": "; ".join(f"{f}: " + " → ".join(CROP_LABELS[c] for c in cs) for f, cs in my_plan.items()),
        "recommended_rotation": "; ".join(f"{f}: " + " → ".join(CROP_LABELS[c] for c in cs) for f, cs in suggested.items()),
        "recommendation_vs_yours": ("the same as your rotation" if changed == 0
                                    else f"different from your rotation in {changed} field-years"),
        "your_rotation_rules": ("follows all your ground rules" if not my_problems
                                else f"breaks {len(my_problems)} ground rule(s): " + "; ".join(my_problems[:3])),
        "net_profit_4_years_recommendation": f"${p:,.0f}",
        "profit_change_vs_yours": f"{p - bp:+,.0f} dollars",
        "water_shortfall_4_years_recommendation": f"{w:,.0f} acre-inches",
        "water_shortfall_change_vs_yours": f"{w - bw:+,.0f} acre-inches (lower is better)",
        "soil_health_recommendation": f"{s:+.1f}",
        "soil_health_change_vs_yours": f"{s - bs:+.1f}",
        "seasons_tested": n_seasons,
        "seasons_recommendation_won": f"{wins} of {n_seasons}",
        "driest_season": driest_year,
        "data_status": ("the optimizer is real, but it runs on synthetic sample weather and crop "
                        "data until the NASA POWER data is connected"),
    }


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
# Everything else reads the "_" copy. Your rotation is stored under "my_plan".
def keep_state():
    """Called by app.py at the top of every run: defaults for the saved values."""
    ss = st.session_state
    ss.setdefault("_scenario", "average")
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


def fit_plan(plan, farm):
    """`plan` trimmed to the current fields: fields it doesn't cover (new, renamed, or a
    crop no longer known) get the plain corn-soy rotation."""
    base = baseline_plan(farm)
    out = {}
    for f in farm["fields"]:
        crops = (plan or {}).get(f["name"])
        ok = crops is not None and len(crops) == farm["years"] and all(c in CROPS for c in crops)
        out[f["name"]] = list(crops) if ok else base[f["name"]]
    return out


def current_plan(farm):
    """The farmer's rotation: what they entered in the evaluator, else corn-soy."""
    return fit_plan(st.session_state.get("my_plan"), farm)


def _restart_editor():
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


def apply_plan(plan):
    """Button callback: make the recommendation the farmer's rotation."""
    st.session_state["my_plan"] = plan
    st.session_state["rotation_base"] = plan
    st.session_state["applied"] = True
    _restart_editor()


def reset_plan():
    """Button callback: go back to the plain corn-soy rotation."""
    for k in ("my_plan", "rotation_base"):
        st.session_state.pop(k, None)
    st.session_state["applied"] = False
    _restart_editor()


def rotation_editor_frame(start):
    """Table for the rotation editor: one row per field, one column per year."""
    rows = []
    for name, crops in start.items():
        row = {"Field": name}
        for i, crop in enumerate(crops):
            row[year_label(i)] = crop
        rows.append(row)
    return pd.DataFrame(rows)


def editor_to_plan(table, farm, start):
    """Turn the edited table back into a plan {field: [crop per year]}.
    Any cell the farmer cleared falls back to the starting crop, and we report how many."""
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


def farm_ready():
    """The farm and ground rules from the sidebar, or None (with a message) if there's
    nothing to plan yet."""
    ctx = st.session_state.get("_farm_ctx")
    if ctx is None or not ctx["farm"]["fields"]:
        st.info("Add at least one field under **Your fields** in the left panel to get started.")
        return None
    if not ctx["constraints"]["allowed_crops"]:
        st.info("Pick at least one crop under **Ground rules** in the left panel to get started.")
        return None
    return ctx


# ================================================================ goal and limits
LIMIT_HELP = {
    "profit_min": "Average 4-year profit can't fall below this share of your rotation's.",
    "worst_profit_min": "Profit in your worst 10% of seasons can't fall below this share of yours.",
    "shortfall_max": "Water the crops lack (need minus rain and soil water) can't exceed this "
                     "share of your rotation's. Lower is safer in a drought.",
    "irrigation_max": "In every season, the plan can't pump more than this share of what your "
                      "rotation pumps. Only for irrigated fields.",
    "soil_min": "Soil-health points can't fall below this share of your rotation's.",
    "production_min": "For every crop in your rotation, the plan must still harvest at least "
                      "this share of the bushels you'd grow (feed or contracts).",
}


def _offered_limits(goal, any_irrigated):
    """Limits that make sense for this goal (never the goal's own measure)."""
    return [k for k in LIMIT_LABELS
            if k not in GOAL_OWN_LIMITS[goal] and not (k == "irrigation_max" and not any_irrigated)]


def _limit_start(goal, key):
    default = DEFAULT_LIMITS[goal].get(key)
    return int(round(100 * (default if default is not None else (1.0 if key.endswith("_max") else 0.95))))


def read_goal(any_irrigated):
    """The goal, limits and bad-year share as last set on the optimizer page (or defaults)."""
    goal = saved("goal") if saved("goal") in GOALS else "max_profit"
    limits = {}
    for key in _offered_limits(goal, any_irrigated):
        if saved(f"lim_on_{goal}_{key}", key in DEFAULT_LIMITS[goal]):
            limits[key] = saved(f"lim_{goal}_{key}", _limit_start(goal, key)) / 100
    worst = saved("worst_share_sel", WORST_SHARE) if goal == "max_worst_profit" else WORST_SHARE
    return goal, limits, worst


def goal_controls(any_irrigated):
    """The optimizer's goal picker and limit sliders. Each widget gets its saved value
    back before it's drawn and saves changes (remember/save), so the choices survive
    page changes; read_goal() reads the saved values."""
    ss = st.session_state
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        remember("goal", "max_profit")
        st.selectbox("Your goal", list(GOALS), format_func=GOALS.get, key="goal",
                     on_change=save, args=("goal",),
                     help="The optimizer pursues one goal. Everything else is a limit.")
        goal = ss["goal"]
        st.caption(GOAL_HELP[goal])
        if goal == "max_worst_profit":
            remember("worst_share_sel", WORST_SHARE)
            st.select_slider(
                "Bad years to protect", options=[1 / 44, 0.10, 0.25], key="worst_share_sel",
                on_change=save, args=("worst_share_sel",),
                format_func=lambda v: "Worst single season" if v < 0.05 else f"Worst {v:.0%} of seasons",
                help="Which seasons count as bad years: the plan's average profit across them "
                     "is what this goal makes as high as possible.")
    with right:
        st.markdown("**Limits** · compared with your rotation")
        for key in _offered_limits(goal, any_irrigated):
            on_key, pct_key = f"lim_on_{goal}_{key}", f"lim_{goal}_{key}"
            remember(on_key, key in DEFAULT_LIMITS[goal])
            st.checkbox(LIMIT_LABELS[key], key=on_key, help=LIMIT_HELP[key],
                        on_change=save, args=(on_key,))
            if ss[on_key]:
                remember(pct_key, _limit_start(goal, key))
                st.slider(LIMIT_LABELS[key], 50, 150 if key.endswith("_max") else 120, step=1,
                          format="%d%% of yours", key=pct_key, label_visibility="collapsed",
                          on_change=save, args=(pct_key,))


# ================================================================ the shared calculation
def analysis(ctx):
    """Your rotation and the optimizer's recommendation, scored and backtested, for the
    current settings. Both tool pages and the assistant use this; the model caches its
    solves, so calling it more than once in a run is cheap."""
    farm = ctx["farm"]
    scenario = saved("scenario") or "average"
    goal, limits, worst = read_goal(ctx["any_irrigated"])
    constraints = {**ctx["constraints"], "worst_share": worst}
    my_plan = current_plan(farm)
    plan_table = model.solve(farm, None, goal, scenario,
                             {**constraints, "limits": limits, "reference_plan": my_plan})
    base_table = model.evaluate(my_plan, farm, None, scenario)
    suggested = model.table_to_plan(plan_table)
    covers = model.table_to_covers(plan_table) if hasattr(model, "table_to_covers") else None
    bt_plan = model.backtest(suggested, farm, covers=covers) if covers else model.backtest(suggested, farm)
    bt_base = model.backtest(my_plan, farm)
    rain = bt_base.set_index("year")["growing_season_rain_mm"]
    return {
        "farm": farm, "constraints": constraints, "scenario": scenario,
        "season": "dry" if scenario == "dry" else "typical",
        "goal": goal, "limits": limits, "my_plan": my_plan,
        "my_problems": rule_problems(my_plan, farm, constraints),
        "plan_table": plan_table, "base_table": base_table, "suggested": suggested,
        "bt_plan": bt_plan, "bt_base": bt_base,
        "wins": int((bt_plan["total_profit_usd"] > bt_base["total_profit_usd"]).sum()),
        "driest": int(rain.idxmin()),
    }


def analysis_or_stop(ctx):
    try:
        return analysis(ctx)
    except Exception as e:  # never show a traceback to a judge
        st.error(f"The model could not run: {e}")
        st.stop()


# ================================================================ page furniture
def load_styles():
    """All the styling lives in style.css; colours for Streamlit's widgets in config.toml."""
    show_html(f"<style>{(HERE / 'style.css').read_text()}</style>")
    show_html(crop_tag_css())


def anchor(name):
    """An invisible marker the logo directory can jump to."""
    show_html(f'<div id="{name}" class="fs-anchor"></div>')


# The logo doubles as a directory of the open page: click it and a panel lists its parts.
# Links jump within the page only (a plain link to another page would reload the app and
# lose your inputs; the page menu in the left panel switches pages safely).
SETUP_GROUP = ("Set up", "In the left panel (open it with » if hidden)", [
    ("fields", "🗺️", "Your fields", "Acres, soil, irrigation, last crop"),
    ("rules", "📏", "Ground rules", "Crops you'd grow, rotation limits"),
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


def scenario_card(what):
    """The drought switch. `what` names what it changes on this page. Its value is saved
    (remember/save), so the choice carries between pages."""
    anchor("weather")
    with st.container(key="card_scenario"):
        q_col, text_col = st.columns([1, 2.3], vertical_alignment="center")
        with q_col:
            show_html('<div class="fs-scn-q">What if it\'s a drought year?</div>')
            remember("scenario", "average")
            picked = st.segmented_control(
                "Plan for", ["average", "dry"], key="scenario", on_change=save, args=("scenario",),
                # Plain labels: the icons are drawn by style.css (buttons can't hold our SVGs).
                format_func={"average": "Typical year", "dry": "Dry year"}.get,
                label_visibility="collapsed")
        scenario = picked or "average"   # clicking the active button un-selects it
        with text_col:
            if scenario == "dry":
                show_html('<div class="fs-scenario fs-scenario-dry">'
                          f'<span class="fs-scenario-icon fs-wx-dry">{WEATHER_SVG["dry"]}</span>'
                          f'<div><b>Planning for a dry year.</b> {what} assume growing-season rain '
                          'like the driest quarter of seasons in the NASA record. The 1981–2024 '
                          'test below still runs every real year.</div></div>')
            else:
                show_html('<div class="fs-scenario">'
                          f'<span class="fs-scenario-icon fs-wx-avg">{WEATHER_SVG["average"]}</span>'
                          f'<div><b>Planning for a typical year.</b> {what} assume average '
                          'growing-season rain from the NASA record. The 1981–2024 test below runs '
                          'every real year, wet and dry.</div></div>')
    return scenario


def money(v):
    """$12,345 or −$8,208 (minus sign before the dollar sign)."""
    return f"{'−' if v < 0 else ''}${abs(v):,.0f}"


def vs(diff, text, tiny=0.5):
    """The comparison under a metric, or nothing when the two rotations are the same."""
    return None if abs(diff) < tiny else f"{text} vs your rotation"


def metric_row(table, season, base=None):
    """Profit, water shortfall and soil health for a plan; compared with `base` if given."""
    p, w, s = totals(table)
    anchor("numbers")
    c1, c2, c3 = st.columns(3)
    if base is not None:
        bp, bw, bs = totals(base)
        d_p, d_w, d_s = vs(p - bp, f"{p - bp:+,.0f}"), vs(w - bw, f"{w - bw:+,.0f}"), vs(s - bs, f"{s - bs:+.1f}", tiny=0.05)
    else:
        d_p = d_w = d_s = None
    with c1.container(key="m_profit"):
        st.metric(f"Net profit, 4 {season} years", f"${p:,.0f}", d_p,
                  help="Revenue minus seed, fertilizer, rye and pumping costs, across all fields.")
    with c2.container(key="m_water"):
        st.metric(f"Water shortfall, 4 {season} years", f"{w:,.0f} acre-in", d_w, delta_color="inverse",
                  help="How far rain and stored soil water fell short of what the crops needed. "
                       "One acre-inch is an inch of water over one acre. Lower is better.")
    with c3.container(key="m_soil"):
        st.metric(f"Soil health, 4 {season} years", f"{s:+.1f}", d_s,
                  help="Soil-health points per acre over the four years: residue, nitrogen from "
                       "legumes, small grains and rye cover. Higher is better.")


def ring_html(n, total, label):
    """The big 'N / 44' ring."""
    pct = 100 * n / total
    return (f'<div class="fs-stat"><div class="fs-ring" style="--pct:{pct:.1f}"><div class="fs-ring-inner">'
            f'<div class="fs-stat-num">{n}<small> / {total}</small></div>'
            f'<div class="fs-stat-pct">{pct:.0f}% OF SEASONS</div></div></div>'
            f'<div class="fs-stat-label">{label}</div></div>')


def backtest_chart(mine, rec=None):
    """Profit per season (top panel) over NASA growing-season rain (bottom), 1981-2024,
    with a replay: ▶ plays the seasons one at a time and a slider jumps to any year.
    `mine` is the farmer's backtest; `rec` (optional) the recommendation's. With one line,
    the farmer's rotation gets the starring style; with two, the recommendation does."""
    years = list(mine["year"])
    rain = list(mine["growing_season_rain_mm"])
    mm = mine["growing_season_rain_mm"]
    driest = int(mine.loc[mm.idxmin(), "year"])
    lines = ([("Your rotation", list(mine["total_profit_usd"]), ACCENT, 3, True)] if rec is None else
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
     "they drive. Every rotation is backtested on it, and it sets the dry-year scenario."),
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
