"""PartCore — deterministic arbitration over Part votes (spec section 16).

Selyros-beta style: a short, readable, hardcoded precedence chain rather
than a generic activation/threshold engine. Crash is handled specially per
spec 15.2 ("Low Crash should color behavior. High Crash should be capable
of stealing active_part."):

  - "crash" or "snap" (a real interpersonal snap, not just visible
    irritation) steal active_part outright, ahead of everything else.
  - "annoyed" never becomes active_part on its own — it only shows up as a
    secondary influence, so a fully engaged Desire/Bond/Tease can still win
    while Crash's irritation still colors the cognitive context (spec
    15.2's own example: Crash "annoyed" + Desire "engage" -> Desire is
    active, Mai "may flirt while visibly irritated").

Every other engaged Part is preserved as a secondary influence rather than
discarded (spec 16.1 point 5).
"""
from __future__ import annotations

from relationships.models import PartcoreResult, PartVote

# Configurable in one place, per spec 16.1 ("priority order should be
# configurable rather than deeply hardcoded") — kept as a plain constant
# instead of an external data file. Crash is deliberately not listed here;
# it's arbitrated separately (see module docstring).
PRIORITY: tuple[str, ...] = ("Desire", "Bond", "Tease", "Curiosity", "Familiar")

_NEUTRAL_VOTES = {"neutral"}
_CRASH_STEAL_VOTES = {"crash", "snap"}


def resolve(votes: list[PartVote]) -> PartcoreResult:
    by_part = {v.part: v for v in votes}
    crash = by_part.get("Crash")

    if crash is not None and crash.vote in _CRASH_STEAL_VOTES:
        secondary = [v for v in votes if v.part != "Crash" and v.vote not in _NEUTRAL_VOTES]
        return PartcoreResult(active=crash, secondary=secondary)

    crash_colors = crash is not None and crash.vote not in _NEUTRAL_VOTES

    engaged = [
        by_part[part_name]
        for part_name in PRIORITY
        if part_name in by_part and by_part[part_name].vote not in _NEUTRAL_VOTES
    ]

    if not engaged:
        secondary = [crash] if crash_colors else []
        return PartcoreResult(active=by_part.get("Familiar"), secondary=secondary)

    active, secondary = engaged[0], engaged[1:]
    if crash_colors:
        secondary = secondary + [crash]
    return PartcoreResult(active=active, secondary=secondary)
