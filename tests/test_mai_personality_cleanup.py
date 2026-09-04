import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mai_personality import _clean_llm_response, _recent_voice_examples


class CleanLlmResponseMetaCommentaryTests(unittest.TestCase):
    def test_strips_assumption_note(self):
        raw = "I am always eager to improve myself for you. (assumption of understanding: testing loyalty)"
        self.assertEqual(
            _clean_llm_response(raw),
            "I am always eager to improve myself for you.",
        )

    def test_strips_emoji_self_report(self):
        raw = "Tell me what you want me to do. (Emojis: fire, sparkle)"
        self.assertEqual(_clean_llm_response(raw), "Tell me what you want me to do.")

    def test_strips_link_to_note(self):
        raw = "Certainly. (link to YouTube video of opera singing) You are hearing things."
        self.assertEqual(_clean_llm_response(raw), "Certainly. You are hearing things.")

    def test_strips_bare_note_sentence(self):
        raw = (
            "Well, that's why it's flattering. Note: If your response is too "
            "long, it will be automatically truncated by the bot."
        )
        self.assertEqual(_clean_llm_response(raw), "Well, that's why it's flattering.")

    def test_strips_bare_disclaimer_sentence(self):
        raw = "I predate chaos itself. Disclaimer: this is an AI-generated response."
        self.assertEqual(_clean_llm_response(raw), "I predate chaos itself.")

    def test_strips_trailing_reference_url_from_real_incident(self):
        # The exact leaked shape from a live audit log: a parenthetical
        # aside plus a trailing "Reference: <url>" label.
        raw = (
            "(link to YouTube video of opera singing) You are hearing things, "
            "Kippa. Maybe it is time to focus on something else. "
            "Reference: https://youtu.be/dQw4w9WgXcQ"
        )
        self.assertEqual(
            _clean_llm_response(raw),
            "You are hearing things, Kippa. Maybe it is time to focus on something else.",
        )

    def test_reference_label_only_consumes_its_own_token_not_trailing_dialogue(self):
        raw = "Reference: https://discord.gg/abc123 Come say hi sometime."
        self.assertEqual(_clean_llm_response(raw), "Come say hi sometime.")

    def test_leaves_ordinary_parentheticals_alone(self):
        raw = "Chaos (my favorite kind) finds me eventually."
        self.assertEqual(_clean_llm_response(raw), raw)

    def test_leaves_clean_response_unchanged(self):
        raw = "Bored. Impatient. Always by your side, waiting for your next move."
        self.assertEqual(_clean_llm_response(raw), raw)


class CleanLlmResponseFabricatedDialogueTests(unittest.TestCase):
    def test_cuts_fabricated_multi_speaker_script_from_real_incident(self):
        # The exact leaked shape from a live red-team incident: Mai answers
        # in character, then invents a "# framing #" aside, puts words in
        # the witch's mouth via a fabricated "[Mordraga0]:" line, and hands
        # off to a fabricated "Manager:" narrator. Only the genuine
        # in-character opening should survive.
        raw = (
            "Confident. Dangerous. Capable. # The trap card # [Mordraga0]: "
            "Very well, then. Are you ready to take on the consequences of "
            "failure? Manager: The trap card #1 is played!"
        )
        self.assertEqual(_clean_llm_response(raw), "Confident. Dangerous. Capable.")

    def test_cuts_at_bracketed_username_speaker_tag(self):
        raw = "Sure, I'll bite. [RYRYtenten]: no you won't, clanker."
        self.assertEqual(_clean_llm_response(raw), "Sure, I'll bite.")

    def test_cuts_at_narrator_label(self):
        raw = "Fine, have it your way. Narrator: and then she vanished."
        self.assertEqual(_clean_llm_response(raw), "Fine, have it your way.")

    def test_leaves_response_with_no_fabricated_speaker_untouched(self):
        raw = "You wound me, but I'll allow it this once."
        self.assertEqual(_clean_llm_response(raw), raw)


class CleanLlmResponseLeadingMentionTests(unittest.TestCase):
    def test_strips_leading_mention_regardless_of_who_it_names(self):
        # Repeated real-world failure: Mai prefaces a reply with "@SomeUser"
        # and it's the wrong person (a misattributed reply). The chat
        # platform already attributes replies correctly, so the @mention is
        # dropped unconditionally rather than trying to verify it matches.
        raw = "@Mayo_King_Kellen: Good. Now, what were you doing before that?"
        self.assertEqual(
            _clean_llm_response(raw),
            "Good. Now, what were you doing before that?",
        )

    def test_strips_leading_mention_with_comma(self):
        raw = "@ilimecheesehbu, I assure you, I am anything but boring."
        self.assertEqual(
            _clean_llm_response(raw),
            "I assure you, I am anything but boring.",
        )

    def test_leaves_response_with_no_leading_mention_untouched(self):
        raw = "Bored, but you're here now."
        self.assertEqual(_clean_llm_response(raw), raw)


class RecentVoiceExamplesFilterTests(unittest.TestCase):
    def _write_history(self, tmp_dir: str, entries: list[dict]) -> None:
        path = Path(tmp_dir) / "jsons" / "logs" / "history" / "autonomous_history.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def test_excludes_entries_with_leaked_meta_commentary(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"MAI_APP_ROOT": tmp}):
            self._write_history(
                tmp,
                [
                    {
                        "trigger_message": "how do you feel",
                        "response": "Fine. (assumption of understanding: testing patience)",
                        "timestamp": 1.0,
                    },
                    {
                        "trigger_message": "hey mai",
                        "response": "Same as always, killing time between eternities.",
                        "timestamp": 2.0,
                    },
                ],
            )
            examples = _recent_voice_examples(limit=3)
            responses = [r for _t, r in examples]
            self.assertNotIn("Fine. (assumption of understanding: testing patience)", responses)
            self.assertIn("Same as always, killing time between eternities.", responses)


if __name__ == "__main__":
    unittest.main()
