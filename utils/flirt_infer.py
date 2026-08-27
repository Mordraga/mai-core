"""
Flirt inference utilities for channel-point redemptions.

Provides:
  - infer_flirt_params()  — LLM-assisted natural-language → {theme, tone, spice}
  - generate_flirt()      — build prompt + call LLM, returns a single flirt line
"""

import json
import random

from engine import ask_openrouter, build_prompt_from_keyword, get_personality_spice_params
from utils.helpers import load_json
from utils.mood_engine import resolve_effective_mood
from utils.paths import Paths


def infer_flirt_params(
    user_input: str,
    themes_data: dict,
    tones_data: dict,
) -> dict | None:
    """Map free-text user input to the closest valid {theme, tone, spice}.

    Returns a dict with keys ``theme``, ``tone``, ``spice`` (int 1-10) on
    success, or ``None`` if the input is empty or the LLM response cannot be
    parsed.
    """
    text = (user_input or "").strip()
    if not text:
        return None

    valid_themes = sorted(themes_data.keys())
    valid_tones = sorted(tones_data.keys())

    prompt = (
        f"Available themes: {valid_themes}\n"
        f"Available tones: {valid_tones}\n"
        f"Spice scale: 1 (very mild) to 10 (maximum intensity)\n\n"
        f"User input: \"{text}\"\n\n"
        "Map the user's intent to the closest valid theme, tone, and appropriate spice level.\n"
        "Reply with ONLY valid JSON — no explanation, no markdown:\n"
        "{\"theme\": \"<theme>\", \"tone\": \"<tone>\", \"spice\": <1-10>}"
    )

    raw = ask_openrouter(prompt, spicy=False)
    if not raw or raw.startswith("WARNING:"):
        return None

    # Extract JSON from response (model may wrap it in prose)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end <= start:
        return None

    try:
        parsed = json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None

    theme = str(parsed.get("theme", "")).strip().lower()
    tone = str(parsed.get("tone", "")).strip().lower()
    spice_raw = parsed.get("spice", 3)

    try:
        spice = max(1, min(10, int(spice_raw)))
    except (TypeError, ValueError):
        spice = 3

    # Validate against actual keys
    if theme not in themes_data:
        theme = None
    if tone not in tones_data:
        tone = None

    if not theme and not tone:
        return None

    return {"theme": theme, "tone": tone, "spice": spice}


def generate_flirt(
    username: str,
    theme: str,
    tone: str,
    spice: int,
    mood_context: dict | None = None,
) -> str:
    """Generate a single flirt line using the standard flirt template pipeline."""
    themes_data = load_json(Paths.THEMES, default={})
    tones_data = load_json(Paths.TONES, default={})
    spice_data = load_json(Paths.SPICE, default={})

    if mood_context is None:
        mood_context = resolve_effective_mood("flirt", require_active_session=False)

    theme_obj = themes_data.get(theme, {})
    tone_obj = tones_data.get(tone, {})
    spice_obj = spice_data.get(str(spice), {})

    prompt_context = {
        "theme": theme,
        "tone": tone,
        "level": spice,
        "theme_desc": theme_obj.get("description") or "No description available.",
        "tone_desc": tone_obj.get("description") or "No description available.",
        "spice_desc": spice_obj.get("description") or "No description available.",
        "theme_anchors": theme_obj.get("anchors", []),
        "tone_anchors": tone_obj.get("anchors", []),
        "spice_anchors": spice_obj.get("anchors", []),
        "mood_name": mood_context.get("name", "neutral"),
        "mood_guidance": mood_context.get("guidance", ""),
    }

    prompt = build_prompt_from_keyword("flirt", context=prompt_context)
    if prompt.startswith("WARNING:"):
        return ""

    clamped_spice, spicy = get_personality_spice_params(spice)
    return ask_openrouter(prompt, spicy=spicy)


def resolve_flirt_params(user_input: str) -> tuple[str | None, str | None, int | None, bool]:
    """Parse and/or infer flirt params from free-text user input.

    Returns (theme, tone, spice, needs_correction).
    ``needs_correction`` is True when inference was used instead of structured syntax,
    meaning the caller should show the user the correct syntax alongside the flirt.
    """
    from utils.helpers import parse_all_params

    themes_data = load_json(Paths.THEMES, default={})
    tones_data = load_json(Paths.TONES, default={})

    # Try structured parse first
    structured = parse_all_params(user_input or "")
    theme = structured.get("theme")
    tone = structured.get("tone")
    spice = structured.get("spice")

    # Clear invalid structured values
    if theme and theme not in themes_data:
        theme = None
    if tone and tone not in tones_data:
        tone = None
    if spice is not None and not (1 <= int(spice) <= 10):
        spice = None

    all_structured = bool(theme and tone and spice is not None)

    # If anything missing and user typed something, try LLM inference
    needs_correction = False
    if not all_structured and (user_input or "").strip():
        inferred = infer_flirt_params(user_input, themes_data, tones_data)
        if inferred:
            theme = theme or inferred.get("theme")
            tone = tone or inferred.get("tone")
            spice = spice if spice is not None else inferred.get("spice")
            needs_correction = True

    # Final random fallback
    if not theme:
        theme = random.choice(list(themes_data.keys())) if themes_data else "pagan"
        needs_correction = needs_correction or bool((user_input or "").strip())
    if not tone:
        tone = random.choice(list(tones_data.keys())) if tones_data else "sultry"
        needs_correction = needs_correction or bool((user_input or "").strip())
    if spice is None:
        spice = random.randint(1, 5)

    return theme, tone, int(spice), needs_correction
