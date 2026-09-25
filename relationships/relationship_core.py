"""
Orchestrator: load -> observe -> evaluate -> resolve -> build context ->
post-update -> persist (spec §35 relationship_core.py).

Two entry points are the public interface consumed by chat_session.py (and,
after wiring, mai_monitor.py directly):

    build_cognitive_context(username, message, recent_messages, task, owner_username)
        -> (cognitive_context: str, partcore_result: PartcoreResult)

    post_response_update(username, message, response, task, partcore_result, owner_username)
        -> None

Both are best-effort: callers already wrap them in try/except, but internal
failures are also defensive (missing files, bad config) since this layer
must never be able to break existing chat.
"""
from __future__ import annotations

import time
from typing import Any

from utils.helpers import load_json
from utils.paths import Paths

from relationships import context as context_mod
from relationships import crypt as crypt_mod
from relationships import instincts
from relationships import needs as needs_mod
from relationships import state
from relationships.models import PartContext, PartcoreResult
from relationships.parts import partcore

DEFAULT_EVENT_WEIGHTS = {
    "follow": {"familiarity": 0.02},
    "sub": {"reciprocity": 0.05, "affection": 0.03},
    "resub": {"reciprocity": 0.04, "affection": 0.02},
    "subgift": {"reciprocity": 0.05, "affection": 0.04},
    "raid": {"affection": 0.05, "reciprocity": 0.03},
    "cheer": {"affection": 0.02, "reciprocity": 0.02},
}


def _load_config() -> dict:
    config = load_json(Paths.RELATIONSHIP_CONFIG, default={})
    return config if isinstance(config, dict) else {}


def build_cognitive_context(
    username: str,
    message: str,
    recent_messages: list[str] | None,
    task: str,
    owner_username: str | None = None,
    stream_start_time: float | None = None,
) -> tuple[str, PartcoreResult]:
    config = _load_config()
    record = state.load_user_record(username)
    relationship = record["relationship"]
    friendship = record["friendship"]
    observations = record["observations"]

    needs = needs_mod.load_needs()
    crypt_relationship = crypt_mod.aggregate_crypt_relationship(
        stream_start_time=stream_start_time, config=config
    )

    ctx = PartContext(
        username=username,
        message=message or "",
        task=task or "general",
        recent_messages=list(recent_messages or []),
        relationship=relationship,
        friendship=friendship,
        crypt_relationship=crypt_relationship,
        needs=needs,
        observations=observations,
        config=config,
    )

    partcore_result = partcore.resolve(ctx)
    selective_threshold = config.get("selective_threshold", context_mod.DEFAULT_SELECTIVE_THRESHOLD)
    context_text = context_mod.build_context_text(
        username, relationship, crypt_relationship, needs, partcore_result,
        selective_threshold=selective_threshold,
    )
    return context_text, partcore_result


def post_response_update(
    username: str,
    message: str,
    response: str,
    task: str,
    partcore_result: PartcoreResult | None,
    owner_username: str | None = None,
) -> None:
    config = _load_config()
    signals = instincts.extract_signals(message or "")

    relationship_deltas = instincts.relationship_deltas_for_signals(signals, config)
    needs_deltas = instincts.needs_deltas_for_signals(signals, config)

    hostility_triggered = "hostility" in signals
    if hostility_triggered:
        state.add_observation(username, {"type": "hostility_event", "timestamp": time.time()})

    record = state.load_user_record(username)
    pet_peeve = instincts.maybe_record_pet_peeve(username, record["observations"], hostility_triggered, time.time())
    if pet_peeve:
        state.add_observation(username, pet_peeve)

    if partcore_result is not None and partcore_result.hard_override and partcore_result.active is not None \
            and partcore_result.active.part == "Crash":
        crash_rel_deltas, crash_needs_deltas = instincts.crash_mutation(config)
        for key, value in crash_rel_deltas.items():
            relationship_deltas[key] = relationship_deltas.get(key, 0.0) + value
        for key, value in crash_needs_deltas.items():
            needs_deltas[key] = needs_deltas.get(key, 0.0) + value

    if relationship_deltas:
        state.update_relationship(username, relationship_deltas)
        state.sync_friendship(username)
    if needs_deltas:
        needs_mod.apply_needs_deltas(needs_deltas)


def observe_event(username: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Best-effort relationship nudge from a Twitch event (§27) — never touches
    the existing event-template/response logic."""
    config = _load_config()

    if event_type == "command_cooldown_blocked":
        state.add_observation(username, {"type": "hostility_event", "subtype": "command_spam", "timestamp": time.time()})
        record = state.load_user_record(username)
        pet_peeve = instincts.maybe_record_pet_peeve(username, record["observations"], True, time.time())
        if pet_peeve:
            state.add_observation(username, pet_peeve)
        return

    weights = config.get("event_weights", DEFAULT_EVENT_WEIGHTS)
    deltas = dict(weights.get(event_type, {}))
    if not deltas:
        return

    if event_type == "cheer" and payload:
        bits = float(payload.get("bits", 0) or 0)
        scale = max(0.1, min(1.0, bits / 1000.0))
        deltas = {key: value * scale for key, value in deltas.items()}

    state.update_relationship(username, deltas)
    state.sync_friendship(username)
