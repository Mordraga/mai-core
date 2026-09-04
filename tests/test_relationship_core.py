import tempfile
import unittest
from unittest.mock import patch

from relationships.context import bucket_label
from relationships.models import DEFAULT_NEEDS, DEFAULT_OWNER_RELATIONSHIP, DEFAULT_RELATIONSHIP, PartcoreResult, PartVote
from relationships.needs import read_needs_state, write_needs_state
from relationships.crypt_mood import read_current_crypt_state
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

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_applies_inferred_relationship_deltas(self, mock_infer):
        mock_infer.return_value = {"deltas": {"trust": 0.05, "enjoyment": -0.02}, "observation": None}
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Bond", "engage", "[bond:relational]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            relationship = load_relationship("nova")["relationship"]
            self.assertAlmostEqual(relationship["trust"], DEFAULT_RELATIONSHIP["trust"] + 0.05)
            self.assertAlmostEqual(relationship["enjoyment"], DEFAULT_RELATIONSHIP["enjoyment"] - 0.02)

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_persists_inferred_observation(self, mock_infer):
        mock_infer.return_value = {
            "deltas": {},
            "observation": {"type": "pet_peeve", "name": "denies_realness", "confidence": 0.85, "note": "note"},
        }
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Crash", "annoyed", "[crash:idle]"), secondary=[])
            post_response_update("nova", "you're just a bot", "rude.", result)

            observations = load_relationship("nova")["observations"]
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["name"], "denies_realness")

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_leaves_relationship_untouched_when_inference_returns_none(self, mock_infer):
        mock_infer.return_value = None
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Bond", "engage", "[bond:relational]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            self.assertEqual(load_relationship("nova")["relationship"], DEFAULT_RELATIONSHIP)

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_passes_recent_messages_through_to_inference(self, mock_infer):
        mock_infer.return_value = None
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Bond", "engage", "[bond:relational]"), secondary=[])
            post_response_update("nova", "hi", "hey", result, recent_messages=["hi", "hi again"])

            self.assertEqual(mock_infer.call_args.kwargs["recent_messages"], ["hi", "hi again"])

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_accepts_a_high_confidence_nickname(self, mock_infer):
        mock_infer.return_value = {
            "deltas": {},
            "observation": {"type": "nickname", "name": "pi_bit", "confidence": 0.85, "note": "Digit Demon"},
            "theory_of_mind": None,
        }
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Tease", "engage", "[tease:banter]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            record = load_relationship("nova")
            self.assertEqual(record["nickname"], "Digit Demon")
            self.assertEqual(record["observations"], [])

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_rejects_a_low_confidence_nickname(self, mock_infer):
        mock_infer.return_value = {
            "deltas": {},
            "observation": {"type": "nickname", "name": "joke", "confidence": 0.35, "note": "One-Off Joke"},
            "theory_of_mind": None,
        }
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Tease", "engage", "[tease:banter]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            self.assertIsNone(load_relationship("nova")["nickname"])

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_persists_callback_observation_like_pet_peeve(self, mock_infer):
        mock_infer.return_value = {
            "deltas": {},
            "observation": {"type": "callback", "name": "pi_bit", "confidence": 0.6, "note": "recited pi"},
            "theory_of_mind": None,
        }
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Tease", "engage", "[tease:banter]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            observations = load_relationship("nova")["observations"]
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["type"], "callback")

    @patch("relationships.relationship_core.mutation_mod.infer_relationship_update")
    def test_post_response_update_persists_theory_of_mind_with_timestamp(self, mock_infer):
        mock_infer.return_value = {
            "deltas": {},
            "observation": None,
            "theory_of_mind": {"believed_wants": "attention", "believed_view_of_mai": "amused", "confidence": 0.6},
        }
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Bond", "engage", "[bond:relational]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            tom = load_relationship("nova")["theory_of_mind"]
            self.assertEqual(tom["believed_wants"], "attention")
            self.assertIsNotNone(tom["last_updated"])

    def test_post_response_update_nudges_current_crypt_state(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Crash", "crash", "[crash:crash_out]"), secondary=[])
            post_response_update("nova", "hi", "hey", result)

            current = read_current_crypt_state()
            self.assertGreater(current["current_friction"], 0.0)


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

    def test_context_includes_a_crypt_section(self):
        # spec Phase 5: The Crypt's aggregate relationship should reach the
        # cognitive context alongside [relationship]/[needs]/[partcore],
        # even with only this one user known (falls back to
        # DEFAULT_RELATIONSHIP as the aggregate, per crypt.py).
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            context_text, _ = build_cognitive_context(
                username="nova",
                message="hi",
                owner_username="mordraga0",
            )
            self.assertIn("[crypt]", context_text)

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
