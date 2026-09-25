"""
The Crypt as a collective social entity — §17-24 of the spec.

Estimates which known users are representative of the current community
(`crypt_sway`) from the distribution of `stream_count`, then aggregates
their individual relationship primitives into a collective relationship.
"""
from __future__ import annotations

import math
import time
from typing import Any

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

from relationships.models import RELATIONSHIP_DEFAULTS, clamp_dict
from relationships.state import list_known_usernames, load_user_record

DEFAULT_SIGMA = 3.0


def _eligible_records(stream_start_time: float | None) -> list[dict[str, Any]]:
    """Users active within the current stream boundary, or all known users when
    no boundary is available (Discord / offline callers — §platform coverage)."""
    records: list[dict[str, Any]] = []
    for username in list_known_usernames():
        record = load_user_record(username)
        if stream_start_time is not None:
            last_stream_at = float(record.get("last_stream_at", 0.0) or 0.0)
            if last_stream_at < stream_start_time:
                continue
        records.append(record)
    return records


def _population_center(stream_counts: list[float]) -> float:
    if not stream_counts:
        return 0.0
    ordered = sorted(stream_counts)
    n = len(ordered)
    if n >= 20:
        trim = max(1, int(n * 0.10))
        trimmed = ordered[trim: n - trim] or ordered
    else:
        # <10 and 10-19: no percentile trimming (§19.2/§19.3)
        trimmed = ordered
    return sum(trimmed) / len(trimmed)


def _sigma(stream_counts: list[float], center: float) -> float:
    if len(stream_counts) < 2:
        return DEFAULT_SIGMA
    variance = sum((v - center) ** 2 for v in stream_counts) / len(stream_counts)
    sigma = math.sqrt(variance)
    return sigma if sigma > 1e-6 else 0.0  # 0 signals "degenerate" to caller


def compute_crypt_sway(records: list[dict[str, Any]], sigma_override: float | None = None) -> dict[str, float]:
    if not records:
        return {}
    stream_counts = [float(r.get("stream_count", 0) or 0) for r in records]
    center = _population_center(stream_counts)
    sigma = sigma_override if sigma_override else _sigma(stream_counts, center)

    sway: dict[str, float] = {}
    if sigma <= 0:
        # Degenerate/zero variance — equal sway for all (§19.5)
        for record in records:
            sway[record["username"]] = 1.0
        return sway

    for record, stream_count in zip(records, stream_counts):
        exponent = -0.5 * ((stream_count - center) / sigma) ** 2
        sway[record["username"]] = math.exp(exponent)
    return sway


def aggregate_crypt_relationship(
    stream_start_time: float | None = None,
    config: dict | None = None,
) -> dict[str, float]:
    config = config or {}
    sigma_override = config.get("crypt_sigma")

    records = _eligible_records(stream_start_time)
    if not records:
        return dict(RELATIONSHIP_DEFAULTS)

    sway = compute_crypt_sway(records, sigma_override=sigma_override)
    total_sway = sum(sway.values())
    if total_sway <= 0:
        return dict(RELATIONSHIP_DEFAULTS)

    aggregate: dict[str, float] = {key: 0.0 for key in RELATIONSHIP_DEFAULTS}
    for record in records:
        weight = sway.get(record["username"], 0.0)
        relationship = clamp_dict(record.get("relationship"), RELATIONSHIP_DEFAULTS)
        for key, value in relationship.items():
            aggregate[key] += value * weight

    return {key: round(value / total_sway, 4) for key, value in aggregate.items()}


def load_crypt_state() -> dict[str, Any]:
    return load_json(Paths.CRYPT_STATE, default={"current": dict(RELATIONSHIP_DEFAULTS), "updated_at": 0.0})


def refresh_crypt_state(stream_start_time: float | None = None, config: dict | None = None) -> dict[str, Any]:
    current = aggregate_crypt_relationship(stream_start_time=stream_start_time, config=config)
    payload = {"current": current, "updated_at": time.time()}
    atomic_write_json(Paths.CRYPT_STATE, payload)
    return payload
