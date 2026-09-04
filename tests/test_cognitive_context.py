import unittest

from relationships.context import bucket_label, build_cognitive_context
from relationships.models import DEFAULT_NEEDS, DEFAULT_RELATIONSHIP, PartcoreResult, PartVote


class CognitiveContextTests(unittest.TestCase):
    def test_bucket_label_boundaries(self):
        self.assertEqual(bucket_label(0.0), "very low")
        self.assertEqual(bucket_label(0.19), "very low")
        self.assertEqual(bucket_label(0.2), "low")
        self.assertEqual(bucket_label(0.39), "low")
        self.assertEqual(bucket_label(0.4), "moderate")
        self.assertEqual(bucket_label(0.59), "moderate")
        self.assertEqual(bucket_label(0.6), "high")
        self.assertEqual(bucket_label(0.79), "high")
        self.assertEqual(bucket_label(0.8), "very high")
        self.assertEqual(bucket_label(1.0), "very high")

    def test_crypt_section_omitted_when_absent(self):
        result = PartcoreResult(active=PartVote("Familiar", "neutral", "[familiar:idle]"), secondary=[])
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, result, crypt=None)
        self.assertNotIn("[crypt]", text)

    def test_crypt_section_present_when_supplied(self):
        result = PartcoreResult(active=None, secondary=[])
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, result, crypt=DEFAULT_RELATIONSHIP)
        self.assertIn("[crypt]", text)

    def test_partcore_section_reflects_active_and_secondary(self):
        result = PartcoreResult(
            active=PartVote("Crash", "crash", "[crash:pet_peeve][intensity:snap]"),
            secondary=[PartVote("Bond", "engage", ""), PartVote("Tease", "engage", "")],
        )
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, result)
        self.assertIn("Active: Crash (crash)", text)
        self.assertIn("Secondary: Bond, Tease", text)
        self.assertIn("Reason: crash pet peeve, intensity snap", text)

    def test_partcore_section_omitted_when_no_active_part(self):
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None)
        self.assertNotIn("[partcore]", text)

    def test_relationship_and_needs_sections_always_present(self):
        result = PartcoreResult(active=None, secondary=[])
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, result)
        self.assertIn("[relationship]", text)
        self.assertIn("[needs]", text)
        self.assertIn("Familiarity:", text)
        self.assertIn("Social need:", text)

    def test_nickname_included_when_present(self):
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None, nickname="Little Gremlin")
        self.assertIn("Little Gremlin", text)

    def test_nickname_omitted_when_absent(self):
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None, nickname=None)
        self.assertNotIn("Nickname", text)

    def test_theory_of_mind_section_present_when_supplied(self):
        tom = {"believed_wants": "attention", "believed_view_of_mai": "amused by her", "confidence": 0.6}
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None, theory_of_mind=tom)
        self.assertIn("[theory_of_mind]", text)
        self.assertIn("attention", text)
        self.assertIn("amused by her", text)

    def test_theory_of_mind_section_omitted_when_absent(self):
        text = build_cognitive_context(DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None, theory_of_mind=None)
        self.assertNotIn("[theory_of_mind]", text)

    def test_current_crypt_lines_only_appear_alongside_historical_crypt(self):
        current = {"current_warmth": 0.9, "current_friction": 0.1}
        text = build_cognitive_context(
            DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None, crypt=None, current_crypt=current
        )
        # No historical [crypt] section to attach to -> current_crypt is
        # silently dropped rather than rendering a malformed lone section.
        self.assertNotIn("[crypt]", text)

    def test_current_crypt_lines_appear_within_crypt_section(self):
        current = {"current_warmth": 0.9, "current_friction": 0.1}
        text = build_cognitive_context(
            DEFAULT_RELATIONSHIP, DEFAULT_NEEDS, None, crypt=DEFAULT_RELATIONSHIP, current_crypt=current
        )
        self.assertIn("[crypt]", text)
        self.assertIn("warmth", text)
        self.assertIn("friction", text)


if __name__ == "__main__":
    unittest.main()
