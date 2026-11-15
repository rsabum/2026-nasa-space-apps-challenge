"""Field Shift: Streamlit app (owner: Claude-Thomas, Team Athens)."""
import html
import urllib.parse
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import fake_model as model  # switch to `import model` when Robert's model.py is ready
from contract import (CONSTRAINTS, CROP_LABELS, CROPS, FARM,
                      WEIGHTS, baseline_plan, normalize_weights)
from rules import rule_problems
import assistant

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


def start_plan(farm):
    """The plan the rotation editor starts from: the applied recommendation if there is
    one and it still fits these fields, otherwise the corn-soy rotation."""
    applied = st.session_state.get("applied_plan")
    names = [f["name"] for f in farm["fields"]]
    if (applied and list(applied) == names
            and all(len(c) == farm["years"] for c in applied.values())):
        return applied
    return baseline_plan(farm)


def apply_plan(plan):
    """Button callback: copy the recommendation into the farmer's rotation."""
    st.session_state["applied_plan"] = plan
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


def reset_plan():
    """Button callback: go back to the plain corn-soy rotation."""
    st.session_state.pop("applied_plan", None)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


def rotation_editor_frame(farm):
    """Starting table for the farmer's own rotation: one row per field, one column
    per year, pre-filled from start_plan()."""
    start = start_plan(farm)
    rows = []
    for name, crops in start.items():
        row = {"Field": name}
        for i, crop in enumerate(crops):
            row[year_label(i)] = crop
        rows.append(row)
    return pd.DataFrame(rows)


def editor_to_plan(table, farm):
    """Turn the edited table back into a plan {field: [crop per year]}.
    Any cell the farmer cleared falls back to the starting crop, and we report how many."""
    start = start_plan(farm)
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
        body = ("Your rotation already matches the recommendation: nothing better turned up "
                "for your priorities and ground rules. ")
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

    # Sentence 3: average water need of the crops, weighted by acres.
    def need(t):
        return (t["water_need_mm"] * t["acres"]).sum() / t["acres"].sum()
    sn, bn = need(plan_table), need(base_table)
    if abs(sn - bn) >= 5:
        lead = "Because you're planning for a dry year, water need matters: its" if scenario == "dry" else "Its"
        body += (f"{lead} crops need {sn:.0f} mm of water a season on average, "
                 f"against {bn:.0f} mm for your rotation.")
    return f'<div class="fs-why"><div class="fs-why-title">Why this plan</div>{body}</div>'


def add_replay(fig, base, plan, rain_mm, floor, driest):
    """Turn the backtest chart into a replay: a ▶ button plays the seasons one at a time
    (lines and rain bars grow, a marker rides the lines, a tally counts the wins so far)
    and a slider jumps to any year. The chart still opens showing every season.
    Trace order matches the chart: 0 mine, 1 floor, 2 recommendation, 3 glow, 4 rain."""
    years = list(plan["year"])
    mine, rec = list(base["total_profit_usd"]), list(plan["total_profit_usd"])
    rain = list(rain_mm)
    # A marker on both lines at the current season (empty until the replay runs).
    fig.add_trace(go.Scatter(x=[], y=[], mode="markers", hoverinfo="skip", showlegend=False,
                             marker=dict(size=[10, 13], color=[MINE, ACCENT],
                                         line=dict(color="#0A0E1F", width=2))), row=1, col=1)
    # "Driest" sits inside the profit panel, just right of its red band.
    driest_note = dict(x=driest["year"] + 0.6, y=0.995, xref="x", yref="paper", xanchor="left",
                       yanchor="top", showarrow=False, text=f"Driest: {int(driest['year'])}",
                       font=dict(color=DRY, size=11))

    def tally(k):
        """'1995 · Recommendation ahead in 11 of 15 seasons so far', top right."""
        ahead = sum(r > m for r, m in zip(rec[:k + 1], mine[:k + 1]))
        so_far = " so far" if k < len(years) - 1 else ""
        return dict(x=1, y=1.06, xref="paper", yref="paper", xanchor="right", yanchor="bottom",
                    showarrow=False, font=dict(color=INK, size=12),
                    text=f"<b>{years[k]}</b> · Recommendation ahead in <b>{ahead}</b> "
                         f"of {k + 1} seasons{so_far}")

    frames = []
    for k in range(len(years)):
        xs = years[:k + 1]
        frames.append(go.Frame(name=str(years[k]), traces=[0, 1, 2, 3, 4, 5], data=[
            go.Scatter(x=xs, y=mine[:k + 1]),
            go.Scatter(x=xs, y=[floor] * (k + 1)),
            go.Scatter(x=xs, y=rec[:k + 1]),
            go.Scatter(x=xs, y=rec[:k + 1]),
            go.Bar(x=xs, y=rain[:k + 1]),   # colours stay per bar, in year order
            go.Scatter(x=[years[k]] * 2, y=[mine[k], rec[k]]),
        ], layout=dict(annotations=[driest_note, tally(k)])))
    fig.frames = frames

    # Fixed axes, so nothing jumps around while the replay runs.
    top = max(max(mine), max(rec))
    fig.update_xaxes(range=[years[0] - 0.7, years[-1] + 0.7])
    fig.update_yaxes(range=[floor, top + 0.06 * abs(top)], row=1, col=1)
    fig.update_yaxes(range=[0, max(rain) * 1.12], row=2, col=1)

    step = dict(frame=dict(duration=0, redraw=True), mode="immediate", transition=dict(duration=0))
    fig.update_layout(
        annotations=[driest_note, tally(len(years) - 1)],
        height=500, margin=dict(l=0, r=6, t=34, b=0),
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
            steps=[dict(label=str(y), method="animate",
                        args=[[str(y)], step]) for y in years])])


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


def faq_context(farm, scenario, weights, plan_table, base_table, wins, n_seasons, driest_year,
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
        "priority_profit": f"{weights['profit']:.1f}",
        "priority_water": f"{weights['water']:.1f}",
        "priority_soil": f"{weights['soil']:.1f}",
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
        "data_status": "sample values until the NASA POWER data and the optimizer are connected",
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
                f'<span class="fm-icon">{CROP_SVG.get(f.last_crop, "")}</span></div>'
                f'<div class="fm-soil">{soil}</div></div></div>')
            n += 1
        out += f'<div class="fm-row" style="flex-grow:{row_acres:g}">{plots}</div>'
    summary = (f'<div class="fm-sum"><b>{total:g}</b> acres across <b>{len(fields)}</b> '
               f'field{"" if len(fields) == 1 else "s"}</div>')
    return f'{summary}<div class="fm" style="height:{height}px">{out}</div>'


st.set_page_config(page_title="Field Shift", page_icon=str(ASSETS / "icon.png"), layout="wide")

# All the styling lives in style.css. The colours and theme base are in .streamlit/config.toml.
show_html(f"<style>{(HERE / 'style.css').read_text()}</style>")
show_html(crop_tag_css())

# ---------- Header ----------
logo_svg = (ASSETS / "logo.svg").read_text()

# The logo doubles as a directory: click it and a panel lists every part of the page,
# grouped the way a farmer works through it. Each link jumps to an anchor id below.
# Built from <details>/<summary>, so it opens and closes without any JavaScript.
DIRECTORY = [
    ("Set up", "In the left panel (open it with » if hidden)", [
        ("fields", "🗺️", "Your fields", "Acres, soil and last season's crop"),
        ("priorities", "⚖️", "What matters most", "Weigh profit, water and soil health"),
        ("rules", "📏", "Ground rules", "Crops you'd grow, rotation limits"),
    ]),
    ("Plan", "Build and compare", [
        ("weather", "🌵", "Drought check", "Plan for a typical or a dry year"),
        ("rotation", "🌽", "Your rotation", "Enter what you plan to plant"),
        ("recommendation", "⭐", "Recommended plan", "The optimizer's pick, and why"),
        ("numbers", "💵", "Key numbers", "Profit, water shortfall, soil health"),
    ]),
    ("Proof", "Check the evidence", [
        ("backtest", "🛰️", "NASA weather test", "Every season, 1981–2024"),
        ("details", "📋", "Numbers behind the plan", "Field-by-field table"),
        ("sources", "📚", "Data sources", "Where every number comes from"),
    ]),
]


def directory_html(logo):
    """The clickable logo and the directory panel that opens under it."""
    groups = ""
    for title, note, items in DIRECTORY:
        links = "".join(
            f'<a class="fs-dir-link" href="#{anchor}"><span class="fs-dir-icon">{icon}</span>'
            f'<span><b>{name}</b><small>{desc}</small></span></a>'
            for anchor, icon, name, desc in items)
        groups += (f'<div class="fs-dir-group"><div class="fs-dir-head">{title}'
                   f'<span>{note}</span></div>{links}</div>')
    return (f'<details class="fs-dir"><summary title="Open the page directory" '
            f'aria-label="Field Shift menu: jump to a section">{logo}'
            f'<span class="fs-dir-hint">☰</span></summary>'
            f'<nav class="fs-dir-panel"><div class="fs-dir-top">Jump to'
            f'<span>Click the logo again to close</span></div>{groups}</nav></details>')


def anchor(name):
    """An invisible marker the directory can jump to."""
    show_html(f'<div id="{name}" class="fs-anchor"></div>')
show_html(
    '<div class="fs-topbar">'
    '<div class="fs-crumb">Field Shift<span>›</span><b>Rotation planner</b></div>'
    '<div class="fs-status"><span class="fs-live"><i></i>Lat 40.1 · Lon −88.2</span>'
    '<span class="fs-live">Sample data</span></div></div>'
    '<div class="fs-hero">' + directory_html(logo_svg) +
    '<div><div class="fs-hero-sub">NASA <em>climate</em>-powered crop rotation planner</div>'
    '<div class="fs-hero-title">Field Shift</div>'
    '<div class="fs-hero-tag">Test your rotation against 44 seasons of NASA weather, '
    "then see if there's a better one.</div></div>"
    '<div class="fs-hero-badges">'
    '<span class="fs-badge fs-badge-data">🛰️ NASA POWER weather · 1981–2024</span>'
    '<span class="fs-badge">Team Athens</span></div></div>'
    # The story in four steps, so a judge gets it at a glance.
    # Each step is a link that jumps to its part of the page.
    '<nav class="fs-flow" aria-label="Steps">'
    '<a class="fs-step" href="#rotation"><span>1</span>Your rotation<i>↓</i></a>'
    '<a class="fs-step" href="#weather"><span>2</span>NASA weather, 1981–2024<i>↓</i></a>'
    '<a class="fs-step" href="#recommendation"><span>3</span>Optimizer<i>↓</i></a>'
    '<a class="fs-step" href="#backtest"><span>4</span>A better plan, tested<i>↓</i></a></nav>'
)

# ---------- Sidebar: inputs ----------
with st.sidebar:
    anchor("fields")   # sidebar headings get no id from Streamlit, so add our own
    st.header("Your fields", anchor=False)
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

    anchor("priorities")   # sidebar headings get no id from Streamlit, so add our own
    st.header("What matters most", anchor=False)
    weights = {
        "profit": st.slider(
            "Profit", 0.0, 10.0, float(WEIGHTS["profit"]), step=0.1, format="%.1f",
            help="Net return after seed, fertilizer and operating costs."),
        "water": st.slider(
            "Water", 0.0, 10.0, float(WEIGHTS["water"]), step=0.1, format="%.1f",
            help="Favors crops whose water need is covered by the season's rain, "
                 "so the plan is less exposed in a dry year."),
        "soil": st.slider(
            "Soil health", 0.0, 10.0, float(WEIGHTS["soil"]), step=0.1, format="%.1f",
            help="Favors rotations that build the soil: legumes that fix nitrogen, "
                 "more residue, more variety."),
    }

    anchor("rules")   # sidebar headings get no id from Streamlit, so add our own
    st.header("Ground rules", anchor=False)
    allowed = st.multiselect("Crops you'd grow", CROPS, CONSTRAINTS["allowed_crops"], key="allowed_crops",
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
        "Most acres in one crop", 30, 100, int(CONSTRAINTS["max_crop_share"] * 100), step=1,
        format="%d%%",
        help="The largest share of your land any one crop can take in a single year, "
             "so one bad price or one bad season can't hit every acre. "
             "Set it at or above your biggest field's share, or no plan can meet it.")

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

# ---------- Which weather the plan assumes: the drought switch ----------
anchor("weather")
with st.container(key="card_scenario"):
    q_col, text_col = st.columns([1, 2.3], vertical_alignment="center")
    with q_col:
        show_html('<div class="fs-scn-q">What if it\'s a drought year?</div>')
        picked = st.segmented_control(
            "Plan for", ["average", "dry"], default="average", key="scenario",
            # Plain labels: the icons are drawn by style.css (buttons can't hold our SVGs).
            format_func={"average": "Typical year", "dry": "Dry year"}.get,
            label_visibility="collapsed")
        scenario = picked or "average"   # clicking the active button un-selects it
    with text_col:
        if scenario == "dry":
            show_html('<div class="fs-scenario fs-scenario-dry">'
                      f'<span class="fs-scenario-icon fs-wx-dry">{WEATHER_SVG["dry"]}</span>'
                      '<div><b>Planning for a dry year.</b> '
                      'The recommendation and the four-year numbers assume growing-season rain like a '
                      'dry season from the NASA record, so they favor crops that hold up when rain runs '
                      'short. The 1981–2024 test below still runs every real year.</div></div>')
        else:
            show_html('<div class="fs-scenario">'
                      f'<span class="fs-scenario-icon fs-wx-avg">{WEATHER_SVG["average"]}</span>'
                      '<div><b>Planning for a typical year.</b> '
                      'The recommendation and the four-year numbers assume average growing-season rain '
                      'from the NASA record. The 1981–2024 test below runs every real year, wet and dry.'
                      '</div></div>')
season = "dry" if scenario == "dry" else "typical"

# ---------- 01 · Your rotation (the farmer types it in) ----------
with st.container(key="card_mine"):
    eyebrow("01 · Your rotation")
    st.subheader("What you plan to plant", anchor="rotation")
    applied = "applied_plan" in st.session_state
    st.caption("Your rotation is now the recommendation. Edit it, or reset to start over."
               if applied else
               "It starts as a plain corn–soy rotation. Press Edit rotation and change it to what "
               "you'd actually plant; we'll test it on every season since 1981.")
    show_html(crop_key_html())
    tiles = st.container()   # the tiles go here, once we know the rotation
    b1, b2, _ = st.columns([1, 1, 2.6])
    with b1.popover(":material/edit: Edit rotation"):
        show_html('<div class="fm-edit-title">Edit your rotation</div>')
        year_columns = {
            year_label(i): st.column_config.SelectboxColumn(
                year_label(i), options=CROPS, format_func=crop_name, required=True)
            for i in range(farm["years"])
        }
        edited = st.data_editor(
            rotation_editor_frame(farm),
            column_config={"Field": st.column_config.TextColumn("Field", disabled=True), **year_columns},
            num_rows="fixed", hide_index=True,
            # A new key restarts the editor: when fields change, or a plan is applied or reset.
            key=f"rotation-{'|'.join(fields['name'].astype(str))}-v{st.session_state.get('editor_version', 0)}",
        )
        st.caption("Click a cell to pick a crop.")
    if applied:
        b2.button("↺ Reset to corn–soy", on_click=reset_plan)
    my_plan, blanks = editor_to_plan(edited, farm)
    with tiles:
        show_html(rotation_grid_html(pd.DataFrame(my_plan).T.rename(columns=lambda i: i + 1)))
    if blanks:
        st.caption(f":orange[{blanks} empty cell{'' if blanks == 1 else 's'} filled in with "
                   "the starting crop for that year.]")
    my_problems = rule_problems(my_plan, farm, constraints)
    if my_problems:
        st.warning("**Your rotation breaks some of your ground rules.** We'll still test it "
                   "as you entered it.\n\n" + bullet_list(my_problems),
                   icon="⚠️")
    else:
        st.caption(":blue[✓ Follows all your ground rules.]")

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
    eyebrow("02 · Optimized rotation")
    st.subheader(f"Recommended plan for a {season} year", anchor="recommendation")
    st.caption("Chosen by the optimizer for your priorities and ground rules. "
               "The chips compare it with your rotation.")
    grid = (plan_table.pivot(index="field", columns="year", values="crop")
            .reindex(plan_table["field"].unique()))
    show_html(rotation_grid_html(grid))
    sug_problems = rule_problems(suggested, farm, constraints)
    show_html(result_chips_html(plan_table, base_table, len(sug_problems)))
    if sug_problems:
        st.warning("**The recommendation couldn't meet every ground rule**, so these rules may not "
                   "fit together on your farm. Try loosening one in the sidebar.\n\n"
                   + bullet_list(sug_problems), icon="⚠️")
    show_html(why_this_plan_html(suggested, my_plan, plan_table, base_table, farm, scenario))
    show_html('<div class="fs-why-title fs-mix-title">Acres by crop, year by year</div>')
    st.plotly_chart(crop_mix_chart({"Your rotation": my_plan, "Recommended": suggested}, farm),
                    key="crop_mix")
    if suggested != my_plan:
        st.button("Apply recommendation →", type="primary", on_click=apply_plan, args=(suggested,),
                  help="Copies this plan into Your rotation, so you can tweak it and see how it tests.")

# ---------- The three key numbers, against the farmer's rotation ----------
p, w, s = totals(plan_table)
bp, bw, bs = totals(base_table)


def vs(diff, text, tiny=0.5):
    """The comparison under a metric, or nothing when the two rotations are the same."""
    return None if abs(diff) < tiny else f"{text} vs your rotation"


anchor("numbers")
c1, c2, c3 = st.columns(3)
with c1.container(key="m_profit"):
    st.metric(f"Net profit, 4 {season} years", f"${p:,.0f}", vs(p - bp, f"{p - bp:+,.0f}"),
              help="Revenue minus seed, fertilizer and operating costs, across all fields.")
with c2.container(key="m_water"):
    st.metric(f"Water shortfall, 4 {season} years", f"{w:,.0f} acre-in", vs(w - bw, f"{w - bw:+,.0f}"),
              delta_color="inverse",
              help="How far growing-season rain fell short of what the crops needed. "
                   "One acre-inch is an inch of water over one acre. Lower is better.")
with c3.container(key="m_soil"):
    st.metric(f"Soil health, 4 {season} years", f"{s:+.1f}", vs(s - bs, f"{s - bs:+.1f}", tiny=0.05),
              help="A score for what the rotation does to your soil: residue, nitrogen "
                   "from legumes and crop variety. Higher is better.")

# ---------- 03 · The test, on NASA weather ----------
with st.container(key="card_test"):
    eyebrow("03 · Tested on NASA weather")
    st.subheader("How it holds up, 1981–2024", anchor="backtest")
    wins = int((bt_plan["total_profit_usd"] > bt_base["total_profit_usd"]).sum())
    rain = bt_base[["year", "growing_season_rain_mm"]]
    driest = rain.loc[rain["growing_season_rain_mm"].idxmin()]
    stat_col, chart_col = st.columns([1, 3.4])
    with stat_col:
        pct = 100 * wins / len(bt_plan)
        show_html(
            f'<div class="fs-stat"><div class="fs-ring" style="--pct:{pct:.1f}"><div class="fs-ring-inner">'
            f'<div class="fs-stat-num">{wins}<small> / {len(bt_plan)}</small></div>'
            f'<div class="fs-stat-pct">{pct:.0f}% OF SEASONS</div></div></div>'
            '<div class="fs-stat-label">seasons where the recommendation out-earned '
            'your rotation</div></div>')
        worst = bt_base.loc[bt_base["total_profit_usd"].idxmin()]
        st.caption(f"Each rotation is run against that season's actual weather. "
                   f"Your rotation's toughest season was {int(worst['year'])}, "
                   f"at ${worst['total_profit_usd']:,.0f}. The driest was {int(driest['year'])}.")
    with chart_col:
        # Two panels sharing the year axis: profit on top, NASA rain underneath.
        bt = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.66, 0.34],
                           vertical_spacing=0.07)
        # The y-axis floor sits a little under the lowest profit, so the fills stay in view.
        floor = min(bt_base["total_profit_usd"].min(), bt_plan["total_profit_usd"].min())
        floor -= 0.08 * abs(floor) + 1
        bt.add_trace(go.Scatter(
            x=bt_base["year"], y=bt_base["total_profit_usd"], name="Your rotation",
            line=dict(color=MINE, width=2, shape="spline", smoothing=0.6),
            hovertemplate="$%{y:,.0f}"), row=1, col=1)
        # Recommendation: a glowing line with a soft ice-blue fill down to the floor.
        bt.add_trace(go.Scatter(
            x=bt_plan["year"], y=[floor] * len(bt_plan), line=dict(width=0),
            hoverinfo="skip", showlegend=False), row=1, col=1)
        bt.add_trace(go.Scatter(
            x=bt_plan["year"], y=bt_plan["total_profit_usd"], name="Recommendation",
            line=dict(color=ACCENT, width=3, shape="spline", smoothing=0.6),
            fill="tonexty", fillcolor="rgba(191,215,255,0.12)",
            hovertemplate="$%{y:,.0f}"), row=1, col=1)
        # Glow: the same line again, wide and faint. Drawn after, so it doesn't change the fill.
        bt.add_trace(go.Scatter(
            x=bt_plan["year"], y=bt_plan["total_profit_usd"], hoverinfo="skip", showlegend=False,
            line=dict(color="rgba(191,215,255,0.15)", width=7, shape="spline", smoothing=0.6)),
            row=1, col=1)

        # Rain bars: driest quarter of seasons NASA red, wettest quarter NASA blue, the rest navy.
        mm = rain["growing_season_rain_mm"]
        low, high = mm.quantile(0.25), mm.quantile(0.75)
        colors = [DRY if v <= low else WET if v >= high else NORMAL for v in mm]
        bt.add_trace(go.Bar(
            x=rain["year"], y=mm, name="Growing-season rain", marker=dict(color=colors),
            hovertemplate="%{y:.0f} mm rain", showlegend=False), row=2, col=1)
        bt.add_hline(y=mm.mean(), line=dict(color=MUTED, width=1, dash="dot"), row=2, col=1)

        # The driest season: a soft band through both panels, with its year.
        bt.add_vrect(x0=driest["year"] - 0.5, x1=driest["year"] + 0.5,
                     fillcolor=DRY, opacity=0.12, line_width=0)

        bt.update_layout(
            height=430, margin=dict(l=0, r=0, t=26, b=0), hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", color=MUTED),
            hoverlabel=dict(bgcolor="#1A2148", bordercolor="#262F5E", font=dict(color=INK)),
            legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0), bargap=0.25)
        bt.update_xaxes(gridcolor=GRID, zeroline=False)
        bt.update_yaxes(gridcolor=GRID, zeroline=False)
        bt.update_yaxes(title_text="Net profit", tickprefix="$", range=[floor, None], row=1, col=1)
        bt.update_yaxes(title_text="Rain (mm)", row=2, col=1)
        add_replay(bt, bt_base, bt_plan, mm, floor, driest)
        st.plotly_chart(bt)
        st.caption("Press ▶ Replay to watch the seasons play out one by one, or drag the "
                   "slider to any year. "
                   "Bottom panel: growing-season rain from NASA POWER, dotted line = average, "
                   ":red[red] = driest quarter of seasons, :blue[blue] = wettest. "
                   "Sample values until the NASA data is connected.")

anchor("details")
with st.expander("See the numbers behind the plan"):
    details = plan_table.assign(crop=plan_table["crop"].map(crop_name)).rename(columns={
        "field": "Field", "year": "Year", "crop": "Crop", "acres": "Acres",
        "water_need_mm": "Water need (mm)", "water_shortfall_mm": "Shortfall (mm)",
        "soil_score_change": "Soil health", "profit_usd": "Net profit ($)"})
    st.dataframe(details, hide_index=True)

# ---------- Data sources: where NASA comes in ----------
SOURCES = [
    ("🛰️", "NASA POWER", "https://power.larc.nasa.gov/", True,
     "Monthly weather for the farm's location since 1981: rain, temperature, sunlight and "
     "root-zone soil wetness. Every rotation is backtested on it, and it sets the dry-year scenario."),
    ("🧱", "Web Soil Survey (USDA)", "https://websoilsurvey.nrcs.usda.gov/", False,
     "Soil type and how much water each field's soil can hold."),
    ("🗺️", "CropScape (USDA)", "https://nassgeodata.gmu.edu/CropScape/", False,
     "What was actually planted here in recent years: each field's last crop."),
    ("📊", "USDA NASS QuickStats", "https://quickstats.nass.usda.gov/", False,
     "County yields, used to check that the model's numbers are realistic."),
]
rows = "".join(
    f'<div class="fs-src{" fs-src-nasa" if nasa else ""}"><span class="fs-src-icon">{icon}</span>'
    f'<div><a href="{url}" target="_blank">{name} ↗</a><div class="fs-src-note">{note}</div></div></div>'
    for icon, name, url, nasa, note in SOURCES)
show_html(f'<div id="sources" class="fs-sources"><div class="fs-sources-title">Data sources</div>{rows}'
          '<div class="fs-src-sample">Sample numbers for now: the NASA POWER data and the optimizer '
          'are being connected.</div></div>'
          '<div class="fs-footer">Built by Team Athens for NASA Space Apps 2026.</div>')

# ---------- The assistant: floating chat bubble, bottom right ----------
assistant.render(
    faq_context(farm, scenario, weights, plan_table, base_table, wins, len(bt_plan),
                int(driest["year"]), my_problems, suggested, my_plan),
    avatar=str(ASSETS / "icon.png"))
