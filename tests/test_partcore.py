import unittest
from unittest.mock import patch

from relationships.models import NEEDS_DEFAULTS, PartContext, PartResult
from relationships.parts import partcore
from relationships.parts.partcore import DEFAULT_PART_THRESHOLDS, _effective_thresholds


class FakePart:
    def __init__(self, name, activation, tier=None, reason_codes=None):
        self.part_name = name
        self._activation = activation
        self._tier = tier
        self._reason_codes = reason_codes or []

    def evaluate(self, ctx):
        vote = self._tier if self._tier else ("engage" if self._activation >= 0.45 else "idle")
        return PartResult(
            part=self.part_name,
            activation=self._activation,
            vote=vote,
            reason_codes=self._reason_codes,
            tier=self._tier,
        )


def make_ctx(config=None, needs=None):
    return PartContext(
        username="tester", message="hi", task="general", recent_messages=[],
        relationship={}, friendship={}, crypt_relationship={},
        needs=needs or dict(NEEDS_DEFAULTS), observations=[], config=config or {},
    )


class PartcoreThresholdTests(unittest.TestCase):
    def test_high_boredom_lowers_tease_and_curiosity_thresholds(self):
        needs = dict(NEEDS_DEFAULTS)
        needs["boredom"] = 0.8
        thresholds = _effective_thresholds(needs, {})
        self.assertLess(thresholds["Tease"], DEFAULT_PART_THRESHOLDS["Tease"])
        self.assertLess(thresholds["Curiosity"], DEFAULT_PART_THRESHOLDS["Curiosity"])
        self.assertEqual(thresholds["Bond"], DEFAULT_PART_THRESHOLDS["Bond"])

    def test_low_energy_raises_all_thresholds(self):
        needs = dict(NEEDS_DEFAULTS)
        needs["energy"] = 0.1
        thresholds = _effective_thresholds(needs, {})
        for part_name, base in DEFAULT_PART_THRESHOLDS.items():
            self.assertGreater(thresholds[part_name], base)

    def test_high_frustration_lowers_crash_threshold(self):
        needs = dict(NEEDS_DEFAULTS)
        needs["frustration"] = 0.9
        thresholds = _effective_thresholds(needs, {})
        self.assertLess(thresholds["Crash"], DEFAULT_PART_THRESHOLDS["Crash"])


class PartcoreArbitrationTests(unittest.TestCase):
    def test_crash_hard_override_wins_regardless_of_other_activations(self):
        fake_parts = [
            FakePart("Familiar", 0.9),
            FakePart("Bond", 0.95),
            FakePart("Desire", 0.2),
            FakePart("Tease", 0.2),
            FakePart("Curiosity", 0.2),
            FakePart("Crash", 0.9, tier="crash"),
        ]
        with patch.object(partcore, "_PARTS", fake_parts):
            result = partcore.resolve(make_ctx())
        self.assertTrue(result.hard_override)
        self.assertEqual(result.active.part, "Crash")
        # Bond (0.95, above its threshold) should survive as secondary, not be discarded.
        self.assertIn("Bond", [p.part for p in result.secondary])

    def test_exact_tie_broken_by_priority_order(self):
        fake_parts = [
            FakePart("Familiar", 0.1),
            FakePart("Bond", 0.70),
            FakePart("Desire", 0.70),
            FakePart("Tease", 0.1),
            FakePart("Curiosity", 0.1),
            FakePart("Crash", 0.1, tier="neutral"),
        ]
        with patch.object(partcore, "_PARTS", fake_parts):
            result = partcore.resolve(make_ctx())
        # DEFAULT_PRIORITY_ORDER places Bond ahead of Desire.
        self.assertEqual(result.active.part, "Bond")

    def test_highest_activation_wins_when_not_tied(self):
        fake_parts = [
            FakePart("Familiar", 0.1),
            FakePart("Bond", 0.5),
            FakePart("Desire", 0.9),
            FakePart("Tease", 0.1),
            FakePart("Curiosity", 0.1),
            FakePart("Crash", 0.1, tier="neutral"),
        ]
        with patch.object(partcore, "_PARTS", fake_parts):
            result = partcore.resolve(make_ctx())
        self.assertEqual(result.active.part, "Desire")
        self.assertIn("Bond", [p.part for p in result.secondary])

    def test_no_part_above_threshold_yields_no_active_part(self):
        fake_parts = [FakePart(name, 0.05) for name in ("Familiar", "Bond", "Desire", "Tease", "Curiosity")]
        fake_parts.append(FakePart("Crash", 0.05, tier="neutral"))
        with patch.object(partcore, "_PARTS", fake_parts):
            result = partcore.resolve(make_ctx())
        self.assertIsNone(result.active)
        self.assertFalse(result.hard_override)

    def test_secondary_capped_and_sorted_by_activation(self):
        fake_parts = [
            FakePart("Familiar", 0.9, reason_codes=["a"]),
            FakePart("Bond", 0.5),
            FakePart("Desire", 0.99),
            FakePart("Tease", 0.6),
            FakePart("Curiosity", 0.55),
            FakePart("Crash", 0.1, tier="neutral"),
        ]
        with patch.object(partcore, "_PARTS", fake_parts):
            result = partcore.resolve(make_ctx())
        self.assertEqual(result.active.part, "Desire")
        self.assertEqual(len(result.secondary), 2)
        # Capped at 2, sorted by activation desc: Familiar (0.9) then Tease (0.6) —
        # Curiosity (0.55) and Bond (0.5) are above threshold too but get dropped.
        self.assertEqual([p.part for p in result.secondary], ["Familiar", "Tease"])


if __name__ == "__main__":
    unittest.main()
