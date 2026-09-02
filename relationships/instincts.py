"""Lightweight, read-only message-pattern flags fed to each Part's react().

Mirrors the role of selyros-beta's instinct_core.run_instincts(): a cheap
preprocessing pass Parts can key off of. Unlike that project's instincts,
these do not mutate any state directly — relationship/needs mutation from
what happened is spec Phase 4 (post-response update), not built here.
"""
from __future__ import annotations

from relationships import preferences

_GREETING_WORDS = ("hi", "hello", "hey", "yo", "sup", "morning", "evening")


def run_instincts(message: str, recent_messages: list[str] | None = None) -> list[str]:
    flags: list[str] = []
    text = str(message or "").strip()
    lowered = text.lower()

    if not text:
        flags.append("silence")
        return flags

    first_word = lowered.split()[0].strip(".,!?") if lowered.split() else ""
    if first_word in _GREETING_WORDS:
        flags.append("greeting")

    if text.startswith("!"):
        flags.append("command")
        recent = recent_messages or []
        recent_commands = sum(1 for m in recent[-5:] if str(m).strip().startswith("!"))
        if recent_commands >= 3:
            flags.append("command_spam")

    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 5 and text.upper() == text and any(c.isalpha() for c in text):
        flags.append("shouting")

    if text.endswith("?"):
        flags.append("question")

    recent = recent_messages or []
    if recent and str(recent[-1]).strip().lower() == lowered:
        flags.append("repeated_message")

    peeves, likes = preferences.scan(text)
    flags += [f"pet_peeve:{name}" for name in peeves]
    flags += [f"liked:{name}" for name in likes]

    return flags
