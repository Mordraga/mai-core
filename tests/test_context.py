import unittest

from relationships import context
from relationships.models import NEEDS_DEFAULTS, PartResult, PartcoreResult, RELATIONSHIP_DEFAULTS


class BandTests(unittest.TestCase):
    def test_band_boundaries(self):
        self.assertEqual(context.band(0.0), "very low")
        self.assertEqual(context.band(0.19), "very low")
        self.assertEqual(context.band(0.2), "low")
        self.assertEqual(context.band(0.5), "moderate")
        self.assertEqual(context.band(0.79), "high")
        self.assertEqual(context.band(0.8), "very high")
        self.assertEqual(context.band(1.0), "very high")


class SelectiveInclusionTests(unittest.TestCase):
    def test_near_default_primitives_excluded(self):
        relationship = dict(RELATIONSHIP_DEFAULTS)  # every value at neutral default
        keys = context._relevant_keys(relationship, [], threshold=0.15)
        self.assertEqual(keys, [])

    def test_off_default_primitives_included(self):
        relationship = dict(RELATIONSHIP_DEFAULTS)
        relationship["affection"] = 0.9
        keys = context._relevant_keys(relationship, [], threshold=0.15)
        self.assertIn("affection", keys)
        self.assertNotIn("hate", keys)

    def test_reason_code_forces_inclusion_even_near_default(self):
        relationship = dict(RELATIONSHIP_DEFAULTS)  # resentment at default 0.0
        keys = context._relevant_keys(relationship, ["existing_resentment"], threshold=0.15)
        self.assertIn("resentment", keys)


class BuildContextTextTests(unittest.TestCase):
    def test_includes_all_four_blocks(self):
        relationship = dict(RELATIONSHIP_DEFAULTS)
        relationship["affection"] = 0.9
        relationship["familiarity"] = 0.9
        crypt_relationship = dict(RELATIONSHIP_DEFAULTS)
        needs = dict(NEEDS_DEFAULTS)
        active = PartResult(part="Bond", activation=0.8, vote="engage", reason_codes=["strong_affection"])
        partcore_result = PartcoreResult(active=active, secondary=[], all_results=[active])

        text = context.build_context_text("Nova", relationship, crypt_relationship, needs, partcore_result)
        self.assertIn("[relationship]", text)
        self.assertIn("[crypt]", text)
        self.assertIn("[needs]", text)
        self.assertIn("[partcore]", text)
        self.assertIn("Target: Nova", text)
        self.assertIn("Active: Bond", text)

    def test_no_active_part_reports_baseline(self):
        relationship = dict(RELATIONSHIP_DEFAULTS)
        crypt_relationship = dict(RELATIONSHIP_DEFAULTS)
        needs = dict(NEEDS_DEFAULTS)
        partcore_result = PartcoreResult(active=None, secondary=[], all_results=[])

        text = context.build_context_text("Nova", relationship, crypt_relationship, needs, partcore_result)
        self.assertIn("baseline personality", text)


if __name__ == "__main__":
    unittest.main()
