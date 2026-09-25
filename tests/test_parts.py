import unittest

from relationships.models import NEEDS_DEFAULTS, PartContext
from relationships.parts import Bond, Crash, Curiosity, Desire, Familiar, Tease

LOVED_REGULAR = {
    "trust": 0.91, "familiarity": 0.98, "reciprocity": 0.89, "enjoyment": 0.95,
    "respect": 0.81, "reliability": 0.88, "interest": 0.82, "affection": 0.94,
    "hate": 0.02, "resentment": 0.18, "closeness_desire": 0.91,
}

FASCINATING_ENEMY = {
    "trust": 0.18, "familiarity": 0.91, "reciprocity": 0.71, "enjoyment": 0.67,
    "respect": 0.21, "reliability": 0.79, "interest": 0.96, "affection": 0.12,
    "hate": 0.88, "resentment": 0.81, "closeness_desire": 0.74,
}

QUIET_VIOLATOR = {
    "trust": 0.68, "familiarity": 0.35, "reciprocity": 0.52, "enjoyment": 0.72,
    "respect": 0.83, "reliability": 0.71, "interest": 0.92, "affection": 0.31,
    "hate": 0.01, "resentment": 0.00, "closeness_desire": 0.46,
}

# "Chaotic and provocative" Crypt prior, so QUIET_VIOLATOR's restraint diverges sharply from it.
CHAOTIC_CRYPT = {
    "trust": 0.20, "familiarity": 0.8, "reciprocity": 0.5, "enjoyment": 0.20,
    "respect": 0.15, "reliability": 0.15, "interest": 0.6, "affection": 0.15,
    "hate": 0.1, "resentment": 0.2, "closeness_desire": 0.4,
}


LOVED_BUT_RESENTFUL = dict(LOVED_REGULAR)
LOVED_BUT_RESENTFUL["resentment"] = 0.6


def make_ctx(relationship, crypt_relationship=None, needs=None, observations=None, task="general", config=None):
    return PartContext(
        username="tester",
        message="hello",
        task=task,
        recent_messages=[],
        relationship=relationship,
        friendship={"utility": 0.5, "pleasure": 0.5, "virtue": 0.5},
        crypt_relationship=crypt_relationship or {},
        needs=needs or dict(NEEDS_DEFAULTS),
        observations=observations or [],
        config=config or {},
    )


class PartTests(unittest.TestCase):
    def test_bond_high_for_loved_regular(self):
        result = Bond().evaluate(make_ctx(LOVED_REGULAR))
        self.assertGreater(result.activation, 0.8)
        self.assertIn("strong_affection", result.reason_codes)

    def test_bond_can_flag_loved_but_resentful(self):
        result = Bond().evaluate(make_ctx(LOVED_BUT_RESENTFUL))
        self.assertIn("loved_but_resentful", result.reason_codes)

    def test_curiosity_high_for_fascinating_enemy(self):
        # High interest alone (no crypt prior supplied) should already push
        # Curiosity's activation well above its engage threshold.
        result = Curiosity().evaluate(make_ctx(FASCINATING_ENEMY))
        self.assertGreater(result.activation, 0.5)
        self.assertEqual(result.vote, "engage")

    def test_curiosity_activates_on_expectation_violation(self):
        divergent = Curiosity().evaluate(make_ctx(QUIET_VIOLATOR, crypt_relationship=CHAOTIC_CRYPT))
        aligned = Curiosity().evaluate(make_ctx(QUIET_VIOLATOR, crypt_relationship=QUIET_VIOLATOR))
        self.assertGreater(divergent.activation, aligned.activation)
        self.assertIn("violates_crypt_expectation", divergent.reason_codes)

    def test_familiar_low_for_new_face(self):
        new_face = dict(QUIET_VIOLATOR)
        new_face["familiarity"] = 0.05
        result = Familiar().evaluate(make_ctx(new_face))
        self.assertIn("new_or_unknown_face", result.reason_codes)

    def test_crash_neutral_without_frustration_or_resentment(self):
        result = Crash().evaluate(make_ctx(LOVED_REGULAR, needs=dict(NEEDS_DEFAULTS)))
        self.assertEqual(result.tier, "neutral")

    def test_crash_can_activate_for_someone_loved(self):
        # High affection (LOVED_REGULAR) does not prevent Crash from firing —
        # it is not the inverse of affection (spec §15).
        needs = dict(NEEDS_DEFAULTS)
        needs["frustration"] = 1.0
        needs["anger"] = 1.0
        observations = [{"type": "pet_peeve", "salience": 0.9}, {"type": "pet_peeve", "salience": 0.8}]
        result = Crash().evaluate(make_ctx(LOVED_REGULAR, needs=needs, observations=observations))
        self.assertIn(result.tier, ("snap", "crash"))
        self.assertIn("repeated_pet_peeve", result.reason_codes)

    def test_desire_not_inherently_sexual_at_baseline_arousal(self):
        result = Desire().evaluate(make_ctx(LOVED_REGULAR, task="general"))
        self.assertIn("wants_attention_not_sexual", result.reason_codes)

    def test_tease_recognizes_established_banter(self):
        observations = [{"type": "established_banter"} for _ in range(3)]
        result = Tease().evaluate(make_ctx(LOVED_REGULAR, observations=observations))
        self.assertIn("established_banter", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
