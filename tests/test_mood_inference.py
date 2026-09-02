import unittest
from unittest.mock import patch

from relationships.models import DEFAULT_NEEDS
from utils.mood_engine import choose_weighted_mood, infer_mood_from_needs


class MoodInferenceTests(unittest.TestCase):
    @patch("utils.mood_engine.ask_openrouter")
    def test_success_path_parses_name_and_guidance(self, mock_ask):
        mock_ask.return_value = (
            "MOOD: Manic-gremlin\n"
            "GUIDANCE: Everything looks like an opportunity to start shit."
        )
        result = infer_mood_from_needs(DEFAULT_NEEDS)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Manic-gremlin")
        self.assertIn("opportunity", result["guidance"])

    @patch("utils.mood_engine.ask_openrouter")
    def test_llm_exception_returns_none(self, mock_ask):
        mock_ask.side_effect = RuntimeError("network down")
        result = infer_mood_from_needs(DEFAULT_NEEDS)
        self.assertIsNone(result)

    @patch("utils.mood_engine.ask_openrouter")
    def test_warning_response_returns_none(self, mock_ask):
        mock_ask.return_value = "WARNING: Missing OpenRouter API key"
        result = infer_mood_from_needs(DEFAULT_NEEDS)
        self.assertIsNone(result)

    @patch("utils.mood_engine.ask_openrouter")
    def test_garbage_response_without_mood_line_returns_none(self, mock_ask):
        mock_ask.return_value = "I'm not sure how she feels today."
        result = infer_mood_from_needs(DEFAULT_NEEDS)
        self.assertIsNone(result)

    @patch("utils.mood_engine.ask_openrouter")
    def test_empty_response_returns_none(self, mock_ask):
        mock_ask.return_value = ""
        result = infer_mood_from_needs(DEFAULT_NEEDS)
        self.assertIsNone(result)

    def test_fallback_weighted_mood_still_works_standalone(self):
        # Sanity check that the safety-net path this module falls back to
        # on inference failure is itself untouched by the retrofit.
        chosen = choose_weighted_mood({"quiet": {"weight": 0}, "flirty": {"weight": 3}})
        self.assertEqual(chosen, "flirty")


if __name__ == "__main__":
    unittest.main()
