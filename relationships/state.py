"""
Per-user relationship state — load/save/migrate.

Extends the existing per-user history file (jsons/logs/history/users/<name>.json,
already holding messages/stream_count/etc.) with relationship/friendship/
observations/restrictions keys rather than introducing a second file per user.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.helpers import atomic_write_json, load_json, sanitize_path_component
from utils.paths import Paths

from relationships.models import (
    FRIENDSHIP_DEFAULTS,
    RELATIONSHIP_DEFAULTS,
    RESTRICTIONS_DEFAULTS,
    clamp_dict,
)

MAX_OBSERVATIONS = 200


def _user_file(username: str) -> str:
    safe = sanitize_path_component(username)
    return str(Path(Paths.USER_HISTORY_DIR) / f"{safe}.json")


def load_user_record(username: str) -> dict[str, Any]:
    """Load the full per-user record, migrating in relationship defaults if absent."""
    path = _user_file(username)
    record = load_json(path, default={})
    if not isinstance(record, dict):
        record = {}
    return migrate_user_record(record, username)


def migrate_user_record(record: dict, username: str) -> dict[str, Any]:
    record = dict(record) if isinstance(record, dict) else {}
    record.setdefault("username", username)
    record["relationship"] = clamp_dict(record.get("relationship"), RELATIONSHIP_DEFAULTS)
    record["friendship"] = clamp_dict(record.get("friendship"), FRIENDSHIP_DEFAULTS)

    observations = record.get("observations")
    record["observations"] = observations if isinstance(observations, list) else []

    restrictions = record.get("restrictions")
    restrictions = restrictions if isinstance(restrictions, dict) else {}
    record["restrictions"] = {
        key: bool(restrictions.get(key, default))
        for key, default in RESTRICTIONS_DEFAULTS.items()
    }

    record.setdefault("stream_count", 0)
    return record


def save_user_record(username: str, record: dict[str, Any]) -> None:
    path = _user_file(username)
    atomic_write_json(path, record)


def get_relationship(username: str) -> dict[str, float]:
    return load_user_record(username)["relationship"]


def get_friendship(username: str) -> dict[str, float]:
    return load_user_record(username)["friendship"]


def update_relationship(username: str, deltas: dict[str, float]) -> dict[str, float]:
    """Apply incremental deltas (clamped to [0,1] after application) and persist."""
    record = load_user_record(username)
    relationship = dict(record["relationship"])
    for key, delta in deltas.items():
        if key not in RELATIONSHIP_DEFAULTS:
            continue
        relationship[key] = max(0.0, min(1.0, relationship.get(key, RELATIONSHIP_DEFAULTS[key]) + delta))
    record["relationship"] = relationship
    save_user_record(username, record)
    return relationship


def add_observation(username: str, observation: dict) -> None:
    record = load_user_record(username)
    observations = record["observations"]
    observations.append(observation)
    record["observations"] = observations[-MAX_OBSERVATIONS:]
    save_user_record(username, record)


def derive_friendship(relationship: dict[str, float]) -> dict[str, float]:
    """Aristotle-style derived dims (§7) — interpretation only, never overwrites primitives."""
    utility = (relationship["reciprocity"] + relationship["reliability"] + relationship["trust"]) / 3.0
    pleasure = (relationship["enjoyment"] + relationship["interest"] + relationship["affection"]) / 3.0
    virtue = (
        relationship["respect"] + relationship["trust"] + relationship["affection"] + relationship["reliability"]
    ) / 4.0
    return {
        "utility": round(utility, 4),
        "pleasure": round(pleasure, 4),
        "virtue": round(virtue, 4),
    }


def sync_friendship(username: str) -> dict[str, float]:
    record = load_user_record(username)
    friendship = derive_friendship(record["relationship"])
    record["friendship"] = friendship
    save_user_record(username, record)
    return friendship


def list_known_usernames() -> list[str]:
    from utils.helpers import resolve_existing_path

    directory = resolve_existing_path(Paths.USER_HISTORY_DIR)
    if not directory.exists():
        return []
    return [p.stem for p in directory.glob("*.json")]
