"""
Partcore — deterministic arbitration among competing Parts (spec §16).

1. Needs shift each Part's effective activation threshold (§16.2) — thresholds,
   not a single hidden weighted equation, are how mood pressure is expressed.
2. Crash at its configured crash-out tier is a hard override (§16.1.1).
3. Otherwise the highest-activation Part clearing its own threshold wins;
   exact ties broken by a configurable priority order (§16.1.3).
4. Other above-threshold Parts survive as `secondary` — contradiction is not
   discarded just because one Part won (§16.1.5).
"""
from __future__ import annotations

from relationships.models import PartContext, PartcoreResult, PartResult
from relationships.parts.familiar import Familiar
from relationships.parts.bond import Bond
from relationships.parts.desire import Desire
from relationships.parts.tease import Tease
from relationships.parts.curiosity import Curiosity
from relationships.parts.crash import Crash

DEFAULT_PART_THRESHOLDS = {
    "Familiar": 0.40,
    "Bond": 0.45,
    "Desire": 0.45,
    "Tease": 0.45,
    "Curiosity": 0.45,
    "Crash": 0.35,
}

DEFAULT_PRIORITY_ORDER = ["Crash", "Bond", "Desire", "Tease", "Curiosity", "Familiar"]

DEFAULT_NEEDS_THRESHOLD_SHIFTS = {
    "boredom": {"trigger": 0.6, "shifts": {"Tease": -0.15, "Curiosity": -0.10}},
    "social_need": {"trigger": 0.6, "shifts": {"Bond": -0.10, "Desire": -0.10}},
    "frustration": {"trigger": 0.5, "shifts": {"Crash": -0.15}},
    "low_energy": {"trigger": 0.3, "shifts": {"__all__": 0.10}},  # low energy -> fewer impulses cross
}

_PARTS = [Familiar(), Bond(), Desire(), Tease(), Curiosity(), Crash()]

MAX_SECONDARY = 2


def _effective_thresholds(needs: dict, config: dict) -> dict[str, float]:
    base = dict(config.get("part_thresholds", DEFAULT_PART_THRESHOLDS))
    shifts_config = config.get("needs_threshold_shifts", DEFAULT_NEEDS_THRESHOLD_SHIFTS)

    thresholds = dict(base)
    for need_key, rule in shifts_config.items():
        trigger = rule.get("trigger", 1.0)
        if need_key == "low_energy":
            active = needs.get("energy", 0.7) <= trigger
        else:
            active = needs.get(need_key, 0.0) >= trigger
        if not active:
            continue
        for part_name, delta in rule.get("shifts", {}).items():
            if part_name == "__all__":
                for name in thresholds:
                    thresholds[name] = thresholds[name] + delta
            else:
                thresholds[part_name] = thresholds.get(part_name, 0.45) + delta

    return {name: max(0.0, min(1.0, value)) for name, value in thresholds.items()}


def resolve(ctx: PartContext) -> PartcoreResult:
    config = ctx.config or {}
    results: list[PartResult] = [part.evaluate(ctx) for part in _PARTS]
    thresholds = _effective_thresholds(ctx.needs, config)
    priority_order = config.get("priority_order", DEFAULT_PRIORITY_ORDER)

    by_name = {r.part: r for r in results}

    crash_result = by_name.get("Crash")
    if crash_result is not None and crash_result.tier == "crash":
        secondary = _above_threshold(results, thresholds, exclude=crash_result.part)
        return PartcoreResult(active=crash_result, secondary=secondary, all_results=results, hard_override=True)

    candidates = [r for r in results if r.activation >= thresholds.get(r.part, 0.45)]
    if not candidates:
        return PartcoreResult(active=None, secondary=[], all_results=results, hard_override=False)

    max_activation = max(r.activation for r in candidates)
    tied = [r for r in candidates if abs(r.activation - max_activation) < 1e-9]
    if len(tied) > 1:
        tied.sort(key=lambda r: priority_order.index(r.part) if r.part in priority_order else len(priority_order))
        active = tied[0]
    else:
        active = tied[0]

    secondary = _above_threshold(candidates, thresholds, exclude=active.part)
    return PartcoreResult(active=active, secondary=secondary, all_results=results, hard_override=False)


def _above_threshold(results: list[PartResult], thresholds: dict, exclude: str) -> list[PartResult]:
    others = [r for r in results if r.part != exclude and r.activation >= thresholds.get(r.part, 0.45)]
    others.sort(key=lambda r: r.activation, reverse=True)
    return others[:MAX_SECONDARY]
