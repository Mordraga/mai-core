import unittest

from relationships.models import PartVote
from relationships.parts import partcore


class PartcoreTests(unittest.TestCase):
    def test_crash_hard_override_beats_everything(self):
        votes = [
            PartVote("Crash", "crash", "[crash:crash_out]"),
            PartVote("Desire", "engage", "[desire:flirty]"),
            PartVote("Bond", "engage", "[bond:relational]"),
            PartVote("Tease", "engage", "[tease:banter]"),
            PartVote("Curiosity", "neutral", "[curiosity:idle]"),
            PartVote("Familiar", "recognize", "[familiar:regular]"),
        ]
        result = partcore.resolve(votes)
        self.assertEqual(result.active.part, "Crash")
        secondary_parts = {v.part for v in result.secondary}
        # Every other engaged Part is preserved as secondary, spec 15's
        # "I adore you. Shut the fuck up." — the love doesn't disappear.
        self.assertEqual(secondary_parts, {"Desire", "Bond", "Tease", "Familiar"})

    def test_crash_annoyed_does_not_override(self):
        votes = [
            PartVote("Crash", "annoyed", "[crash:annoyed]"),
            PartVote("Desire", "engage", "[desire:flirty]"),
            PartVote("Bond", "neutral", "[bond:idle]"),
            PartVote("Tease", "neutral", "[tease:idle]"),
            PartVote("Curiosity", "neutral", "[curiosity:idle]"),
            PartVote("Familiar", "neutral", "[familiar:idle]"),
        ]
        result = partcore.resolve(votes)
        self.assertEqual(result.active.part, "Desire")

    def test_priority_order_among_simultaneously_engaged_parts(self):
        votes = [
            PartVote("Crash", "neutral", ""),
            PartVote("Desire", "neutral", ""),
            PartVote("Bond", "engage", "[bond:relational]"),
            PartVote("Tease", "engage", "[tease:banter]"),
            PartVote("Curiosity", "neutral", ""),
            PartVote("Familiar", "recognize", "[familiar:regular]"),
        ]
        result = partcore.resolve(votes)
        # Bond precedes Tease precedes Familiar in PRIORITY.
        self.assertEqual(result.active.part, "Bond")
        self.assertEqual([v.part for v in result.secondary], ["Tease", "Familiar"])

    def test_all_neutral_defaults_to_familiar(self):
        votes = [
            PartVote("Crash", "neutral", ""),
            PartVote("Desire", "neutral", ""),
            PartVote("Bond", "neutral", ""),
            PartVote("Tease", "neutral", ""),
            PartVote("Curiosity", "neutral", ""),
            PartVote("Familiar", "neutral", "[familiar:idle]"),
        ]
        result = partcore.resolve(votes)
        self.assertEqual(result.active.part, "Familiar")
        self.assertEqual(result.secondary, [])


if __name__ == "__main__":
    unittest.main()
