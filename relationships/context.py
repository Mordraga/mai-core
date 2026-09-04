"""Cognitive context builder — numeric state -> compact semantic-label text
block for MythoMax (spec section 26.1).

Python owns the numbers; MythoMax needs psychologically useful context, not
raw floats or a picked mood name. This module is the one place that
translates between the two.
"""
from __future__ import annotations

from relationships.models import NEEDS_FIELDS, RELATIONSHIP_FIELDS, PartcoreResult


def bucket_label(value: float) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if v < 0.2:
        return "very low"
    if v < 0.4:
        return "low"
    if v < 0.6:
        return "moderate"
    if v < 0.8:
        return "high"
    return "very high"


def _display_name(field: str) -> str:
    return field.replace("_", " ").capitalize()


def _clean_tag(tag: str) -> str:
    """Turn a bracket-style debug tag like "[crash:pet_peeve][intensity:snap]"
    into readable text: "crash pet peeve, intensity snap"."""
    if not tag:
        return ""
    parts = [seg for seg in tag.strip("[]").split("][") if seg]
    readable = [seg.replace(":", " ").replace("_", " ") for seg in parts]
    return ", ".join(readable)


def build_cognitive_context(
    relationship: dict,
    needs: dict,
    partcore_result: PartcoreResult | None,
    crypt: dict | None = None,
    current_crypt: dict | None = None,
    nickname: str | None = None,
    theory_of_mind: dict | None = None,
) -> str:
    sections: list[str] = []

    rel_lines = [
        f"{_display_name(field)}: {bucket_label(relationship.get(field, 0.0))}"
        for field in RELATIONSHIP_FIELDS
    ]
    if nickname:
        rel_lines.insert(0, f"Nickname you have for them: {nickname}")
    sections.append("[relationship]\n" + "\n".join(rel_lines))

    if theory_of_mind:
        tom_lines = [
            f"You think they currently want: {theory_of_mind.get('believed_wants', 'unclear')}",
            f"You think they currently believe about you: {theory_of_mind.get('believed_view_of_mai', 'unclear')}",
            f"Confidence in that read: {bucket_label(theory_of_mind.get('confidence', 0.0))}",
        ]
        sections.append("[theory_of_mind]\n" + "\n".join(tom_lines))

    needs_lines = [
        f"{_display_name(field)}: {bucket_label(needs.get(field, 0.0))}"
        for field in NEEDS_FIELDS
    ]
    sections.append("[needs]\n" + "\n".join(needs_lines))

    if crypt:
        crypt_lines = [
            f"{_display_name(field)}: {bucket_label(crypt.get(field, 0.0))}"
            for field in RELATIONSHIP_FIELDS
            if field in crypt
        ]
        if current_crypt:
            crypt_lines.append(f"How the room has felt lately - warmth: {bucket_label(current_crypt.get('current_warmth', 0.5))}")
            crypt_lines.append(f"How the room has felt lately - friction: {bucket_label(current_crypt.get('current_friction', 0.0))}")
        if crypt_lines:
            sections.append("[crypt]\n" + "\n".join(crypt_lines))

    if partcore_result is not None and partcore_result.active is not None:
        active = partcore_result.active
        secondary_names = ", ".join(v.part for v in partcore_result.secondary) or "none"
        reason = _clean_tag(active.tag) or "no reason recorded"
        partcore_lines = [
            f"Active: {active.part} ({active.vote})",
            f"Secondary: {secondary_names}",
            f"Reason: {reason}",
        ]
        sections.append("[partcore]\n" + "\n".join(partcore_lines))

    return "\n\n".join(sections)
