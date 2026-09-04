"""LLM-driven relationship mutation inference (spec Phase 4).

Mirrors utils/mood_engine.py::infer_mood_from_needs()'s shape: Python builds
a compact snapshot of what just happened, the LLM infers *what it means* —
which relationship dimensions should move, which way, and whether anything
is worth remembering — and Python owns turning that qualitative judgment
into a small bounded numeric change plus validated, capped persistence. The
LLM never hands back a raw float for a delta or a confidence; it picks from
a small fixed vocabulary (up/down, slightly/moderately/strongly,
low/moderate/high) that Python maps to fixed numbers, the same reason
mood_engine parses "MOOD:"/"GUIDANCE:" lines instead of trusting arbitrary
LLM-authored numbers.

On any inference failure (network error, unparseable response, or the
model judging nothing changed) this returns None and the caller keeps the
relationship exactly as it was — inference is an enhancement to Phase 4,
never a hard dependency for a response to go out.
"""
from __future__ import annotations

import re
import time

from engine import ask_openrouter
from relationships.context import bucket_label
from relationships.models import RELATIONSHIP_FIELDS, clamp01

# Max absolute movement a single exchange can apply to any one primitive —
# spec 28: "A single ordinary message should rarely rewrite a mature
# relationship." The LLM only ever picks a qualitative intensity; this is
# the only place a number gets attached to it.
_INTENSITY_STEPS = {"slightly": 0.02, "moderately": 0.05, "strongly": 0.08}
_MAX_SINGLE_DELTA = max(_INTENSITY_STEPS.values())

_CONFIDENCE_STEPS = {"low": 0.35, "moderate": 0.6, "high": 0.85}

# Observations are capped so a long-running relationship can't accumulate
# an unbounded remembered-facts list — keep what Mai is most sure about /
# what has come up most, drop the rest.
_MAX_OBSERVATIONS = 40

_DELTA_LINE_PATTERN = re.compile(
    r'^\s*(' + '|'.join(RELATIONSHIP_FIELDS) + r')\s*:\s*(up|down)\s+(slightly|moderately|strongly)\s*$',
    re.IGNORECASE | re.MULTILINE,
)
# pet_peeve/preference are memory-log entries (spec 30) — merge_observation
# accumulates and reinforces them. callback is the same mechanism applied
# to a specific memorable moment worth referencing later (spec 34,
# "associative memories" — deliberately not a separate data structure,
# just another observation type). nickname is different in kind: a single
# *current* belief that overwrites rather than accumulates (spec 32),
# routed to profile["nickname"] instead of the observations list — see
# relationship_core.post_response_update.
_OBSERVATION_PATTERN = re.compile(
    r'^\s*OBSERVATION:\s*(pet_peeve|preference|callback|nickname)\s*\|\s*([a-z0-9_]+)\s*\|\s*(low|moderate|high)\s*\|\s*(.+?)\s*$',
    re.IGNORECASE | re.MULTILINE,
)
# One-level theory of mind (spec 31): what Mai currently believes this
# person wants and believes about her. A single current snapshot belief
# like nickname, not a growing log — it overwrites the previous read
# rather than accumulating a history of past guesses.
_THEORY_OF_MIND_PATTERN = re.compile(
    r'^\s*THEORY_OF_MIND:\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(low|moderate|high)\s*$',
    re.IGNORECASE | re.MULTILINE,
)


def _format_relationship_for_prompt(relationship: dict) -> str:
    return "\n".join(
        f"{field.replace('_', ' ').capitalize()}: {bucket_label(relationship.get(field, 0.0))}"
        for field in RELATIONSHIP_FIELDS
    )


def _format_recent_for_prompt(username: str, recent_messages: list[str] | None) -> str:
    cleaned = [str(m).strip() for m in (recent_messages or []) if str(m).strip()]
    if not cleaned:
        return ""
    lines = "\n".join(f"- {m}" for m in cleaned[-5:])
    return f"\n{username}'s last few messages, for spotting a pattern or repetition:\n{lines}\n"


def infer_relationship_update(
    username: str,
    message: str,
    response: str,
    relationship: dict,
    recent_messages: list[str] | None = None,
) -> dict | None:
    """Ask the LLM what this exchange means for the relationship.

    Returns {"deltas": {...}, "observation": {...} | None,
    "theory_of_mind": {...} | None} on success (with at least one of the
    three non-empty), or None on any failure or when the model judges
    nothing changed — the caller should treat None as "leave the
    relationship exactly as it was".
    """
    recent_block = _format_recent_for_prompt(username, recent_messages)
    prompt = (
        "You are inferring how a single chat exchange should nudge Mai's "
        "persistent relationship with one specific person. Most ordinary "
        "exchanges should change little or nothing at all — only note real "
        "movement, not routine banter. A genuine apology or repair can "
        "ease resentment even if trust doesn't fully recover yet; a "
        "pattern of unwanted behavior can build resentment even while "
        "other dimensions stay stable — these don't have to move together.\n\n"
        f"Mai's current relationship with {username}:\n"
        f"{_format_relationship_for_prompt(relationship)}\n"
        f"{recent_block}\n"
        f'{username} said: "{message}"\n'
        f'Mai replied: "{response}"\n\n'
        "Respond in exactly this format, nothing else:\n"
        "- One line per relationship dimension that should genuinely shift "
        "because of THIS exchange, as: <dimension>: <up|down> "
        "<slightly|moderately|strongly>. Omit any dimension that shouldn't "
        "change. Valid dimensions: " + ", ".join(RELATIONSHIP_FIELDS) + ".\n"
        "- Optionally, one line if this exchange revealed something worth "
        "remembering about this person, as: OBSERVATION: "
        "<pet_peeve|preference|callback|nickname> | <a short snake_case "
        "name> | <low|moderate|high confidence> | <for pet_peeve/"
        "preference/callback, one sentence note; for nickname, the "
        "nickname itself>. pet_peeve/preference are standing traits; "
        "callback is one specific memorable moment worth bringing up "
        "again later; nickname is only worth naming if something in THIS "
        "exchange actually earned one — most people don't get one.\n"
        "- Optionally, one line updating Mai's current read of this "
        "person, as: THEORY_OF_MIND: <what Mai thinks this person wants "
        "right now, one short phrase> | <what Mai thinks this person "
        "currently believes about her, one short phrase> | <low|moderate"
        "|high confidence>\n"
        "- If nothing should change and nothing is worth noting, respond "
        "with exactly: NONE"
    )

    try:
        raw = ask_openrouter(prompt, spicy=False, max_tokens=260)
    except Exception:
        return None

    if not raw or raw.startswith("WARNING:"):
        return None
    if raw.strip().upper() == "NONE":
        return None

    deltas: dict[str, float] = {}
    for field, direction, intensity in _DELTA_LINE_PATTERN.findall(raw):
        step = _INTENSITY_STEPS.get(intensity.lower(), 0.0)
        deltas[field.lower()] = step if direction.lower() == "up" else -step

    observation = None
    obs_match = _OBSERVATION_PATTERN.search(raw)
    if obs_match:
        obs_type, name, confidence_label, note = obs_match.groups()
        observation = {
            "type": obs_type.lower(),
            "name": name.lower(),
            "confidence": _CONFIDENCE_STEPS.get(confidence_label.lower(), 0.5),
            "note": note.strip()[:200],
        }

    theory_of_mind = None
    tom_match = _THEORY_OF_MIND_PATTERN.search(raw)
    if tom_match:
        believed_wants, believed_view_of_mai, confidence_label = tom_match.groups()
        theory_of_mind = {
            "believed_wants": believed_wants.strip()[:150],
            "believed_view_of_mai": believed_view_of_mai.strip()[:150],
            "confidence": _CONFIDENCE_STEPS.get(confidence_label.lower(), 0.5),
        }

    if not deltas and not observation and not theory_of_mind:
        return None

    return {"deltas": deltas, "observation": observation, "theory_of_mind": theory_of_mind}


def apply_bounded_deltas(relationship: dict, deltas: dict[str, float]) -> dict:
    """Apply `deltas` to `relationship`, clamped to [0, 1] and defensively
    re-bounded to the same per-message movement cap infer_relationship_update
    already enforces via its fixed intensity vocabulary — this is a second,
    independent gate so a malformed/unexpected deltas dict from any future
    caller still can't move a primitive further than one exchange should."""
    result = dict(relationship)
    for field, delta in deltas.items():
        if field not in RELATIONSHIP_FIELDS:
            continue
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            continue
        bounded = max(-_MAX_SINGLE_DELTA, min(_MAX_SINGLE_DELTA, delta))
        result[field] = clamp01(float(result.get(field, 0.0)) + bounded)
    return result


def merge_observation(observations: list, observation: dict | None) -> list:
    """Insert a new observation, or reinforce an existing one with the same
    (type, name): bump confidence slightly (capped), increment
    reinforced_count, and refresh last_reinforced — repeated behavior
    should read as more established, not just re-logged as a duplicate."""
    if not observation:
        return observations if isinstance(observations, list) else []

    obs_type = observation.get("type")
    name = observation.get("name")
    if not obs_type or not name:
        return observations if isinstance(observations, list) else []

    now = time.time()
    result = [dict(o) for o in observations if isinstance(o, dict)] if isinstance(observations, list) else []

    for existing in result:
        if existing.get("type") == obs_type and existing.get("name") == name:
            existing["confidence"] = min(0.97, float(existing.get("confidence", 0.5)) + 0.05)
            existing["reinforced_count"] = int(existing.get("reinforced_count", 1)) + 1
            existing["last_reinforced"] = now
            existing["note"] = observation.get("note") or existing.get("note", "")
            return result

    result.append({
        "type": obs_type,
        "name": name,
        "confidence": observation.get("confidence", 0.5),
        "note": observation.get("note", ""),
        "reinforced_count": 1,
        "last_reinforced": now,
    })

    if len(result) > _MAX_OBSERVATIONS:
        result.sort(key=lambda o: float(o.get("confidence", 0)) * int(o.get("reinforced_count", 1)), reverse=True)
        result = result[:_MAX_OBSERVATIONS]
    return result
