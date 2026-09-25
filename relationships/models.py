"""
Shared schemas, defaults, and clamping helpers for the relationship system.

Everything here is plain dicts/dataclasses, no I/O — matches the rest of
mai-core (mood_engine.py etc.) rather than introducing an ORM-style layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RELATIONSHIP_DEFAULTS: dict[str, float] = {
    "trust": 0.5,
    "familiarity": 0.0,
    "reciprocity": 0.5,
    "enjoyment": 0.5,
    "respect": 0.5,
    "reliability": 0.5,
    "interest": 0.5,
    "affection": 0.0,
    "hate": 0.0,
    "resentment": 0.0,
    "closeness_desire": 0.0,
}

FRIENDSHIP_DEFAULTS: dict[str, float] = {
    "utility": 0.5,
    "pleasure": 0.5,
    "virtue": 0.5,
}

RESTRICTIONS_DEFAULTS: dict[str, bool] = {
    "explicit_minor": False,
}

NEEDS_DEFAULTS: dict[str, float] = {
    "happiness": 0.5,
    "sadness": 0.0,
    "frustration": 0.0,
    "anger": 0.0,
    "energy": 0.7,
    "arousal": 0.0,
    "boredom": 0.2,
    "social_need": 0.5,
}

PART_NAMES: tuple[str, ...] = (
    "Familiar",
    "Bond",
    "Desire",
    "Tease",
    "Curiosity",
    "Crash",
)

CRASH_TIERS: tuple[str, ...] = ("neutral", "annoyed", "snap", "crash")


def clamp01(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(default)
    if v != v:  # NaN
        return float(default)
    return max(0.0, min(1.0, v))


def clamp_dict(raw: dict | None, defaults: dict[str, float]) -> dict[str, float]:
    raw = raw if isinstance(raw, dict) else {}
    return {key: clamp01(raw.get(key, default), default) for key, default in defaults.items()}


@dataclass
class PartResult:
    part: str
    activation: float = 0.0
    vote: str = "neutral"
    reason_codes: list[str] = field(default_factory=list)
    tier: str | None = None  # Crash-only: neutral/annoyed/snap/crash

    def to_dict(self) -> dict:
        return {
            "part": self.part,
            "activation": round(float(self.activation), 4),
            "vote": self.vote,
            "reason_codes": list(self.reason_codes),
            "tier": self.tier,
        }


@dataclass
class PartcoreResult:
    active: PartResult | None
    secondary: list[PartResult] = field(default_factory=list)
    all_results: list[PartResult] = field(default_factory=list)
    hard_override: bool = False

    def to_dict(self) -> dict:
        return {
            "active": self.active.to_dict() if self.active else None,
            "secondary": [p.to_dict() for p in self.secondary],
            "hard_override": self.hard_override,
        }


@dataclass
class PartContext:
    """Bundle handed to every Part.evaluate() — pure input, no I/O."""

    username: str
    message: str
    task: str
    recent_messages: list[str]
    relationship: dict[str, float]
    friendship: dict[str, float]
    crypt_relationship: dict[str, float]
    needs: dict[str, float]
    observations: list[dict]
    config: dict
