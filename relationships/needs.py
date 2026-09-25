"""
Global (not per-user) transient Needs state — §8 of the spec.

Needs decay toward neutral baselines over time and are nudged by events.
They are read by Partcore to shift Part activation thresholds (§16.2).
"""
from __future__ import annotations

import time
from typing import Any

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

from relationships.models import NEEDS_DEFAULTS, clamp_dict

# Per-need (value_per_second, target) — decay pulls each need back toward its
# neutral baseline when nothing is actively pushing it elsewhere.
DECAY_TARGETS: dict[str, float] = {
    "happiness": 0.5,
    "sadness": 0.0,
    "frustration": 0.0,
    "anger": 0.0,
    "energy": 0.7,
    "arousal": 0.0,
    "boredom": 0.2,
    "social_need": 0.5,
}

DECAY_RATE_PER_HOUR = 0.15


def _default_state() -> dict[str, Any]:
    return {"needs": dict(NEEDS_DEFAULTS), "updated_at": time.time()}


def load_needs() -> dict[str, float]:
    payload = load_json(Paths.NEEDS_STATE, default=_default_state())
    if not isinstance(payload, dict):
        payload = _default_state()
    needs = clamp_dict(payload.get("needs"), NEEDS_DEFAULTS)
    updated_at = float(payload.get("updated_at", time.time()) or time.time())
    return _apply_decay(needs, updated_at)


def _apply_decay(needs: dict[str, float], updated_at: float) -> dict[str, float]:
    elapsed_hours = max(0.0, (time.time() - updated_at) / 3600.0)
    if elapsed_hours <= 0:
        return needs
    factor = min(1.0, DECAY_RATE_PER_HOUR * elapsed_hours)
    decayed = {}
    for key, value in needs.items():
        target = DECAY_TARGETS.get(key, 0.5)
        decayed[key] = value + (target - value) * factor
    return clamp_dict(decayed, NEEDS_DEFAULTS)


def save_needs(needs: dict[str, float]) -> None:
    payload = {"needs": clamp_dict(needs, NEEDS_DEFAULTS), "updated_at": time.time()}
    atomic_write_json(Paths.NEEDS_STATE, payload)


def apply_needs_deltas(deltas: dict[str, float]) -> dict[str, float]:
    needs = load_needs()
    for key, delta in deltas.items():
        if key not in NEEDS_DEFAULTS:
            continue
        needs[key] = max(0.0, min(1.0, needs.get(key, NEEDS_DEFAULTS[key]) + delta))
    save_needs(needs)
    return needs
