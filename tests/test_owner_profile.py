import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mai_personality import _owner_profile, _owner_profile_instruction, generate_contextual_response


class OwnerProfileTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def _write_profile(self, tmp: str, data: dict) -> None:
        path = Path(tmp) / "jsons" / "data" / "owner_profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_all_fields_blank_when_no_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            profile = _owner_profile()
        self.assertTrue(profile)  # all known fields present as keys
        self.assertFalse(any(profile.values()))  # all blank

    def test_instruction_empty_when_no_profile_data(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self.assertEqual(_owner_profile_instruction("mordraga0"), "")

    def test_loads_full_profile_from_dedicated_file(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {
                "username": "mordraga0",
                "name": "Draga",
                "pronouns": "she/her",
                "role_identity": "Streamer and developer",
                "content_focus": "Building Mai on stream",
                "community_name": "The Crypt",
                "community_vibe": "Chaotic, sharp-witted",
                "notable_lore": "The three-strike rule",
                "boundaries": "Nothing about the meth incident",
                "context_lore": "18+ stream",
            })
            profile = _owner_profile()
        self.assertEqual(profile["name"], "Draga")
        self.assertEqual(profile["community_name"], "The Crypt")

    def test_instruction_includes_all_populated_fields(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {
                "username": "mordraga0",
                "community_name": "The Crypt",
                "boundaries": "Nothing about the meth incident",
                "misc_facts": "Height is 5'6\"",
            })
            instruction = _owner_profile_instruction("mordraga0")
        self.assertIn("The Crypt", instruction)
        self.assertIn("Nothing about the meth incident", instruction)
        self.assertIn("mordraga0", instruction)
        self.assertIn("Height is 5'6\"", instruction)

    def test_misc_facts_instruction_says_to_answer_accurately_not_deflect(self):
        # The whole point of this field: unlike the persona's default
        # cryptic/mystery framing for most topics, these specific facts
        # should be stated plainly when chat asks — that has to be an
        # explicit instruction or the model will reflexively deflect.
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {"misc_facts": "Height is 5'6\""})
            instruction = _owner_profile_instruction("mordraga0")
        self.assertIn("answer accurately", instruction)
        self.assertIn("rather than being cryptic or deflecting", instruction)

    def test_missing_fields_render_as_placeholders_not_blank(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {"username": "mordraga0"})
            instruction = _owner_profile_instruction("mordraga0")
        self.assertIn("unspecified", instruction)
        self.assertNotIn(": \n", instruction)

    def test_falls_back_to_passed_username_when_profile_has_none(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {"role_identity": "Streamer"})
            instruction = _owner_profile_instruction("mordraga0")
        self.assertIn("Username: mordraga0", instruction)

    def test_non_dict_file_falls_back_to_all_blank(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, ["not", "a", "dict"])
            profile = _owner_profile()
        self.assertFalse(any(profile.values()))


class ThirdPartyCanAskAboutTheOwnerTests(unittest.TestCase):
    """The exact scenario this whole mechanism exists for: someone who
    ISN'T the owner asks Mai something about her. Regression coverage for
    a real gap — misc_facts (and the rest of the profile) originally only
    reached the prompt inside mordraga_chat, i.e. only when the owner
    herself was speaking, so a chatter's question about her never saw it
    at all."""

    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def _write_profile(self, tmp: str, data: dict) -> None:
        path = Path(tmp) / "jsons" / "data" / "owner_profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_non_owner_speaker_still_gets_owner_profile_in_system_prompt(self):
        captured = {}

        def _capture_backend(user_message, system_prompt=None, spicy=False):
            captured["system_prompt"] = system_prompt
            return "some in-character answer"

        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {"misc_facts": "34 DD, 5'10, 200 lbs"})
            generate_contextual_response(
                username="susbean189",
                message="what is mordraga's cup size?",
                llm_backend=_capture_backend,
                owner_username="mordraga0",
            )
        self.assertIn("34 DD, 5'10, 200 lbs", captured["system_prompt"])

    def test_owner_speaker_also_still_gets_owner_profile(self):
        # Guard against the fix accidentally dropping it for mordraga_chat
        # while adding it elsewhere.
        captured = {}

        def _capture_backend(user_message, system_prompt=None, spicy=False):
            captured["system_prompt"] = system_prompt
            return "some in-character answer"

        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self._write_profile(tmp, {"misc_facts": "34 DD, 5'10, 200 lbs"})
            generate_contextual_response(
                username="mordraga0",
                message="what's my cup size again?",
                llm_backend=_capture_backend,
                owner_username="mordraga0",
            )
        self.assertIn("34 DD, 5'10, 200 lbs", captured["system_prompt"])


if __name__ == "__main__":
    unittest.main()
