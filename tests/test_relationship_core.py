import tempfile
import unittest
from unittest.mock import patch

from relationships.context import bucket_label
from relationships.models import DEFAULT_NEEDS, DEFAULT_OWNER_RELATIONSHIP, DEFAULT_RELATIONSHIP, PartcoreResult, PartVote
from relationships.needs import read_needs_state, write_needs_state
from relationships.relationship_core import build_cognitive_context, post_response_update
from relationships.state import load_relationship, user_file_exists


class RelationshipCorePostResponseUpdateTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_post_response_update_applies_engagement_delta_to_needs(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            write_needs_state({**DEFAULT_NEEDS, "loneliness": 0.5, "social_need": 0.5})
            before = read_needs_state()

            result = PartcoreResult(active=PartVote("Bond", "engage", "[bond:relational]"), secondary=[])
            post_response_update("nova", "hi mai", "hey there!", result)

            after = read_needs_state()
            self.assertLess(after["loneliness"], before["loneliness"])
            self.assertLess(after["social_need"], before["social_need"])
            self.assertGreater(after["happiness"], before["happiness"])

    def test_post_response_update_persists_a_relationship_file_on_first_contact(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self.assertFalse(user_file_exists("nova"))

            result = PartcoreResult(active=PartVote("Curiosity", "engage", "[curiosity:new_face]"), secondary=[])
            post_response_update("nova", "hi mai", "hey there!", result)

            self.assertTrue(user_file_exists("nova"))
            self.assertEqual(load_relationship("nova")["relationship"], DEFAULT_RELATIONSHIP)

    def test_post_response_update_persists_owner_baseline_on_first_contact(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Desire", "engage", "[desire:flirty]"), secondary=[])
            post_response_update(
                "mordraga0", "hi", "hey witch", result, owner_username="mordraga0"
            )

            self.assertTrue(user_file_exists("mordraga0"))
            self.assertEqual(load_relationship("mordraga0")["relationship"], DEFAULT_OWNER_RELATIONSHIP)

    def test_post_response_update_does_not_overwrite_an_existing_file_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            from relationships.state import save_relationship

            record = load_relationship("nova")
            record["relationship"]["affection"] = 0.77
            save_relationship("nova", record)

            result = PartcoreResult(active=PartVote("Bond", "engage", "[bond:relational]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            self.assertEqual(load_relationship("nova")["relationship"]["affection"], 0.77)


class BuildCognitiveContextOwnerDetectionTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_owner_username_match_uses_elevated_baseline(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            context_text, _ = build_cognitive_context(
                username="Mordraga0",
                message="hi",
                owner_username="mordraga0",
            )
            expected = bucket_label(DEFAULT_OWNER_RELATIONSHIP["affection"])
            self.assertIn(f"Affection: {expected}", context_text)

    def test_non_owner_username_uses_stranger_baseline(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            context_text, _ = build_cognitive_context(
                username="random_viewer",
                message="hi",
                owner_username="mordraga0",
            )
            expected = bucket_label(DEFAULT_RELATIONSHIP["affection"])
            self.assertIn(f"Affection: {expected}", context_text)


if __name__ == "__main__":
    unittest.main()
