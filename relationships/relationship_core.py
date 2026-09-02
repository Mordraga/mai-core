"""Orchestrates the pre-response half of the cognition pipeline:

    load -> instincts -> parts react -> partcore resolve -> build context

Post-response mutation nudges the shared (global) needs vector to reflect
that Mai just engaged with someone, and persists that person's relationship
record so a real conversation actually produces a file on disk (loading is
tolerant/in-memory-only — nothing else in the pipeline ever writes one).
Per-user relationship-primitive mutation (trust/affection/resentment
changing from interactions, pet peeves, repair) is the larger remaining
piece of spec Phase 4 and is still not built — that needs observation
extraction and confidence-weighted beliefs, a separate design pass. This
only ensures the record *exists*; it doesn't change any values in it yet.
"""
from __future__ import annotations

from relationships import context as context_mod
from relationships import instincts as instincts_mod
from relationships import needs as needs_mod
from relationships import state as state_mod
from relationships.models import PartcoreResult
from relationships.parts import ALL_PARTS
from relationships.parts import partcore as partcore_mod


def build_cognitive_context(
    username: str,
    message: str,
    recent_messages: list[str] | None = None,
    task: str | None = None,
    owner_username: str | None = None,
) -> tuple[str, PartcoreResult]:
    """Return (cognitive_context_text, partcore_result) for the given
    interaction. Never raises — callers (chat_session.py) still wrap this
    defensively, but every internal load is already tolerant of missing/
    corrupt state on its own.

    `owner_username`, when supplied and matching `username` (case-
    insensitive), only affects the *default* relationship record used the
    first time this person is ever seen — see state.load_relationship."""
    is_owner = bool(owner_username) and username.strip().lower() == owner_username.strip().lower()
    profile = state_mod.load_relationship(username, is_owner=is_owner)
    needs = needs_mod.read_needs_state()
    flags = instincts_mod.run_instincts(message, recent_messages)

    votes = [
        part.react(profile, needs, flags, message, recent_messages)
        for part in ALL_PARTS
    ]
    result = partcore_mod.resolve(votes)
    context_text = context_mod.build_cognitive_context(
        profile.get("relationship", {}), needs, result
    )
    return context_text, result


def post_response_update(
    username: str,
    message: str,
    response: str,
    partcore_result: PartcoreResult,
    owner_username: str | None = None,
) -> None:
    """Nudge global needs to reflect a completed exchange, and persist this
    person's relationship record so it actually exists on disk after a real
    conversation — not just when a debug script calls save_relationship
    directly.

    `owner_username` is re-checked here (same as build_cognitive_context)
    rather than trusting a value threaded through from the pre-response
    half, so that a first-ever contact with the owner gets persisted with
    the correct elevated baseline instead of silently locking in the
    stranger defaults.

    Per-user relationship-primitive mutation (trust/affection/resentment,
    observation extraction) is not built yet — spec Phase 4's larger piece,
    deferred. `message`/`response`/`partcore_result` are already accepted
    so that future mutation can slot in here without changing the call site
    in chat_session.py or mai_monitor.py again.
    """
    needs_mod.apply_engagement_delta()

    is_owner = bool(owner_username) and username.strip().lower() == owner_username.strip().lower()
    profile = state_mod.load_relationship(username, is_owner=is_owner)
    state_mod.save_relationship(username, profile)
