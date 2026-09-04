"""Per-user persistent relationship state.

One JSON file per known chatter under Paths.USER_HISTORY_DIR, following the
same tolerant load/normalize/save shape as utils/mood_engine.py: missing or
corrupt data always falls back to defaults rather than raising into the
chat pipeline.
"""
from __future__ import annotations

from pathlib import Path

from utils.helpers import atomic_write_json, load_json, resolve_existing_path, sanitize_path_component
from utils.paths import Paths

from relationships.models import (
    DEFAULT_OWNER_RELATIONSHIP,
    DEFAULT_RELATIONSHIP,
    RELATIONSHIP_FIELDS,
    clamp_state,
)


def _user_file_path(username: str) -> Path:
    # Paths.RELATIONSHIPS_DIR, not Paths.USER_HISTORY_DIR — the consuming
    # app already owns per-user files under USER_HISTORY_DIR for its own
    # message-log/stream-count tracking (a different schema). Sharing that
    # directory would silently clobber that data on the first save here.
    safe_name = sanitize_path_component(str(username or "unknown").strip().lower() or "unknown")
    return Path(Paths.RELATIONSHIPS_DIR) / f"{safe_name}.json"


def _default_record(username: str, is_owner: bool = False) -> dict:
    baseline = DEFAULT_OWNER_RELATIONSHIP if is_owner else DEFAULT_RELATIONSHIP
    return {
        "username": str(username or "").strip(),
        "stream_count": 0,
        "relationship": dict(baseline),
        "friendship": compute_friendship(baseline),
        "observations": [],
        # Phase 7 (spec 31-34) — nickname/theory_of_mind are single current
        # beliefs Mai holds *right now* about this person (mutation.py
        # inference overwrites, doesn't accumulate); observations already
        # covers the memory-log side (pet peeves, preferences, callbacks).
        "nickname": None,
        "theory_of_mind": None,
    }


def compute_friendship(relationship: dict) -> dict[str, float]:
    """Aristotle-style derived friendship dimensions (spec section 7).

    Interpretations of the relationship, not primitive truth — always
    recomputed from the primitives, never trusted as persisted source of
    truth.
    """
    r = clamp_state(relationship, RELATIONSHIP_FIELDS, DEFAULT_RELATIONSHIP)
    utility = (r["reciprocity"] + r["reliability"] + r["trust"]) / 3.0
    pleasure = (r["enjoyment"] + r["interest"] + r["affection"]) / 3.0
    virtue = (r["respect"] + r["trust"] + r["affection"] + r["reliability"]) / 4.0
    return {"utility": utility, "pleasure": pleasure, "virtue": virtue}


def load_relationship(username: str, is_owner: bool = False) -> dict:
    """Load the full persisted record for `username`, defaults on any
    missing/corrupt data. Friendship dimensions are always recomputed fresh
    from the loaded primitives, never read verbatim from disk.

    `is_owner` only affects the *first-ever* default record for someone —
    once a real file exists on disk (for anyone), it's used as-is regardless
    of who it's for.
    """
    path = _user_file_path(username)
    try:
        raw = load_json(path, default={})
    except (ValueError, OSError):
        # Corrupt file (invalid JSON) or unreadable — treat like "missing".
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    # NOTE: load_json's own default={} already satisfies isinstance(raw, dict)
    # for a missing file, so "missing" and "corrupt" both funnel into an
    # empty `raw` here — the owner/stranger baseline is applied via the
    # clamp_state fallback below, not a separate early return, so it
    # actually takes effect for the common "never seen before" case.
    baseline = DEFAULT_OWNER_RELATIONSHIP if is_owner else DEFAULT_RELATIONSHIP
    relationship = clamp_state(raw.get("relationship", {}), RELATIONSHIP_FIELDS, baseline)
    try:
        stream_count = max(0, int(raw.get("stream_count", 0)))
    except (TypeError, ValueError):
        stream_count = 0

    observations = raw.get("observations", [])
    if not isinstance(observations, list):
        observations = []

    nickname = raw.get("nickname")
    if not isinstance(nickname, str) or not nickname.strip():
        nickname = None

    theory_of_mind = raw.get("theory_of_mind")
    if not isinstance(theory_of_mind, dict):
        theory_of_mind = None

    return {
        "username": str(raw.get("username") or username or "").strip(),
        "stream_count": stream_count,
        "relationship": relationship,
        "friendship": compute_friendship(relationship),
        "observations": observations,
        "nickname": nickname,
        "theory_of_mind": theory_of_mind,
    }


def save_relationship(username: str, record: dict) -> None:
    """Persist `record` (as returned/shaped by load_relationship) for
    `username`. Friendship is recomputed before writing so a stale/edited
    friendship block can never drift from its source primitives."""
    if not isinstance(record, dict):
        record = _default_record(username)

    relationship = clamp_state(record.get("relationship", {}), RELATIONSHIP_FIELDS, DEFAULT_RELATIONSHIP)
    try:
        stream_count = max(0, int(record.get("stream_count", 0)))
    except (TypeError, ValueError):
        stream_count = 0
    observations = record.get("observations", [])
    if not isinstance(observations, list):
        observations = []

    nickname = record.get("nickname")
    if not isinstance(nickname, str) or not nickname.strip():
        nickname = None

    theory_of_mind = record.get("theory_of_mind")
    if not isinstance(theory_of_mind, dict):
        theory_of_mind = None

    payload = {
        "username": str(record.get("username") or username or "").strip(),
        "stream_count": stream_count,
        "relationship": relationship,
        "friendship": compute_friendship(relationship),
        "observations": observations,
        "nickname": nickname,
        "theory_of_mind": theory_of_mind,
    }
    atomic_write_json(_user_file_path(username), payload)


def bump_stream_count(username: str) -> dict:
    """Increment stream_count for `username` and persist. Caller decides
    when this represents "first message this stream" — this function just
    does the increment + save."""
    record = load_relationship(username)
    record["stream_count"] = int(record.get("stream_count", 0)) + 1
    save_relationship(username, record)
    return record


def user_file_exists(username: str) -> bool:
    return resolve_existing_path(_user_file_path(username)).exists()


def list_known_usernames() -> list[str]:
    """Every username with a persisted relationship record — the "known
    chatters" population relationships/crypt.py draws from (spec 18-20).
    Returns [] rather than raising when the directory doesn't exist yet
    (nobody has ever been persisted)."""
    directory = resolve_existing_path(Paths.RELATIONSHIPS_DIR)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))
