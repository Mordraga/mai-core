"""Orchestrates the pre-response half of the cognition pipeline:

    load -> instincts -> crypt aggregate -> parts react -> partcore resolve
    -> build context

The Crypt's aggregate/current mood (relationships/crypt.py,
relationships/crypt_mood.py — spec Phase 5) is folded in alongside the
individual's own relationship/needs/observations so both reach the
cognitive context together.

Post-response mutation nudges the shared (global) needs vector and the
current-Crypt mood to reflect that Mai just engaged with someone, asks the
LLM what the exchange meant for this specific relationship
(relationships/mutation.py — spec Phase 4: deltas, a remembered
observation/pet-peeve/callback, a nickname, or a one-level theory-of-mind
read — spec Phase 7), and persists the result so a real conversation
actually produces a file on disk (loading is tolerant/in-memory-only —
nothing else in the pipeline ever writes one). Mutation inference is
best-effort: any failure there (network error, unparseable response,
nothing judged worth changing) just means the relationship persists
unchanged for this turn, same as the rest of this cognition layer never
being allowed to break chat.
"""
from __future__ import annotations

import time

from relationships import context as context_mod
from relationships import crypt as crypt_mod
from relationships import crypt_mood as crypt_mood_mod
from relationships import instincts as instincts_mod
from relationships import mutation as mutation_mod
from relationships import needs as needs_mod
from relationships import state as state_mod
from relationships.models import PartcoreResult
from relationships.parts import ALL_PARTS
from relationships.parts import partcore as partcore_mod

# A single joke shouldn't permanently rename someone (spec 32 gives no
# explicit threshold — this is a deliberate, documented choice): only
# accept an inferred nickname at moderate confidence or higher.
_NICKNAME_CONFIDENCE_THRESHOLD = 0.6


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
    first time this person is ever seen — see state.load_relationship.

    The Crypt's aggregate relationship (spec Phase 5) is recomputed from
    every known user's persisted record on every call — pure in-memory
    arithmetic over a population the spec itself expects to be small
    (~5 active regulars), so this adds no meaningful latency and needs no
    caching yet.
    """
    is_owner = bool(owner_username) and username.strip().lower() == owner_username.strip().lower()
    profile = state_mod.load_relationship(username, is_owner=is_owner)
    needs = needs_mod.read_needs_state()
    flags = instincts_mod.run_instincts(message, recent_messages)

    crypt_relationship = crypt_mod.aggregate_crypt_relationship()
    violation = crypt_mod.expectation_violation(profile.get("relationship", {}), crypt_relationship)
    current_crypt = crypt_mood_mod.touch_current_crypt_heartbeat()

    votes = []
    for part in ALL_PARTS:
        if part.name == "Curiosity":
            votes.append(part.react(profile, needs, flags, message, recent_messages, expectation_violation=violation))
        else:
            votes.append(part.react(profile, needs, flags, message, recent_messages))

    result = partcore_mod.resolve(votes)
    context_text = context_mod.build_cognitive_context(
        profile.get("relationship", {}),
        needs,
        result,
        crypt=crypt_relationship,
        current_crypt=current_crypt,
        nickname=profile.get("nickname"),
        theory_of_mind=profile.get("theory_of_mind"),
    )
    return context_text, result


def post_response_update(
    username: str,
    message: str,
    response: str,
    partcore_result: PartcoreResult,
    owner_username: str | None = None,
    recent_messages: list[str] | None = None,
) -> None:
    """Nudge global needs to reflect a completed exchange, ask the LLM what
    this exchange meant for the relationship with `username`, and persist
    the result.

    `owner_username` is re-checked here (same as build_cognitive_context)
    rather than trusting a value threaded through from the pre-response
    half, so that a first-ever contact with the owner gets persisted with
    the correct elevated baseline instead of silently locking in the
    stranger defaults.

    `partcore_result` isn't consumed by mutation inference yet (the LLM
    judges the exchange directly from message/response/relationship) but
    stays a parameter so a future pass — e.g. weighting mutation by which
    Part was active — doesn't need to change this call site again.
    """
    needs_mod.apply_engagement_delta()

    is_owner = bool(owner_username) and username.strip().lower() == owner_username.strip().lower()
    profile = state_mod.load_relationship(username, is_owner=is_owner)

    inferred = mutation_mod.infer_relationship_update(
        username=username,
        message=message,
        response=response,
        relationship=profile["relationship"],
        recent_messages=recent_messages,
    )
    if inferred:
        if inferred.get("deltas"):
            profile["relationship"] = mutation_mod.apply_bounded_deltas(
                profile["relationship"], inferred["deltas"]
            )

        observation = inferred.get("observation")
        if observation and observation.get("type") == "nickname":
            # A single current belief that overwrites, not a memory-log
            # entry — routed around merge_observation entirely (spec 32).
            if observation.get("confidence", 0.0) >= _NICKNAME_CONFIDENCE_THRESHOLD:
                nickname_text = str(observation.get("note") or "").strip()
                if nickname_text:
                    profile["nickname"] = nickname_text[:50]
        elif observation:
            profile["observations"] = mutation_mod.merge_observation(
                profile.get("observations", []), observation
            )

        theory_of_mind = inferred.get("theory_of_mind")
        if theory_of_mind:
            profile["theory_of_mind"] = {**theory_of_mind, "last_updated": time.time()}

    crypt_mood_mod.nudge_from_partcore(partcore_result)

    state_mod.save_relationship(username, profile)
