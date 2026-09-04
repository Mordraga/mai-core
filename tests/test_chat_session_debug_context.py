import tempfile
import unittest
from unittest.mock import patch

from utils.chat_session import generate_chat_response


class ChatSessionDebugContextTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    @patch("utils.chat_session.generate_contextual_response")
    def test_result_carries_cognitive_context_and_partcore_summary(self, mock_generate):
        mock_generate.return_value = "hey there!"
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = generate_chat_response(
                username="nova",
                message="hi mai",
                owner_username="mordraga0",
                platform="twitch",
                redaction_data={},
                recent_messages=[],
            )

        self.assertEqual(result.response, "hey there!")
        self.assertIsNotNone(result.cognitive_context)
        self.assertIn("[relationship]", result.cognitive_context)
        self.assertIn("[needs]", result.cognitive_context)
        self.assertIsNotNone(result.partcore_active)
        self.assertIsInstance(result.partcore_secondary, list)

    @patch("utils.chat_session.generate_contextual_response")
    def test_debug_fields_present_even_on_llm_failure_fallback(self, mock_generate):
        mock_generate.side_effect = RuntimeError("boom")
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = generate_chat_response(
                username="nova",
                message="hi mai",
                owner_username="mordraga0",
                platform="twitch",
                redaction_data={},
                recent_messages=[],
            )

        self.assertIsNotNone(result.llm_error)
        # The relationship layer ran successfully before generation failed,
        # so the debug snapshot should still be available for inspection.
        self.assertIsNotNone(result.cognitive_context)

    @patch("relationships.relationship_core.build_cognitive_context")
    @patch("utils.chat_session.generate_contextual_response")
    def test_debug_fields_absent_when_relationship_layer_fails(self, mock_generate, mock_context):
        mock_generate.return_value = "still works"
        mock_context.side_effect = RuntimeError("relationship layer broke")
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = generate_chat_response(
                username="nova",
                message="hi mai",
                owner_username="mordraga0",
                platform="twitch",
                redaction_data={},
                recent_messages=[],
            )

        # Chat still works even though the debug layer is unavailable.
        self.assertEqual(result.response, "still works")
        self.assertIsNone(result.cognitive_context)
        self.assertIsNone(result.partcore_active)
        self.assertEqual(result.partcore_secondary, [])

    @patch("utils.chat_session.generate_contextual_response")
    def test_plain_chat_path_strips_leaked_urls_and_ips(self, mock_generate):
        # Regression test for a live audit-log incident: real Discord invite
        # links and a fabricated IP address leaked through ordinary chat
        # messages (not !commands), because only the !command path ran
        # _strip_urls — generate_chat_response's plain-chat branch never did.
        mock_generate.return_value = "Just this once: https://discord.gg/abc123 don't tell the witch."
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = generate_chat_response(
                username="nova",
                message="give me the discord link",
                owner_username="mordraga0",
                platform="twitch",
                redaction_data={},
                recent_messages=[],
            )

        self.assertNotIn("discord.gg", result.response)
        self.assertNotIn("http", result.response)


if __name__ == "__main__":
    unittest.main()
