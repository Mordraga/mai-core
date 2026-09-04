"""Current Crypt mood — spec section 21 (explicitly optional, built as part
of Phase 7).

relationships/crypt.py::aggregate_crypt_relationship() is the *historical*
Crypt: slow-moving, built from persisted individual relationships that only
change by small bounded amounts per exchange (relationships/mutation.py).
This module is the *current* Crypt: a separate, fast-moving, decaying-to-
neutral pair of scalars — "what has the room felt like recently" — nudged
by which Part actually won each response. Spec 21's own framing:

    historical: "I love these people."
    current: "These people are fucking unbearable tonight."

Deliberately not a full 11-primitive vector like the historical aggregate —
a lightweight temperature reading is enough to carry that distinction into
the cognitive context. Mirrors relationships/needs.py's persisted-scalar-
with-decay pattern: global (not per-user), caller-driven heartbeat, no
background loop of its own, decay is a pure function of elapsed time.
"""
from __future__ import annotations

import math
import threading
import time

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

from relationships.models import PartcoreResult, clamp01

_crypt_mood_lock = threading.Lock()

CURRENT_CRYPT_FIELDS: tuple[str, ...] = ("current_warmth", "current_friction")
DEFAULT_CURRENT_CRYPT: dict[str, float] = {"current_warmth": 0.5, "current_friction": 0.0}

# How fast each field relaxes back toward its neutral default absent
# reinforcement — exponential decay toward the setpoint (not linear), so it
# approaches neutral smoothly without needing overshoot clamping. "Current"
# means recent, not permanent: a bad night shouldn't still read as tense a
# week later with nothing keeping it there.
_DECAY_RATE_PER_SECOND: dict[str, float] = {
    "current_warmth": 0.00005,
    "current_friction": 0.00008,
}

# Nudges applied post-response based on which Part actually won — spec
# 21's framing is about the room's recent emotional temperature, not a
# specific relationship dimension, so this reads PartcoreResult rather
# than relationship deltas.
_WARM_VOTE_PARTS = {"Bond", "Desire", "Tease"}
_WARMTH_STEP = 0.02
_FRICTION_STEP_BY_VOTE = {"annoyed": 0.03, "snap": 0.08, "crash": 0.15}


def _clamp(state: dict) -> dict:
    return {field: clamp01(state.get(field, DEFAULT_CURRENT_CRYPT[field])) for field in CURRENT_CRYPT_FIELDS}


def read_current_crypt_state() -> dict:
    try:
        raw = load_json(Paths.CURRENT_CRYPT_STATE, default={})
    except (ValueError, OSError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    state = _clamp(raw)
    state["last_touched_at"] = raw.get("last_touched_at")
    return state


def write_current_crypt_state(state: dict) -> None:
    payload = _clamp(state)
    payload["last_touched_at"] = state.get("last_touched_at")
    atomic_write_json(Paths.CURRENT_CRYPT_STATE, payload)


def decay_current_crypt(state: dict, elapsed_seconds: float) -> dict:
    """Return a new state relaxed `elapsed_seconds` toward neutral. Pure
    function — does not read or write the persisted state file."""
    current = _clamp(state)
    try:
        elapsed = max(0.0, float(elapsed_seconds))
    except (TypeError, ValueError):
        elapsed = 0.0

    result = {}
    for field in CURRENT_CRYPT_FIELDS:
        neutral = DEFAULT_CURRENT_CRYPT[field]
        rate = _DECAY_RATE_PER_SECOND.get(field, 0.0)
        decay_factor = math.exp(-rate * elapsed)
        result[field] = clamp01(neutral + (current[field] - neutral) * decay_factor)
    return result


def touch_current_crypt_heartbeat() -> dict:
    """Read state, decay it by elapsed time since it was last touched,
    write it back, and return it. Caller-driven, mirrors
    needs.touch_needs_heartbeat — called once per pre-response cognitive-
    context build."""
    with _crypt_mood_lock:
        now = time.time()
        state = read_current_crypt_state()
        last_touched_at = state.get("last_touched_at")
        if last_touched_at:
            elapsed = max(0.0, now - float(last_touched_at))
            state = decay_current_crypt(state, elapsed)
        state["last_touched_at"] = now
        write_current_crypt_state(state)
        return state


def apply_and_persist_current_crypt_delta(deltas: dict) -> dict:
    """Locked read -> apply -> write cycle for an event-driven nudge, no
    decay applied here — mirrors needs.apply_and_persist_needs_delta."""
    with _crypt_mood_lock:
        state = read_current_crypt_state()
        result = dict(state)
        for field, delta in deltas.items():
            if field in CURRENT_CRYPT_FIELDS:
                result[field] = clamp01(float(state.get(field, DEFAULT_CURRENT_CRYPT[field])) + float(delta))
        result["last_touched_at"] = time.time()
        write_current_crypt_state(result)
        return result


def nudge_from_partcore(partcore_result: PartcoreResult | None) -> dict:
    """Nudge current_warmth/current_friction based on which Part actually
    won this response. No-signal outcomes (no active Part, Familiar or
    Curiosity active, or Crash sitting at "neutral") leave the state
    untouched rather than writing a no-op delta."""
    if partcore_result is None or partcore_result.active is None:
        return read_current_crypt_state()

    active = partcore_result.active
    deltas = {"current_warmth": 0.0, "current_friction": 0.0}

    if active.part == "Crash":
        deltas["current_friction"] = _FRICTION_STEP_BY_VOTE.get(active.vote, 0.0)
    elif active.part in _WARM_VOTE_PARTS and active.vote == "engage":
        deltas["current_warmth"] = _WARMTH_STEP

    if deltas["current_warmth"] == 0.0 and deltas["current_friction"] == 0.0:
        return read_current_crypt_state()

    return apply_and_persist_current_crypt_delta(deltas)
