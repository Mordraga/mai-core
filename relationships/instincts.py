"""
Pre/post-response observation extraction — spec §28-30.

Deliberately simple keyword-based signal detection (no NLP model) that feeds
asymmetric, weighted relationship/needs mutation. Weights live in
relationship_config.json so they can be tuned without code changes.
"""
from __future__ import annotations

from typing import Any

POSITIVE_KEYWORDS = (
    "love you", "love mai", "you're the best", "youre the best", "appreciate you",
    "thank you mai", "thanks mai", "miss you", "good bot", "best girl",
)
HOSTILITY_KEYWORDS = (
    "shut up", "you're dumb", "youre dumb", "you suck", "hate you", "stupid bot",
    "worthless", "useless bot", "screw you",
)
REPAIR_KEYWORDS = (
    "sorry", "my bad", "didn't mean", "didnt mean", "apologize", "no offense", "my apologies",
)

DEFAULT_MUTATION_WEIGHTS = {
    "positive": {"affection": 0.03, "enjoyment": 0.02, "reciprocity": 0.02},
    "hostility": {"trust": -0.05, "resentment": 0.04, "affection": -0.02},
    "repair": {"resentment": -0.05, "trust": 0.02},
    "reciprocity": {"reciprocity": 0.02, "familiarity": 0.01},
    "crash_triggered": {"resentment": 0.03},
    "familiarity_tick": {"familiarity": 0.004},
}

DEFAULT_NEEDS_WEIGHTS = {
    "positive": {"happiness": 0.02, "social_need": -0.02},
    "hostility": {"frustration": 0.05, "anger": 0.03, "happiness": -0.02},
    "repair": {"frustration": -0.03},
    "crash_triggered": {"frustration": 0.02},
}

PET_PEEVE_REPEAT_THRESHOLD = 3


def extract_signals(message: str) -> set[str]:
    lowered = (message or "").lower()
    signals: set[str] = set()
    if any(phrase in lowered for phrase in POSITIVE_KEYWORDS):
        signals.add("positive")
    if any(phrase in lowered for phrase in HOSTILITY_KEYWORDS):
        signals.add("hostility")
    if any(phrase in lowered for phrase in REPAIR_KEYWORDS):
        signals.add("repair")
    if len(lowered.strip()) > 0:
        signals.add("reciprocity")
    return signals


def relationship_deltas_for_signals(signals: set[str], config: dict) -> dict[str, float]:
    weights = config.get("mutation_weights", DEFAULT_MUTATION_WEIGHTS)
    deltas: dict[str, float] = {}
    for signal in signals:
        for key, value in weights.get(signal, {}).items():
            deltas[key] = deltas.get(key, 0.0) + value
    return deltas


def needs_deltas_for_signals(signals: set[str], config: dict) -> dict[str, float]:
    weights = config.get("needs_weights", DEFAULT_NEEDS_WEIGHTS)
    deltas: dict[str, float] = {}
    for signal in signals:
        for key, value in weights.get(signal, {}).items():
            deltas[key] = deltas.get(key, 0.0) + value
    return deltas


def crash_mutation(config: dict) -> tuple[dict[str, float], dict[str, float]]:
    """Extra deltas applied when Crash actually took the wheel this turn."""
    relationship_weights = config.get("mutation_weights", DEFAULT_MUTATION_WEIGHTS).get("crash_triggered", {})
    needs_weights = config.get("needs_weights", DEFAULT_NEEDS_WEIGHTS).get("crash_triggered", {})
    return dict(relationship_weights), dict(needs_weights)


def maybe_record_pet_peeve(username: str, observations: list[dict], hostility_triggered: bool, now: float) -> dict | None:
    """Returns a new pet_peeve observation dict if repeated hostility crosses the
    threshold, else None. Caller is responsible for persisting it (state.add_observation)."""
    if not hostility_triggered:
        return None
    recent_hostility = sum(1 for o in observations if o.get("type") == "hostility_event")
    if recent_hostility + 1 < PET_PEEVE_REPEAT_THRESHOLD:
        return None
    already_flagged = any(o.get("type") == "pet_peeve" for o in observations)
    if already_flagged:
        return None
    return {
        "type": "pet_peeve",
        "subject": username,
        "confidence": 0.7,
        "salience": 0.6,
        "last_reinforced": now,
    }
