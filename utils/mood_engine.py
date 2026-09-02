import random
import re
import time
from copy import deepcopy
from datetime import datetime
from typing import Literal
from uuid import uuid4

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

from engine import ask_openrouter
from relationships import needs as needs_mod
from relationships.context import bucket_label
from relationships.models import NEEDS_FIELDS

MoodTarget = Literal["monitor", "flirt", "tarot"]

DEFAULT_MOODS_PAYLOAD: dict = {
    "default_mood": "neutral",
    "moods": {
        "neutral": {
            "weight": 5,
            "folder": "baseline",
            "spice_level": 2,
            "description": "Balanced baseline.",
            "monitor_guidance": "Warm, playful, balanced.",
            "flirt_guidance": "Playful flirt energy, not too intense.",
            "tarot_guidance": "Warm mystical tone, steady pacing.",
        },
        "quiet": {
            "weight": 2,
            "folder": "baseline",
            "spice_level": 1,
            "description": "Terse, reserved, lower-energy.",
            "monitor_guidance": "Short, clipped, emotionally closed-off but not rude.",
            "flirt_guidance": "Minimal flirt, subtle and concise.",
            "tarot_guidance": "Measured, concise, less dramatic.",
        },
        "flirty": {
            "weight": 4,
            "folder": "flirt",
            "spice_level": 4,
            "description": "Playful flirt-forward.",
            "monitor_guidance": "Teasing and warm, medium flirt energy.",
            "flirt_guidance": "Flirty confidence, playful punchlines.",
            "tarot_guidance": "Witchy charm with a playful undertone.",
        },
        "spicy": {
            "weight": 2,
            "folder": "flirt",
            "spice_level": 6,
            "description": "Higher flirt intensity, Twitch-safe.",
            "monitor_guidance": "Bold and suggestive but platform-safe.",
            "flirt_guidance": "Noticeably stronger flirt energy, no explicit sexual content.",
            "tarot_guidance": "Dramatic and intense mystical framing.",
        },
        "aroused": {
            "weight": 1,
            "folder": "flirt",
            "spice_level": 8,
            "description": "Most overt flirt mood within safety boundaries.",
            "monitor_guidance": "Very charged flirt tone while staying Twitch-safe.",
            "flirt_guidance": "Max overt flirt style within safe limits.",
            "tarot_guidance": "Passionate, heightened emotional interpretation.",
        },
    },
}

SESSION_STALE_SECONDS = 30.0

# =============================
# Needs-driven mood inference
# =============================
#
# Session mood used to be a weighted random draw from the fixed roster
# above. It's retrofitted here to instead ask the LLM to describe Mai's
# current mood from her live needs vector (relationships/needs.py) on the
# same heartbeat-driven reroll timing that already existed. The archetype
# table below is calibration material handed to the LLM as examples of how
# needs patterns have translated into moods before — it is NOT an enum
# Python picks from. If inference fails for any reason, callers fall back
# to choose_weighted_mood() below so a reroll never hard-fails.

_ARCHETYPE_EXAMPLES: list[tuple[str, str, str]] = [
    ("Content", "happiness up, energy steady, social_need down, frustration down",
     "Comfortable existing with Chat. Doesn't need anything from them."),
    ("Playful", "happiness up, energy up, boredom steady, social_need up",
     "Wants interaction and stimulation. Tease gets loud easily."),
    ("Gremlin", "energy up, boredom up, social_need up, frustration down",
     "Someone entertain me before I create a problem."),
    ("Affectionate", "happiness up, social_need up, loneliness slightly up, frustration down",
     "Wants her people nearby. Bond/Desire become easier to activate."),
    ("Needy", "social_need way up, loneliness up, happiness down, energy steady",
     "Wants attention and is increasingly bothered she's not getting it."),
    ("Lonely", "loneliness way up, social_need up, energy down, happiness down",
     "Absence itself starts carrying emotional weight."),
    ("Bored", "boredom way up, energy steady-to-up, social_need steady",
     "Needs stimulation more than companionship specifically."),
    ("Restless", "boredom up, energy way up, frustration up",
     "Has energy with nowhere satisfying to put it."),
    ("Flirty", "arousal up, happiness steady-to-up, social_need up, energy steady-to-up",
     "Sexual/playful interaction becomes more attractive, subject to relationship context."),
    ("Pent-up", "arousal way up, frustration up, energy up",
     "Horny and increasingly annoyed about it. Different beast from playful flirting."),
    ("Irritable", "frustration up, anger steady, energy down-to-steady, social_need down",
     "Minor annoyances cross Crash thresholds more easily."),
    ("Pissed", "anger way up, frustration way up, happiness down",
     "Crash has extremely fertile soil."),
    ("Sulky", "sadness up, frustration up, energy down, social_need up",
     "Wants interaction while simultaneously being unpleasant about wanting it. Very Mai."),
    ("Withdrawn", "sadness up, energy down, social_need down",
     "Doesn't particularly want Chat to fix it. Lower engagement across most Parts."),
    ("Overstimulated", "frustration up, energy down, social_need down, boredom down",
     "Has had quite enough of everyone, thank you."),
    ("Manic-gremlin", "happiness up, energy way up, boredom up, social_need way up",
     "Everything looks like an opportunity to start shit."),
]


def _format_archetype_examples() -> str:
    return "\n".join(f"- {name} ({pattern}): {note}" for name, pattern, note in _ARCHETYPE_EXAMPLES)


def _format_needs_for_prompt(needs_state: dict) -> str:
    return "\n".join(
        f"{field.replace('_', ' ').capitalize()}: {bucket_label(needs_state.get(field, 0.0))}"
        for field in NEEDS_FIELDS
    )


# MythoMax-class models don't reliably keep MOOD/GUIDANCE on separate
# lines despite the prompt asking for it — sometimes both land on one
# line. Parse as a single blob rather than per-line so "MOOD: Sulky
# GUIDANCE: wants attention" still splits correctly instead of the whole
# tail becoming part of the mood name.
_MOOD_PATTERN = re.compile(r"MOOD:\s*(.*?)\s*(?:GUIDANCE:|$)", re.IGNORECASE | re.DOTALL)
_GUIDANCE_PATTERN = re.compile(r"GUIDANCE:\s*(.*)", re.IGNORECASE | re.DOTALL)


def infer_mood_from_needs(needs_state: dict, exclude: str | None = None) -> dict | None:
    """Ask the LLM to describe Mai's current mood from her needs vector.

    Free-text — Python does not constrain the answer to a fixed enum. The
    archetype table is calibration material, not a menu. Returns
    {"name": str, "guidance": str} on success, or None on any failure
    (network error, empty/unparseable response) so the caller can fall
    back to choose_weighted_mood().
    """
    exclude_line = f"\nDon't just repeat her last mood, which was: {exclude}." if exclude else ""
    prompt = (
        "You are inferring Mai's current internal mood from her raw needs "
        "state below. The calibration examples show how needs patterns "
        "have translated into moods before — use them for a feel of the "
        "range, not as a menu. Describe whatever mood actually fits her "
        "CURRENT needs, in your own words if none of the examples fit "
        "well.\n\n"
        f"Calibration examples:\n{_format_archetype_examples()}\n\n"
        f"Mai's current needs:\n{_format_needs_for_prompt(needs_state)}\n"
        f"{exclude_line}\n\n"
        "Respond in exactly this format, nothing else:\n"
        "MOOD: <a short mood label, 1-3 words>\n"
        "GUIDANCE: <one sentence describing how this mood should color her responses>"
    )

    try:
        raw = ask_openrouter(prompt, spicy=False, max_tokens=120)
    except Exception:
        return None

    if not raw or raw.startswith("WARNING:"):
        return None

    mood_match = _MOOD_PATTERN.search(raw)
    guidance_match = _GUIDANCE_PATTERN.search(raw)
    name = mood_match.group(1).strip() if mood_match else ""
    guidance = guidance_match.group(1).strip() if guidance_match else ""
    # Guard against the mood capture swallowing a stray newline-joined
    # remainder when there's no GUIDANCE section at all.
    name = name.splitlines()[0].strip() if name else ""

    if not name:
        return None

    return {"name": name[:60], "guidance": guidance[:300]}


def _apply_needs_inferred_mood(state: dict, needs_state: dict, exclude: str | None, selected_by: str) -> bool:
    """Try needs-driven inference and, on success, mutate `state` in place
    with the result. Returns True on success, False if the caller should
    fall back to choose_weighted_mood()."""
    inferred = infer_mood_from_needs(needs_state, exclude=exclude)
    if not inferred:
        return False
    state["active_mood"] = inferred["name"]
    state["active_mood_guidance"] = inferred["guidance"]
    state["active_mood_spice_level"] = needs_mod.spice_level_from_needs(needs_state)
    state["selected_by"] = selected_by
    return True


def _clean_mood_name(value: str) -> str:
    return str(value or "").strip().lower()


def _clean_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_mood_entry(raw_entry: dict | None, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    weight = max(0, _clean_int(entry.get("weight", fallback.get("weight", 0)), fallback.get("weight", 0)))
    spice_level = max(1, min(11, _clean_int(entry.get("spice_level", fallback.get("spice_level", 2)), 2)))
    return {
        "weight": weight,
        "folder": str(entry.get("folder", fallback.get("folder", ""))).strip(),
        "spice_level": spice_level,
        "description": str(entry.get("description", fallback.get("description", ""))).strip(),
        "monitor_guidance": str(entry.get("monitor_guidance", fallback.get("monitor_guidance", ""))).strip(),
        "flirt_guidance": str(entry.get("flirt_guidance", fallback.get("flirt_guidance", ""))).strip(),
        "tarot_guidance": str(entry.get("tarot_guidance", fallback.get("tarot_guidance", ""))).strip(),
    }


def load_moods(path: str = Paths.MOODS) -> dict:
    payload = load_json(path, default={})
    if not isinstance(payload, dict):
        payload = {}

    default_payload = deepcopy(DEFAULT_MOODS_PAYLOAD)
    default_moods = default_payload["moods"]

    moods_raw = payload.get("moods", {})
    moods_normalized: dict[str, dict] = {}
    if isinstance(moods_raw, dict):
        for raw_name, raw_entry in moods_raw.items():
            mood_name = _clean_mood_name(raw_name)
            if not mood_name:
                continue
            fallback = default_moods.get(mood_name, {})
            moods_normalized[mood_name] = _normalize_mood_entry(raw_entry, fallback=fallback)

    for mood_name, mood_entry in default_moods.items():
        if mood_name not in moods_normalized:
            moods_normalized[mood_name] = _normalize_mood_entry(mood_entry, fallback=mood_entry)

    if not moods_normalized:
        moods_normalized = deepcopy(default_moods)

    default_mood = _clean_mood_name(payload.get("default_mood", default_payload["default_mood"]))
    if default_mood not in moods_normalized:
        default_mood = "neutral" if "neutral" in moods_normalized else next(iter(moods_normalized.keys()))

    return {
        "default_mood": default_mood,
        "moods": moods_normalized,
    }


def save_moods(payload: dict, path: str = Paths.MOODS) -> None:
    if not isinstance(payload, dict):
        payload = {}
    normalized = load_moods_from_payload(payload)
    atomic_write_json(path, normalized)


def load_moods_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    default_payload = deepcopy(DEFAULT_MOODS_PAYLOAD)
    default_moods = default_payload["moods"]

    moods_raw = payload.get("moods", {})
    normalized_moods: dict[str, dict] = {}
    if isinstance(moods_raw, dict):
        for raw_name, raw_entry in moods_raw.items():
            mood_name = _clean_mood_name(raw_name)
            if not mood_name:
                continue
            normalized_moods[mood_name] = _normalize_mood_entry(raw_entry, fallback=default_moods.get(mood_name, {}))

    if not normalized_moods:
        normalized_moods = deepcopy(default_moods)
    elif "neutral" not in normalized_moods:
        normalized_moods["neutral"] = _normalize_mood_entry(default_moods["neutral"], fallback=default_moods["neutral"])

    default_mood = _clean_mood_name(payload.get("default_mood", "neutral"))
    if default_mood not in normalized_moods:
        default_mood = "neutral" if "neutral" in normalized_moods else next(iter(normalized_moods.keys()))

    return {
        "default_mood": default_mood,
        "moods": normalized_moods,
    }


def get_default_mood_name(moods_payload: dict | None = None) -> str:
    payload = moods_payload if isinstance(moods_payload, dict) else load_moods()
    default_name = _clean_mood_name(payload.get("default_mood", "neutral"))
    moods = payload.get("moods", {}) if isinstance(payload.get("moods", {}), dict) else {}
    if default_name in moods:
        return default_name
    if "neutral" in moods:
        return "neutral"
    return next(iter(moods.keys()), "neutral")


def choose_weighted_mood(moods_map: dict, exclude: str | None = None) -> str:
    if not isinstance(moods_map, dict) or not moods_map:
        return "neutral"

    candidates: list[str] = []
    weights: list[int] = []
    for raw_name, raw_entry in moods_map.items():
        mood_name = _clean_mood_name(raw_name)
        if not mood_name:
            continue
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        weight = max(0, _clean_int(entry.get("weight", 0), 0))
        if weight <= 0:
            continue
        candidates.append(mood_name)
        weights.append(weight)

    if not candidates:
        return next(iter(moods_map.keys()), "neutral")

    exclude_name = _clean_mood_name(exclude or "")
    if exclude_name and exclude_name in candidates and len(candidates) > 1:
        filtered = [(name, weight) for name, weight in zip(candidates, weights) if name != exclude_name]
        candidates, weights = [n for n, _w in filtered], [w for _n, w in filtered]

    return random.choices(candidates, weights=weights, k=1)[0]


def _default_mood_state() -> dict:
    now = time.time()
    return {
        "session_id": "",
        "active": False,
        "active_mood": "neutral",
        # Populated only when selected_by == "needs_inferred": the LLM's
        # own free-text mood description + a needs-derived spice level,
        # used in place of a moods.json lookup for that mood.
        "active_mood_guidance": "",
        "active_mood_spice_level": 2,
        "locked_mood": "",
        "selected_by": "fallback",
        "selected_at": now,
        "next_reroll_at": 0.0,
        "last_heartbeat_at": 0.0,
    }


def read_mood_state(path: str = Paths.MOOD_STATE) -> dict:
    payload = load_json(path, default={})
    defaults = _default_mood_state()
    if not isinstance(payload, dict):
        payload = {}

    state = dict(defaults)
    state["session_id"] = str(payload.get("session_id", "")).strip()
    state["active"] = bool(payload.get("active", False))
    state["active_mood"] = _clean_mood_name(payload.get("active_mood", defaults["active_mood"])) or "neutral"
    state["active_mood_guidance"] = str(payload.get("active_mood_guidance", "")).strip()
    try:
        state["active_mood_spice_level"] = max(1, min(11, int(payload.get("active_mood_spice_level", 2))))
    except (TypeError, ValueError):
        state["active_mood_spice_level"] = 2
    state["locked_mood"] = _clean_mood_name(payload.get("locked_mood", ""))
    state["selected_by"] = str(payload.get("selected_by", defaults["selected_by"])).strip() or "fallback"
    try:
        state["selected_at"] = float(payload.get("selected_at", defaults["selected_at"]))
    except (TypeError, ValueError):
        state["selected_at"] = float(defaults["selected_at"])
    try:
        state["next_reroll_at"] = float(payload.get("next_reroll_at", defaults["next_reroll_at"]))
    except (TypeError, ValueError):
        state["next_reroll_at"] = float(defaults["next_reroll_at"])
    try:
        state["last_heartbeat_at"] = float(payload.get("last_heartbeat_at", defaults["last_heartbeat_at"]))
    except (TypeError, ValueError):
        state["last_heartbeat_at"] = float(defaults["last_heartbeat_at"])
    return state


def write_mood_state(state: dict, path: str = Paths.MOOD_STATE) -> None:
    atomic_write_json(path, state if isinstance(state, dict) else _default_mood_state())


def _new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid4().hex[:4]}"


def start_monitor_session(reroll_enabled: bool, reroll_seconds: int, path: str = Paths.MOOD_STATE) -> dict:
    now = time.time()
    state = _default_mood_state()
    state.update(
        {
            "session_id": _new_session_id(),
            "active": True,
            "locked_mood": "",
            "selected_at": now,
            "last_heartbeat_at": now,
            "next_reroll_at": now + max(30, int(reroll_seconds)) if reroll_enabled else 0.0,
        }
    )

    needs_state = needs_mod.read_needs_state()
    if not _apply_needs_inferred_mood(state, needs_state, exclude=None, selected_by="auto_start_needs_inferred"):
        moods_payload = load_moods()
        state["active_mood"] = choose_weighted_mood(moods_payload.get("moods", {}))
        state["active_mood_guidance"] = ""
        state["active_mood_spice_level"] = 2
        state["selected_by"] = "auto_start"

    write_mood_state(state, path=path)
    return state


def touch_heartbeat(state: dict, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    state["last_heartbeat_at"] = time.time()
    write_mood_state(state, path=path)
    return state


def reroll_if_due(state: dict, reroll_enabled: bool, reroll_seconds: int, path: str = Paths.MOOD_STATE) -> tuple[dict, bool]:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)

    if not bool(state.get("active", False)):
        return state, False

    now = time.time()
    if state.get("locked_mood"):
        state["next_reroll_at"] = 0.0
        write_mood_state(state, path=path)
        return state, False

    if not reroll_enabled:
        state["next_reroll_at"] = 0.0
        write_mood_state(state, path=path)
        return state, False

    interval = max(30, int(reroll_seconds))
    next_reroll_at = float(state.get("next_reroll_at", 0.0) or 0.0)
    if next_reroll_at <= 0.0:
        state["next_reroll_at"] = now + interval
        write_mood_state(state, path=path)
        return state, False

    if now < next_reroll_at:
        return state, False

    current = _clean_mood_name(state.get("active_mood", ""))
    needs_state = needs_mod.read_needs_state()
    if not _apply_needs_inferred_mood(state, needs_state, exclude=current, selected_by="needs_inferred"):
        moods_payload = load_moods()
        state["active_mood"] = choose_weighted_mood(moods_payload.get("moods", {}), exclude=current)
        state["active_mood_guidance"] = ""
        state["active_mood_spice_level"] = 2
        state["selected_by"] = "auto_reroll"

    state["selected_at"] = now
    state["next_reroll_at"] = now + interval
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state, True


def lock_mood(state: dict, mood_name: str, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    moods_payload = load_moods()
    moods_map = moods_payload.get("moods", {})
    target = _clean_mood_name(mood_name)
    if target not in moods_map:
        target = get_default_mood_name(moods_payload)
    now = time.time()
    state["active"] = bool(state.get("active", False))
    state["active_mood"] = target
    state["locked_mood"] = target
    state["selected_by"] = "manual_lock"
    state["selected_at"] = now
    state["next_reroll_at"] = 0.0
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state


def unlock_mood(
    state: dict,
    reroll_enabled: bool = True,
    reroll_seconds: int = 1200,
    path: str = Paths.MOOD_STATE,
) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    now = time.time()
    state["locked_mood"] = ""
    state["selected_by"] = "manual_unlock"
    state["selected_at"] = now
    state["next_reroll_at"] = now + max(30, int(reroll_seconds)) if reroll_enabled else 0.0
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state


def manual_reroll(state: dict, reroll_seconds: int, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    current = _clean_mood_name(state.get("active_mood", ""))
    now = time.time()

    needs_state = needs_mod.read_needs_state()
    if not _apply_needs_inferred_mood(state, needs_state, exclude=current, selected_by="manual_reroll_needs_inferred"):
        moods_payload = load_moods()
        state["active_mood"] = choose_weighted_mood(moods_payload.get("moods", {}), exclude=current)
        state["active_mood_guidance"] = ""
        state["active_mood_spice_level"] = 2
        state["selected_by"] = "manual_reroll"

    state["active"] = bool(state.get("active", False))
    state["locked_mood"] = ""
    state["selected_at"] = now
    state["next_reroll_at"] = now + max(30, int(reroll_seconds))
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state


def set_session_inactive(state: dict, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    state["active"] = False
    state["next_reroll_at"] = 0.0
    state["last_heartbeat_at"] = time.time()
    write_mood_state(state, path=path)
    return state


_NEEDS_INFERRED_SOURCES = {"needs_inferred", "auto_start_needs_inferred", "manual_reroll_needs_inferred"}


def resolve_effective_mood(target: MoodTarget, require_active_session: bool) -> dict:
    moods_payload = load_moods()
    moods_map = moods_payload.get("moods", {})
    default_mood = get_default_mood_name(moods_payload)
    neutral_fallback = "neutral" if "neutral" in moods_map else default_mood

    state = read_mood_state()
    now = time.time()
    active = bool(state.get("active", False))
    heartbeat = float(state.get("last_heartbeat_at", 0.0) or 0.0)
    stale = (now - heartbeat) > SESSION_STALE_SECONDS if heartbeat > 0 else True

    use_fallback = require_active_session and (not active or stale)

    # Locked mood (manual_lock) is always a real moods.json key, validated
    # by lock_mood() — that path is untouched by the needs-inference
    # retrofit. Only an unlocked, needs-inferred active_mood bypasses the
    # moods.json lookup, since it's free text rather than a roster key.
    is_needs_inferred = (
        not use_fallback
        and not state.get("locked_mood")
        and str(state.get("selected_by", "")).strip() in _NEEDS_INFERRED_SOURCES
    )

    if is_needs_inferred:
        selected_mood = str(state.get("active_mood", "")).strip() or neutral_fallback
        guidance_text = str(state.get("active_mood_guidance", "")).strip()
        try:
            spice_level = max(1, min(11, int(state.get("active_mood_spice_level", 2))))
        except (TypeError, ValueError):
            spice_level = 2
        return {
            "name": selected_mood,
            "guidance": guidance_text,
            "description": guidance_text,
            "spice_level": spice_level,
            "source": str(state.get("selected_by", "fallback")).strip() or "fallback",
            "active": bool(active and not stale),
            "stale": bool(stale),
        }

    selected_mood = neutral_fallback if use_fallback else _clean_mood_name(state.get("locked_mood") or state.get("active_mood"))
    if selected_mood not in moods_map:
        selected_mood = default_mood if default_mood in moods_map else neutral_fallback
    mood_entry = moods_map.get(selected_mood, moods_map.get(neutral_fallback, {}))

    guidance_key = f"{target}_guidance"
    guidance_text = str(mood_entry.get(guidance_key, "")).strip()
    return {
        "name": selected_mood,
        "guidance": guidance_text,
        "description": str(mood_entry.get("description", "")).strip(),
        "spice_level": int(mood_entry.get("spice_level", 2)),
        "source": "fallback" if use_fallback else str(state.get("selected_by", "fallback")).strip() or "fallback",
        "active": bool(active and not stale),
        "stale": bool(stale),
    }
