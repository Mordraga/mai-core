import unittest
from unittest.mock import patch

from relationships.models import DEFAULT_RELATIONSHIP
from relationships.mutation import (
    apply_bounded_deltas,
    infer_relationship_update,
    merge_observation,
)


class InferRelationshipUpdateTests(unittest.TestCase):
    def test_parses_a_single_delta_line(self):
        with patch("relationships.mutation.ask_openrouter", return_value="trust: down slightly"):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["deltas"], {"trust": -0.02})
        self.assertIsNone(result["observation"])

    def test_parses_multiple_delta_lines_and_intensities(self):
        raw = "affection: up moderately\nresentment: up strongly\ninterest: down slightly"
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertEqual(
            result["deltas"],
            {"affection": 0.05, "resentment": 0.08, "interest": -0.02},
        )

    def test_parses_observation_line(self):
        raw = "OBSERVATION: pet_peeve | denies_realness | high | Called her a bot again."
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "you're just a bot", "rude.", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["deltas"], {})
        self.assertEqual(
            result["observation"],
            {
                "type": "pet_peeve",
                "name": "denies_realness",
                "confidence": 0.85,
                "note": "Called her a bot again.",
            },
        )

    def test_parses_deltas_and_observation_together(self):
        raw = (
            "trust: down slightly\n"
            "OBSERVATION: preference | likes_being_teased | moderate | Lights up when teased."
        )
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["deltas"], {"trust": -0.02})
        self.assertEqual(result["observation"]["type"], "preference")

    def test_none_response_returns_none(self):
        with patch("relationships.mutation.ask_openrouter", return_value="NONE"):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertIsNone(result)

    def test_unparseable_response_returns_none(self):
        with patch("relationships.mutation.ask_openrouter", return_value="I decline to answer that."):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertIsNone(result)

    def test_warning_response_returns_none(self):
        with patch("relationships.mutation.ask_openrouter", return_value="WARNING: Missing OpenRouter API key"):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertIsNone(result)

    def test_empty_response_returns_none(self):
        with patch("relationships.mutation.ask_openrouter", return_value=""):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertIsNone(result)

    def test_llm_exception_returns_none(self):
        with patch("relationships.mutation.ask_openrouter", side_effect=RuntimeError("network down")):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertIsNone(result)

    def test_parses_callback_observation(self):
        raw = "OBSERVATION: callback | pi_digits_bit | moderate | Made her recite digits of pi on command."
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "list pi", "sure...", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["observation"]["type"], "callback")
        self.assertEqual(result["observation"]["name"], "pi_digits_bit")

    def test_parses_nickname_observation(self):
        raw = "OBSERVATION: nickname | pi_bit | high | Digit Demon"
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["observation"]["type"], "nickname")
        self.assertEqual(result["observation"]["note"], "Digit Demon")

    def test_parses_theory_of_mind_line(self):
        raw = "THEORY_OF_MIND: attention from her | that she finds him amusing | moderate"
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["deltas"], {})
        self.assertIsNone(result["observation"])
        self.assertEqual(
            result["theory_of_mind"],
            {
                "believed_wants": "attention from her",
                "believed_view_of_mai": "that she finds him amusing",
                "confidence": 0.6,
            },
        )

    def test_parses_deltas_observation_and_theory_of_mind_together(self):
        raw = (
            "trust: up slightly\n"
            "OBSERVATION: preference | likes_being_teased | moderate | note\n"
            "THEORY_OF_MIND: to be teased | that she enjoys him | high"
        )
        with patch("relationships.mutation.ask_openrouter", return_value=raw):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertEqual(result["deltas"], {"trust": 0.02})
        self.assertEqual(result["observation"]["type"], "preference")
        self.assertEqual(result["theory_of_mind"]["confidence"], 0.85)

    def test_rejects_a_field_not_in_the_valid_dimension_list(self):
        # "vibes" isn't a real relationship dimension — the fixed-vocabulary
        # regex must not match it, so it's silently dropped rather than
        # injecting an arbitrary key into the relationship dict.
        with patch("relationships.mutation.ask_openrouter", return_value="vibes: up strongly"):
            result = infer_relationship_update("nova", "hi", "hey", DEFAULT_RELATIONSHIP)
        self.assertIsNone(result)


class ApplyBoundedDeltasTests(unittest.TestCase):
    def test_applies_a_delta_within_bounds(self):
        result = apply_bounded_deltas(DEFAULT_RELATIONSHIP, {"trust": 0.05})
        self.assertAlmostEqual(result["trust"], DEFAULT_RELATIONSHIP["trust"] + 0.05)

    def test_clamps_to_zero_one_range(self):
        result = apply_bounded_deltas({**DEFAULT_RELATIONSHIP, "hate": 0.99}, {"hate": 0.08})
        self.assertEqual(result["hate"], 1.0)

    def test_reclamps_an_oversized_delta_to_the_per_message_cap(self):
        # Defensive re-bound: even if a caller somehow hands in a delta
        # bigger than the fixed intensity vocabulary would ever produce,
        # a single exchange still can't move a primitive further than the cap.
        result = apply_bounded_deltas(DEFAULT_RELATIONSHIP, {"trust": 0.5})
        self.assertAlmostEqual(result["trust"], DEFAULT_RELATIONSHIP["trust"] + 0.08)

    def test_ignores_unknown_field(self):
        result = apply_bounded_deltas(DEFAULT_RELATIONSHIP, {"vibes": 0.5})
        self.assertNotIn("vibes", result)

    def test_leaves_relationship_untouched_when_no_deltas(self):
        result = apply_bounded_deltas(DEFAULT_RELATIONSHIP, {})
        self.assertEqual(result, DEFAULT_RELATIONSHIP)


class MergeObservationTests(unittest.TestCase):
    def test_none_observation_returns_observations_unchanged(self):
        existing = [{"type": "pet_peeve", "name": "x", "confidence": 0.5, "reinforced_count": 1}]
        self.assertEqual(merge_observation(existing, None), existing)

    def test_appends_a_new_observation(self):
        result = merge_observation([], {"type": "pet_peeve", "name": "denies_realness", "confidence": 0.85, "note": "n"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "pet_peeve")
        self.assertEqual(result[0]["name"], "denies_realness")
        self.assertEqual(result[0]["reinforced_count"], 1)

    def test_reinforces_a_matching_existing_observation_instead_of_duplicating(self):
        existing = [{
            "type": "pet_peeve", "name": "denies_realness",
            "confidence": 0.6, "reinforced_count": 2, "note": "old note", "last_reinforced": 1.0,
        }]
        result = merge_observation(
            existing,
            {"type": "pet_peeve", "name": "denies_realness", "confidence": 0.85, "note": "new note"},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reinforced_count"], 3)
        self.assertGreater(result[0]["confidence"], 0.6)
        self.assertEqual(result[0]["note"], "new note")
        self.assertGreater(result[0]["last_reinforced"], 1.0)

    def test_confidence_capped_when_reinforced_repeatedly(self):
        existing = [{"type": "pet_peeve", "name": "x", "confidence": 0.95, "reinforced_count": 10}]
        result = merge_observation(existing, {"type": "pet_peeve", "name": "x", "confidence": 0.9, "note": ""})
        self.assertLessEqual(result[0]["confidence"], 0.97)

    def test_caps_total_observations_keeping_the_strongest(self):
        existing = [
            {"type": "preference", "name": f"item_{i}", "confidence": 0.1, "reinforced_count": 1}
            for i in range(45)
        ]
        result = merge_observation(
            existing,
            {"type": "preference", "name": "brand_new", "confidence": 0.9, "note": "strong signal"},
        )
        self.assertLessEqual(len(result), 40)
        names = [o["name"] for o in result]
        self.assertIn("brand_new", names)


if __name__ == "__main__":
    unittest.main()
