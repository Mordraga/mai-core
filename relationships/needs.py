"""Global (not per-user) transient needs state.

Mirrors utils/mood_engine.py's caller-driven pattern: mai-core has no
background loop of its own, so decay is a pure function of elapsed time
that the consuming app calls on its own heartbeat, same as
touch_heartbeat/reroll_if_due.
"""
from __future__ import annotations

import threading
import time

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

from relationships.models import DEFAULT_NEEDS, NEEDS_FIELDS, clamp01, clamp_state

# Guards every read-modify-write cycle in this module. Needs mutation is
# called from multiple threads in a live monitor (the main heartbeat loop
# and one thread per in-flight chat response), so read-then-write must be
# serialized to avoid one thread's update clobbering another's.
_needs_lock = threading.Lock()

# Per-need drift-per-second rates. Positive = rises toward 1.0 over time when
# left alone; negative = decays toward 0.0. Tunable — these are starting
# points, not tuned-from-data values.
#
# Rationale sketch (not exhaustive):
#  - arousal decays fast when nothing is reinforcing it.
#  - loneliness and boredom creep up slowly during silence.
#  - energy recovers slowly at rest, frustration/anger cool off slowly.
#  - happiness/social_need drift gently toward their neutral defaults.
_DECAY_PER_SECOND: dict[str, float] = {
    "happiness": 0.0,
    "sadness": -0.00002,
    "frustration": -0.00003,
    "anger": -0.00005,
    "energy": 0.00002,
    "arousal": -0.0002,
    "boredom": 0.00004,
    "social_need": 0.00003,
    "loneliness": 0.00002,
}


def read_needs_state() -> dict:
    try:
        raw = load_json(Paths.NEEDS_STATE, default={})
    except (ValueError, OSError):
        # Corrupt file (invalid JSON) or unreadable — treat like "missing".
        raw = {}
    if not isinstance(raw, dict):
        state = dict(DEFAULT_NEEDS)
    else:
        state = clamp_state(raw, NEEDS_FIELDS, DEFAULT_NEEDS)
    return state


def write_needs_state(state: dict) -> None:
    clamped = clamp_state(state, NEEDS_FIELDS, DEFAULT_NEEDS)
    atomic_write_json(Paths.NEEDS_STATE, clamped)


def decay_needs(state: dict, elapsed_seconds: float) -> dict:
    """Return a new needs dict drifted by `elapsed_seconds` of inactivity.

    Pure function — does not read or write the persisted state file. Caller
    is expected to read, decay, mutate as needed, then write.
    """
    current = clamp_state(state, NEEDS_FIELDS, DEFAULT_NEEDS)
    try:
        elapsed = max(0.0, float(elapsed_seconds))
    except (TypeError, ValueError):
        elapsed = 0.0

    result = {}
    for key in NEEDS_FIELDS:
        rate = _DECAY_PER_SECOND.get(key, 0.0)
        result[key] = clamp01(current[key] + rate * elapsed)
    return result


def apply_needs_delta(state: dict, deltas: dict) -> dict:
    """Apply bounded incremental deltas to a needs state, clamping the
    result. Does not persist — caller writes if desired."""
    current = clamp_state(state, NEEDS_FIELDS, DEFAULT_NEEDS)
    deltas = deltas if isinstance(deltas, dict) else {}
    result = dict(current)
    for key in NEEDS_FIELDS:
        if key in deltas:
            try:
                delta = float(deltas[key])
            except (TypeError, ValueError):
                delta = 0.0
            result[key] = clamp01(current[key] + delta)
    return result


def spice_level_from_needs(state: dict) -> int:
    """Deterministic spice_level (1-11) derived from needs, used when the
    active session mood came from LLM inference rather than a moods.json
    entry. Primarily arousal-driven, with a small happiness lift."""
    needs = clamp_state(state, NEEDS_FIELDS, DEFAULT_NEEDS)
    raw = 1.0 + needs["arousal"] * 9.0 + needs["happiness"] * 1.0
    level = int(round(raw))
    return max(1, min(11, level))


def touch_needs_heartbeat(last_touched_at: float | None) -> tuple[dict, float]:
    """Convenience wrapper: read state, decay it by elapsed time since
    `last_touched_at` (a unix timestamp, or None for "no decay"), write it
    back, and return (new_state, now). Caller-driven, mirrors
    mood_engine.touch_heartbeat's role for session mood."""
    with _needs_lock:
        now = time.time()
        state = read_needs_state()
        if last_touched_at:
            elapsed = max(0.0, now - float(last_touched_at))
            state = decay_needs(state, elapsed)
        write_needs_state(state)
        return state, now


def apply_and_persist_needs_delta(deltas: dict) -> dict:
    """Locked read -> apply_needs_delta -> write cycle, for direct callers
    that want to nudge live needs state from an event."""
    with _needs_lock:
        state = read_needs_state()
        state = apply_needs_delta(state, deltas)
        write_needs_state(state)
        return state


# Small per-tick nudge — meant to be called periodically (roughly every
# 30s) by the consuming app's monitor loop, not once per message. Sized so
# an hour of continuous silence moves boredom/loneliness by roughly +0.24,
# not an instant snap to extremes.
_QUIET_PRESENCE_DELTA = {"boredom": 0.002, "loneliness": 0.002, "social_need": 0.002}
_ACTIVE_PRESENCE_DELTA = {"loneliness": -0.001, "social_need": -0.001}

# A distinctly larger, one-off nudge for when Mai actually responds to
# someone — actually engaging matters more than chat merely existing
# nearby (spec 28: "not all events need equal weight").
_ENGAGEMENT_DELTA = {
    "social_need": -0.03,
    "loneliness": -0.02,
    "happiness": 0.02,
    "energy": -0.01,
}


def apply_presence_tick(is_quiet: bool) -> dict:
    """Nudge needs based on whether chat has been quiet or active since the
    last tick. Call this periodically from a monitor loop — see
    _QUIET_PRESENCE_DELTA/_ACTIVE_PRESENCE_DELTA for magnitudes."""
    return apply_and_persist_needs_delta(
        _QUIET_PRESENCE_DELTA if is_quiet else _ACTIVE_PRESENCE_DELTA
    )


def apply_engagement_delta() -> dict:
    """Nudge needs to reflect Mai actually engaging with someone (a
    completed response), distinct from and larger than passive presence."""
    return apply_and_persist_needs_delta(_ENGAGEMENT_DELTA)
