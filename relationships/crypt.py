"""The Crypt as a collective social entity (spec Phase 5, sections 17-24).

Mai's relationship with individual chatters (relationships/state.py) is one
axis. This module derives a second, emergent one: what The Crypt
collectively means to Mai, built as a crypt_sway-weighted average of
eligible individual relationships. crypt_sway itself is pure population
statistics (spec 19) — representativeness, not popularity — so there's no
LLM involvement here at all; the qualitative *meaning* of the aggregate
numbers is left to the same place that already interprets individual
relationship numbers: the response-generating LLM call, once
relationships/context.py hands it a populated [crypt] section. That keeps
this module fast enough to run on every message with no added latency.

expectation_violation() is the one piece Phase 5 adds *as* a signal (spec
22-23): a cheap, deterministic proxy for "does this person diverge from
what The Crypt collectively is to Mai" — relationship-vector distance from
the aggregate, dampened by familiarity so a well-established regular's
ordinary individuality doesn't keep re-triggering it (spec 22: "As
familiarity with an individual increases, individual evidence should
rapidly dominate").
"""
from __future__ import annotations

import math

from relationships import state as state_mod
from relationships.models import DEFAULT_RELATIONSHIP, RELATIONSHIP_FIELDS, clamp01

# Below this many eligible users (covers both spec 19.3's 1-9 and 10-19
# tiers — neither trims), no percentile trimming at all: small-group
# volatility is socially meaningful, not noise to smooth away (spec
# 19.2/19.3). The current Crypt averages ~5 active regulars per spec 19.2,
# so this no-trim path is the common case in practice, not the edge case.
# At or above this many eligible users, trim the extremes before computing
# the center.
_TRIM_AT = 20
_TRIM_FRACTION = 0.10

# Bandwidth controlling how quickly crypt_sway falls off from the
# population center (spec 19.4). Tunable — not derived from real stream
# data yet.
_DEFAULT_SIGMA = 5.0


def eligible_stream_counts() -> dict[str, int]:
    """username -> stream_count for every known relationship record.
    "Eligible" is currently "has ever been seen" — spec doesn't mandate a
    stricter definition (e.g. a minimum recency) for v1."""
    result: dict[str, int] = {}
    for username in state_mod.list_known_usernames():
        record = state_mod.load_relationship(username)
        result[username] = int(record.get("stream_count", 0))
    return result


def population_center(stream_counts: list[int]) -> float:
    """Trimmed mean of stream_count across eligible users (spec 19.1-19.3).
    Fewer than _TRIM_AT eligible users: no trimming at all, full population
    mean — small-Crypt volatility stays real."""
    if not stream_counts:
        return 0.0
    values = sorted(stream_counts)
    n = len(values)
    if n < _TRIM_AT:
        trimmed = values
    else:
        cut = int(n * _TRIM_FRACTION)
        trimmed = values[cut: n - cut] or values
    return sum(trimmed) / len(trimmed)


def population_sigma(stream_counts: list[int], center: float) -> float:
    """Standard deviation of stream_count around `center`. Falls back to
    _DEFAULT_SIGMA when there's too little data to measure spread, or when
    it comes out at/near zero — spec 19.5's "do not divide by zero"."""
    if len(stream_counts) < 2:
        return _DEFAULT_SIGMA
    variance = sum((v - center) ** 2 for v in stream_counts) / len(stream_counts)
    sigma = math.sqrt(variance)
    return sigma if sigma > 1e-6 else _DEFAULT_SIGMA


def crypt_sway(stream_count: float, center: float, sigma: float) -> float:
    """Bell-curve representativeness weight (spec 19.4) — peaks at 1.0 for
    a user exactly at the population center, falls off symmetrically as
    stream_count diverges from it in either direction. Not a popularity
    score: a brand-new user AND an extremely long-established one can both
    receive low sway despite being far apart on raw stream_count."""
    if sigma <= 1e-6:
        return 1.0
    return math.exp(-0.5 * ((stream_count - center) / sigma) ** 2)


def compute_crypt_sway_weights() -> dict[str, float]:
    """username -> crypt_sway for every eligible user. Degenerate-variance
    populations (everyone at the same stream_count, or too few data points)
    fall back to equal sway for everyone rather than an arbitrary weighting
    (spec 19.5)."""
    counts = eligible_stream_counts()
    if not counts:
        return {}
    values = list(counts.values())
    if len(set(values)) <= 1:
        return {username: 1.0 for username in counts}
    center = population_center(values)
    sigma = population_sigma(values, center)
    return {username: crypt_sway(count, center, sigma) for username, count in counts.items()}


def aggregate_crypt_relationship() -> dict[str, float]:
    """crypt_sway-weighted mean of eligible individual relationship
    primitives (spec 20). An empty or all-zero-weight population falls
    back to DEFAULT_RELATIONSHIP (the same stranger baseline a brand-new
    individual gets) rather than dividing by zero."""
    weights = compute_crypt_sway_weights()
    total_weight = sum(weights.values())
    if not weights or total_weight <= 1e-9:
        return dict(DEFAULT_RELATIONSHIP)

    totals = {field: 0.0 for field in RELATIONSHIP_FIELDS}
    for username, weight in weights.items():
        relationship = state_mod.load_relationship(username)["relationship"]
        for field in RELATIONSHIP_FIELDS:
            totals[field] += relationship.get(field, 0.0) * weight

    return {field: clamp01(totals[field] / total_weight) for field in RELATIONSHIP_FIELDS}


def expectation_violation(individual_relationship: dict, crypt_relationship: dict) -> float:
    """How much this person's relationship with Mai diverges from The
    Crypt's collective relationship, dampened by familiarity — a cheap,
    deterministic proxy for spec 22-23's "does this individual contradict
    my model of the group", fed to Curiosity. Simplification: divergence is
    measured over relationship state, not a separate behavioral model —
    there's no independent "expected behavior" signal to compare against
    yet, and relationship divergence is a reasonable correlate of it.

    Familiarity dampening implements spec 22 directly: "As familiarity
    with an individual increases, individual evidence should rapidly
    dominate" — a well-known regular being unlike the collective is just
    who they are, not a standing surprise.
    """
    familiarity = clamp01(individual_relationship.get("familiarity", 0.0))
    diffs = [
        abs(individual_relationship.get(field, 0.0) - crypt_relationship.get(field, 0.0))
        for field in RELATIONSHIP_FIELDS
    ]
    raw_divergence = sum(diffs) / len(diffs) if diffs else 0.0
    return clamp01(raw_divergence * (1.0 - familiarity))
