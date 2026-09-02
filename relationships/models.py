"""Data shapes for the relationship/needs/Parts cognition layer.

Kept deliberately small. Parts are scripts (see relationships/parts/*), not
a generic scored data system, so the only shared records are the state
containers (RelationshipState/NeedsState) and the vote/result shapes each
Part hands back to PartCore.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# =============================
# Relationship primitives (spec section 5.1)
# =============================

RELATIONSHIP_FIELDS: tuple[str, ...] = (
    "trust",
    "familiarity",
    "reciprocity",
    "enjoyment",
    "respect",
    "reliability",
    "interest",
    "affection",
    "hate",
    "resentment",
    "closeness_desire",
)

# Neutral defaults per spec 5.1's example. Exact numbers are tunable.
DEFAULT_RELATIONSHIP: dict[str, float] = {
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

# Baseline for the owner specifically (personality.yaml's own framing: "She
# built you and you chose to stay" / "devoted without being submissive").
# The owner isn't a stranger on day one the way every other chatter is —
# this is only the starting point for a *new* relationship record though;
# once one exists on disk, it's used as-is regardless of who it's for.
# resentment stays slightly non-zero on purpose: devoted isn't the same as
# submissive, she still has agency and opinions.
DEFAULT_OWNER_RELATIONSHIP: dict[str, float] = {
    "trust": 0.85,
    "familiarity": 0.95,
    "reciprocity": 0.8,
    "enjoyment": 0.85,
    "respect": 0.85,
    "reliability": 0.85,
    "interest": 0.7,
    "affection": 0.85,
    "hate": 0.0,
    "resentment": 0.05,
    "closeness_desire": 0.8,
}

# =============================
# Needs primitives (spec section 8, + loneliness added per project direction)
# =============================

NEEDS_FIELDS: tuple[str, ...] = (
    "happiness",
    "sadness",
    "frustration",
    "anger",
    "energy",
    "arousal",
    "boredom",
    "social_need",
    "loneliness",
)

DEFAULT_NEEDS: dict[str, float] = {
    "happiness": 0.5,
    "sadness": 0.0,
    "frustration": 0.0,
    "anger": 0.0,
    "energy": 0.7,
    "arousal": 0.0,
    "boredom": 0.2,
    "social_need": 0.5,
    "loneliness": 0.0,
}


def clamp01(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def clamp_state(raw: dict, fields: tuple[str, ...], defaults: dict[str, float]) -> dict[str, float]:
    """Return a dict containing exactly `fields`, each clamped to [0, 1],
    falling back to `defaults` for missing/invalid entries."""
    raw = raw if isinstance(raw, dict) else {}
    return {key: clamp01(raw.get(key, defaults.get(key, 0.0))) for key in fields}


# =============================
# Part votes / arbitration result
# =============================

@dataclass
class PartVote:
    """One Part's reaction to the current interaction.

    `vote` is categorical (e.g. "engage", "neutral", "crash") — Parts do not
    return a numeric activation score. `tag` is a short bracket-style debug
    string explaining why, e.g. "[crash:pet_peeve][intensity:snap]".
    """

    part: str
    vote: str
    tag: str = ""


@dataclass
class PartcoreResult:
    """Result of PartCore arbitration over all Part votes."""

    active: PartVote | None
    secondary: list[PartVote] = field(default_factory=list)
