"""
Numeric state -> compact, semantic cognitive_context text block (spec §26.1).

Python owns the numbers; MythoMax needs psychologically useful, selective
context rather than a dump of every primitive every turn.
"""
from __future__ import annotations

from relationships.models import (
    FRIENDSHIP_DEFAULTS,
    NEEDS_DEFAULTS,
    PartcoreResult,
    RELATIONSHIP_DEFAULTS,
)

DEFAULT_SELECTIVE_THRESHOLD = 0.15

_LABEL_FIELDS = {
    "trust": "Trust", "familiarity": "Familiarity", "reciprocity": "Reciprocity",
    "enjoyment": "Enjoyment", "respect": "Respect", "reliability": "Reliability",
    "interest": "Interest", "affection": "Affection", "hate": "Hate",
    "resentment": "Resentment", "closeness_desire": "Closeness desire",
}

_NEEDS_LABELS = {
    "happiness": "Happiness", "sadness": "Sadness", "frustration": "Frustration",
    "anger": "Anger", "energy": "Energy", "arousal": "Arousal",
    "boredom": "Boredom", "social_need": "Social need",
}


def band(value: float) -> str:
    if value < 0.2:
        return "very low"
    if value < 0.4:
        return "low"
    if value < 0.6:
        return "moderate"
    if value < 0.8:
        return "high"
    return "very high"


def _relevant_keys(relationship: dict, reason_codes: list[str], threshold: float) -> list[str]:
    reason_blob = " ".join(reason_codes).lower()
    relevant = []
    for key, default in RELATIONSHIP_DEFAULTS.items():
        value = relationship.get(key, default)
        if abs(value - default) >= threshold or key.replace("_", " ") in reason_blob or key in reason_blob:
            relevant.append(key)
    return relevant


def _format_relationship_block(username: str, relationship: dict, reason_codes: list[str], threshold: float) -> str:
    keys = _relevant_keys(relationship, reason_codes, threshold)
    if not keys:
        keys = ["familiarity", "affection", "trust"]
    lines = [f"Target: {username}"]
    for key in keys:
        lines.append(f"{_LABEL_FIELDS[key]}: {band(relationship.get(key, RELATIONSHIP_DEFAULTS[key]))}")
    return "[relationship]\n" + "\n".join(lines)


def _format_crypt_block(crypt_relationship: dict, threshold: float) -> str:
    keys = _relevant_keys(crypt_relationship, [], threshold)
    if not keys:
        keys = ["affection", "enjoyment"]
    lines = [f"{_LABEL_FIELDS[key]}: {band(crypt_relationship.get(key, RELATIONSHIP_DEFAULTS[key]))}" for key in keys]
    return "[crypt]\n" + "\n".join(lines)


def _format_needs_block(needs: dict) -> str:
    lines = []
    for key, default in NEEDS_DEFAULTS.items():
        value = needs.get(key, default)
        if abs(value - default) >= DEFAULT_SELECTIVE_THRESHOLD or key in ("energy", "social_need"):
            lines.append(f"{_NEEDS_LABELS[key]}: {band(value)}")
    if not lines:
        lines = ["Energy: " + band(needs.get("energy", NEEDS_DEFAULTS["energy"]))]
    return "[needs]\n" + "\n".join(lines)


def _format_partcore_block(partcore: PartcoreResult) -> str:
    if partcore.active is None:
        return "[partcore]\nActive: none (baseline personality)"
    lines = [f"Active: {partcore.active.part}"]
    intensity = partcore.active.tier if partcore.active.tier else band(partcore.active.activation)
    lines.append(f"Intensity: {intensity}")
    if partcore.secondary:
        lines.append("Secondary: " + ", ".join(p.part for p in partcore.secondary))
    all_reasons = list(partcore.active.reason_codes)
    for p in partcore.secondary:
        all_reasons.extend(p.reason_codes)
    if all_reasons:
        lines.append("Reason: " + ", ".join(dict.fromkeys(all_reasons)))
    return "[partcore]\n" + "\n".join(lines)


def build_context_text(
    username: str,
    relationship: dict,
    crypt_relationship: dict,
    needs: dict,
    partcore: PartcoreResult,
    selective_threshold: float = DEFAULT_SELECTIVE_THRESHOLD,
) -> str:
    reason_codes = list(partcore.active.reason_codes) if partcore.active else []
    for p in partcore.secondary:
        reason_codes.extend(p.reason_codes)

    blocks = [
        _format_relationship_block(username, relationship, reason_codes, selective_threshold),
        _format_crypt_block(crypt_relationship, selective_threshold),
        _format_needs_block(needs),
        _format_partcore_block(partcore),
    ]
    return "\n\n".join(blocks)
