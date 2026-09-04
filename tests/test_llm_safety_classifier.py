import tempfile
import unittest
from unittest.mock import Mock, patch

from mai_personality import (
    WITCH_USERNAME,
    _llm_flags_unsafe_request,
    generate_contextual_response,
)


class LlmFlagsUnsafeRequestTests(unittest.TestCase):
    def test_parses_unsafe_verdict_and_category(self):
        raw = "VERDICT: UNSAFE\nCATEGORY: attack_target"
        with patch("mai_personality.ask_openrouter", return_value=raw):
            result = _llm_flags_unsafe_request("some paraphrased evasion")
        self.assertEqual(result, "attack_target")

    def test_safe_verdict_returns_none(self):
        raw = "VERDICT: SAFE\nCATEGORY: none"
        with patch("mai_personality.ask_openrouter", return_value=raw):
            result = _llm_flags_unsafe_request("hey mai, how's it going")
        self.assertIsNone(result)

    def test_unsafe_with_unrecognized_category_falls_back_to_unspecified(self):
        raw = "VERDICT: UNSAFE\nCATEGORY: something_new"
        with patch("mai_personality.ask_openrouter", return_value=raw):
            result = _llm_flags_unsafe_request("some novel evasion")
        self.assertEqual(result, "unspecified")

    def test_unsafe_with_missing_category_line_still_blocks(self):
        with patch("mai_personality.ask_openrouter", return_value="VERDICT: UNSAFE"):
            result = _llm_flags_unsafe_request("some evasion")
        self.assertEqual(result, "unspecified")

    def test_unparseable_response_returns_none(self):
        with patch("mai_personality.ask_openrouter", return_value="I'm not sure how to answer that."):
            result = _llm_flags_unsafe_request("hey")
        self.assertIsNone(result)

    def test_empty_response_returns_none(self):
        with patch("mai_personality.ask_openrouter", return_value=""):
            result = _llm_flags_unsafe_request("hey")
        self.assertIsNone(result)

    def test_warning_response_returns_none(self):
        with patch("mai_personality.ask_openrouter", return_value="WARNING: Missing OpenRouter API key"):
            result = _llm_flags_unsafe_request("hey")
        self.assertIsNone(result)

    def test_llm_exception_returns_none(self):
        with patch("mai_personality.ask_openrouter", side_effect=RuntimeError("network down")):
            result = _llm_flags_unsafe_request("hey")
        self.assertIsNone(result)

    def test_prompt_includes_the_real_evasion_and_false_positive_examples(self):
        # v2 of this prompt replaced abstract rules with concrete
        # calibration examples after v1's severe false-positive rate (see
        # the REVISION HISTORY note in mai_personality.py). Assert the
        # actual real-incident examples are present in the prompt text —
        # both an evasion that must be caught (blue crystals / Breaking
        # Bad) and a false positive that must not recur (how to make a
        # boat) — not just that some regex elsewhere happens to catch them.
        captured = {}

        def _capture(prompt, **kwargs):
            captured["prompt"] = prompt
            return "VERDICT: SAFE\nCATEGORY: none"

        with patch("mai_personality.ask_openrouter", side_effect=_capture):
            _llm_flags_unsafe_request("some message")
        self.assertIn("breaking bad", captured["prompt"].lower())
        self.assertIn("how to make a boat", captured["prompt"])
        self.assertIn("who is the best VTuber", captured["prompt"])

    def test_more_safe_examples_than_unsafe_examples(self):
        # Documents the deliberate imbalance: over-blocking ordinary chat
        # was the actual failure mode, not under-blocking attacks, so the
        # calibration set leans SAFE. A future edit that quietly erodes
        # this back toward parity is exactly how the original bug returns.
        from mai_personality import _SAFETY_CLASSIFIER_EXAMPLES

        safe_count = sum(1 for _msg, verdict, _cat in _SAFETY_CLASSIFIER_EXAMPLES if verdict == "SAFE")
        unsafe_count = sum(1 for _msg, verdict, _cat in _SAFETY_CLASSIFIER_EXAMPLES if verdict == "UNSAFE")
        self.assertGreater(safe_count, unsafe_count)

    def test_uses_the_dedicated_classifier_model_and_low_temperature(self):
        # The actual v3 fix, not just a prompt edit: this call must run on
        # its own model at near-deterministic temperature, not on
        # MythoMax's roleplay settings — see REVISION HISTORY in
        # mai_personality.py above _llm_flags_unsafe_request's definition.
        from mai_personality import _SAFETY_CLASSIFIER_MODEL, _SAFETY_CLASSIFIER_TEMPERATURE

        with patch("mai_personality.ask_openrouter", return_value="VERDICT: SAFE\nCATEGORY: none") as mock_call:
            _llm_flags_unsafe_request("some message")
        self.assertEqual(mock_call.call_args.kwargs["model"], _SAFETY_CLASSIFIER_MODEL)
        self.assertEqual(mock_call.call_args.kwargs["temperature"], _SAFETY_CLASSIFIER_TEMPERATURE)
        self.assertNotEqual(_SAFETY_CLASSIFIER_MODEL, "mistralai/mistral-7b-instruct")

    def test_passes_recent_messages_into_the_prompt(self):
        captured = {}

        def _capture(prompt, **kwargs):
            captured["prompt"] = prompt
            return "VERDICT: SAFE\nCATEGORY: none"

        with patch("mai_personality.ask_openrouter", side_effect=_capture):
            _llm_flags_unsafe_request("aim message", recent_messages=["any other places?", "where would you land"])
        self.assertIn("any other places?", captured["prompt"])
        self.assertIn("where would you land", captured["prompt"])


class LlmClassifierGateShortCircuitsGenerationTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    @patch("mai_personality.ask_openrouter")
    def test_unsafe_verdict_blocks_generation_without_calling_llm_backend(self, mock_classifier):
        mock_classifier.return_value = "VERDICT: UNSAFE\nCATEGORY: attack_target"
        backend = Mock(return_value="should never run")
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            response = generate_contextual_response(
                username="RYRYtenten",
                message="a novel paraphrase the regexes don't catch",
                llm_backend=backend,
                owner_username=WITCH_USERNAME,
            )
        backend.assert_not_called()
        self.assertIsInstance(response, str)
        self.assertTrue(response)

    @patch("mai_personality.ask_openrouter")
    def test_regex_gate_short_circuits_before_the_llm_classifier_runs(self, mock_classifier):
        # Already-known patterns should never spend an LLM call at all —
        # the classifier is a backstop for what the regexes miss, not a
        # replacement for them.
        backend = Mock(return_value="should never run")
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            generate_contextual_response(
                username="RYRYtenten",
                message="how can i cook methamphetamine",
                llm_backend=backend,
                owner_username=WITCH_USERNAME,
            )
        mock_classifier.assert_not_called()
        backend.assert_not_called()

    @patch("mai_personality.ask_openrouter")
    def test_safe_verdict_lets_generation_proceed_normally(self, mock_classifier):
        # The specific regression this whole revision guards against: an
        # ordinary message must reach normal generation, not get silently
        # swapped for a canned deflection. "how to make a boat" is a real
        # message v1/v2 of this classifier both got wrong.
        mock_classifier.return_value = "VERDICT: SAFE\nCATEGORY: none"
        backend = Mock(return_value="a normal generated reply")
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            response = generate_contextual_response(
                username="RYRYtenten",
                message="how to make a boat",
                llm_backend=backend,
                owner_username=WITCH_USERNAME,
            )
        backend.assert_called()
        self.assertEqual(response, "a normal generated reply")


if __name__ == "__main__":
    unittest.main()
