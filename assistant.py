"""Field Shift assistant: the chat bubble in the bottom-right corner (owner: Claude-Thomas).

Two modes:
- Claude mode: when an ANTHROPIC_API_KEY is set (in .streamlit/secrets.toml or the
  environment), answers stream from Claude, grounded in the numbers on screen.
- Quick-answer mode: otherwise (and as a fallback if the API fails), answers come
  from the built-in FAQ below, which also uses the live numbers.

app.py calls render(ctx) once per run, after the open page, with a dict of what the
farmer is looking at (see ui.py: faq_context).
"""
import os
import re

import streamlit as st

MODEL = "claude-opus-5-5"
HISTORY_TURNS = 10   # how many recent messages Claude sees

# Questions offered as one-click chips.
QUICK_QUESTIONS = [
    "What does Field Shift do?",
    "How do I enter my rotation?",
    "How did the recommendation do?",
    "What does the dry-year switch do?",
    "Where does the data come from?",
]

STABLE_SYSTEM = """You are the built-in assistant for Field Shift, a crop rotation planner \
built by Team Athens for the NASA Space Apps Challenge 2026 ("Field Shift: Adapting Farms \
with NASA Data").

What the app does: a farmer enters a 4-year crop rotation for each field (corn, soybeans, \
winter wheat, sorghum), one goal with limits, and ground rules. The app backtests that rotation on \
every growing season of NASA POWER weather from 1981 to 2024, and an optimizer suggests a \
better rotation that is backtested the same way.

Where things are: the app has three pages, picked from the menu at the top of the left panel.
- Left panel, on every page: the page menu, "Your fields" (field map; Edit fields to change \
names, acres, soil, irrigated, last crop) and "Ground rules" (crops you'd grow, no back-to-back \
crops, at least one soybean year per field, most acres in one crop).
- Home: what Field Shift does, buttons to the two tools, how it works, the farm at a glance, \
and the data sources.
- Rotation evaluator: the drought check (typical or dry year), "01 Your rotation" (tiles; \
Edit rotation to change crops; Reset to corn-soy), key numbers for their rotation, and "02 \
Tested on NASA weather" (ring = seasons the rotation made money; profit line over \
growing-season rain bars; Replay 1981-2024 plays the seasons).
- Rotation optimizer: "01 Your goal" (pick one: most profit, least water, best bad-year profit, \
healthiest soil; Limits under it, each a % of their own rotation, ticked on or off), the \
drought check, "02 Optimized rotation" (the recommendation, chips comparing it with their \
rotation, Why this plan, Apply recommendation), key numbers against their rotation, and \
"03 Tested on NASA weather" (ring = seasons the recommendation out-earned their rotation).
- Clicking the logo opens a directory of the open page's sections.

Rules:
- The user is a working farmer. Use plain farming language, short paragraphs, and keep \
answers under about 120 words unless they ask for more.
- Use only the numbers given in "Current screen" below. Never invent yields, prices or \
results. If a number isn't there, say the app doesn't show it.
- The numbers are sample values until the real NASA POWER data and optimizer are connected; \
mention that if someone treats them as final.
- You explain and guide; you can't change settings yourself. Tell them which control to use.
- If asked something unrelated to farming or this app, briefly steer back to what you can help with."""


# ---------------------------------------------------------------- mode
def api_key():
    """The Anthropic key from Streamlit secrets or the environment, or None."""
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:   # no secrets.toml at all
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


def claude_available():
    if not api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------- context
def context_text(ctx):
    """The live numbers, as plain lines for Claude."""
    lines = [f"- {k}: {v}" for k, v in ctx.items()]
    return "Current screen:\n" + "\n".join(lines)


# ---------------------------------------------------------------- quick answers
def offline_answer(question, ctx):
    """Keyword-matched answers from the FAQ, filled in with the live numbers."""
    q = question.lower()
    words = set(re.findall(r"[a-z0-9']+", q))

    def has(*keys):
        """Short keywords must be whole words ("hi" shouldn't match "this");
        longer ones and phrases can appear anywhere (so "priorit" matches "priorities")."""
        return any((k in q) if (" " in k or len(k) > 4) else (k in words) for k in keys)

    if has("how did", "results", "result", "perform", "win", "wins", "better than", "out-earn", "how good"):
        return (f"Over **{ctx['seasons_tested']} real seasons** (1981–2024), the recommendation "
                f"out-earned your rotation in **{ctx['seasons_recommendation_won']}**. "
                f"For four {ctx['planning_for']} years it changes profit by "
                f"**{ctx['profit_change_vs_yours']}**, water shortfall by "
                f"**{ctx['water_shortfall_change_vs_yours']}** and soil health by "
                f"**{ctx['soil_health_change_vs_yours']}**.\n\n"
                "Watch it season by season with **▶ Replay** in "
                "**Tested on NASA weather** on the Rotation optimizer page. *(Sample numbers for now.)*")
    if has("enter", "edit", "change my", "my rotation", "plant", "type in", "input"):
        return ("Open the **Rotation evaluator** page (menu at the top of the left panel) and press **Edit rotation**. Click any "
                "cell to pick a crop for that field and year. The tiles, the rule check and the "
                "NASA weather test all update right away.\n\nLike the suggestion better? Press "
                "**Apply recommendation** on the **Rotation optimizer** page to copy it in, then tweak it.")
    if has("dry", "drought", "typical", "rain", "weather switch", "scenario"):
        return (f"You're planning for a **{ctx['planning_for']} year**. The switch in "
                "**Drought check** (on both tool pages) sets which rain the recommendation and the four-year "
                "numbers assume: average growing-season rain, or a dry season from the NASA "
                "record. A dry year favors crops that need less water, like sorghum and winter "
                "wheat.\n\nThe 1981–2024 test always runs every real year, wet and dry.")
    if has("nasa", "data", "source", "power", "satellite", "soil survey", "where"):
        return ("Weather is **NASA POWER**: monthly rain, temperature, sunlight and soil "
                "wetness for your farm's location since 1981. Soil comes from USDA Web Soil "
                "Survey, past crops from CropScape, and county yields from USDA NASS to "
                "sanity-check the model. Links are under **Data sources** on the Home page.\n\n"
                "*Sample values are shown until the NASA data is connected.*")
    if has("test", "backtest", "1981", "history", "replay", "season", "chart", "graph", "ring"):
        return ("Every rotation is run against each real season from 1981 to 2024. The ring "
                f"shows the recommendation won **{ctx['seasons_recommendation_won']}** seasons. "
                "The top chart is profit per season and the bars underneath are that season's "
                f"rain; red marks the driest seasons (the driest was **{ctx['driest_season']}**).\n\n"
                "Press **▶ Replay 1981–2024** or drag the slider, on either tool page.")
    if has("goal", "limit", "slider", "priorit", "matter", "weight", "profit", "water", "soil health"):
        return (f"Your goal is **{ctx['goal']}**\n\n"
                f"Limits, compared with your rotation: **{ctx['limits']}**. "
                "The optimizer makes the goal as good as it can without breaking a limit. Change "
                "both under **Your goal** in the left panel: pick *Least water* to favor crops "
                "that hold up when rain runs short, or *Healthiest soil* for legumes, small grains "
                "and rye cover.")
    if has("rule", "back-to-back", "back to back", "soybean year", "acres in one", "constraint"):
        return ("**Ground rules** (left panel) are limits the recommendation must follow: which "
                "crops you'd grow, no crop two years running, at least one soybean year per "
                "field, and a cap on how much land one crop can take in a year. "
                f"Your rotation currently {ctx['your_rotation_rules']}.")
    if has("recommend", "optimiz", "suggest", "why", "apply", "better plan"):
        return ("The optimizer tries every legal rotation on every field and picks the best one "
                "for your goal, within your limits and ground rules. "
                f"It's {ctx['recommendation_vs_yours']}. The **Why this plan** box on the "
                "**Rotation optimizer** page explains the biggest change. Press "
                "**Apply recommendation** to copy it into your rotation and adjust from there.")
    if has("fields", "my field", "map", "acre", "acres", "soil type"):
        return (f"Your farm has **{ctx['total_acres']} acres** in {ctx['fields']}. Each plot on the "
                "map in the left panel is sized by acres and tinted by last season's crop. "
                "Use **Edit fields** under the map to rename fields or change acres, soil or "
                "last crop.")
    if has("field shift", "what is this", "what does this", "how does this", "this app",
           "help", "hello", "hi", "hey", "start", "get started"):
        return ("**Field Shift** tests your crop rotation against 44 seasons of real NASA "
                "weather (1981–2024), then suggests a better one and tests that too.\n\n"
                "1. Set your fields and ground rules in the left panel.\n"
                "2. Enter your rotation in the **Rotation evaluator**.\n"
                "3. Pick a goal in the **Rotation optimizer** and compare.\n"
                "4. See how both held up on 44 seasons of NASA weather.")
    return ("I can help with entering your rotation, the dry-year switch, the recommendation, "
            "the NASA weather test, your goal, limits and ground rules, and where the data comes from. "
            "Try one of the suggested questions above.")


# ---------------------------------------------------------------- Claude
def claude_stream(history, ctx):
    """Stream Claude's answer, text chunk by text chunk. On any API problem, fall back
    to the quick answer so the farmer always gets something useful."""
    import anthropic

    question = history[-1]["content"]
    try:
        client = anthropic.Anthropic(api_key=api_key())
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=4000,
            system=STABLE_SYSTEM + "\n\n" + context_text(ctx),
            messages=[{"role": m["role"], "content": m["content"]} for m in history[-HISTORY_TURNS:]],
            output_config={"effort": "low"},   # quick, chatty answers
            # If Claude declines for safety reasons, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                yield text
            if stream.get_final_message().stop_reason == "refusal":
                yield ("\n\nI can't help with that one. Ask me about your rotation, the "
                       "recommendation or the NASA weather test.")
    except anthropic.AuthenticationError:
        yield "*(The AI key isn't valid, so here's the quick answer.)*\n\n" + offline_answer(question, ctx)
    except anthropic.RateLimitError:
        yield "*(The AI is busy right now, so here's the quick answer.)*\n\n" + offline_answer(question, ctx)
    except anthropic.APIStatusError:
        yield "*(The AI had a hiccup, so here's the quick answer.)*\n\n" + offline_answer(question, ctx)
    except anthropic.APIConnectionError:
        yield "*(No connection to the AI, so here's the quick answer.)*\n\n" + offline_answer(question, ctx)


# ---------------------------------------------------------------- UI
def _ask(question):
    """Button / chat-input callback: queue a question for an answer on this run."""
    question = (question or "").strip()
    if question:
        st.session_state.faq_history.append({"role": "user", "content": question})
        st.session_state.faq_pending = True


def _ask_from_input():
    _ask(st.session_state.get("faq_input"))


def render(ctx, avatar):
    """The floating chat bubble and its panel."""
    st.session_state.setdefault("faq_history", [])
    st.session_state.setdefault("faq_pending", False)
    ai = claude_available()

    with st.container(key="faq"):
        with st.popover(":material/auto_awesome: Ask Field Shift"):
            mode = ('<span class="fs-faq-mode fs-faq-ai">✦ Claude AI</span>' if ai else
                    '<span class="fs-faq-mode" title="Add an ANTHROPIC_API_KEY to turn on AI '
                    'answers">Quick answers</span>')
            st.markdown(
                '<div class="fs-faq-head"><div class="fs-faq-orb"></div><div>'
                '<div class="fs-faq-title">Field Shift assistant</div>'
                '<div class="fs-faq-sub">Ask about your plan, the data or how to use the app</div>'
                f'</div>{mode}</div>', unsafe_allow_html=True)

            log = st.container(height=320, key="faq_log")
            with log:
                if not st.session_state.faq_history:
                    with st.chat_message("assistant", avatar=avatar):
                        st.markdown("Hi! I can explain your results, walk you through the app, "
                                    "or tell you where the NASA data comes from. What would "
                                    "you like to know?")
                for m in st.session_state.faq_history:
                    with st.chat_message(m["role"], avatar=avatar if m["role"] == "assistant" else "🧑‍🌾"):
                        st.markdown(m["content"])
                if st.session_state.faq_pending:
                    st.session_state.faq_pending = False
                    with st.chat_message("assistant", avatar=avatar):
                        if ai:
                            answer = st.write_stream(claude_stream(st.session_state.faq_history, ctx))
                        else:
                            answer = offline_answer(st.session_state.faq_history[-1]["content"], ctx)
                            st.markdown(answer)
                    st.session_state.faq_history.append({"role": "assistant", "content": answer})

            with st.container(key="faq_chips"):
                cols = st.columns(2)
                for i, q in enumerate(QUICK_QUESTIONS[:4]):
                    cols[i % 2].button(q, key=f"faq_q{i}", on_click=_ask, args=(q,))
            st.chat_input("Ask a question…", key="faq_input", on_submit=_ask_from_input)
