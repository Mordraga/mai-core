import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import SAFETY_GUARDRAILS, build_prompt_from_keyword
from mai_personality import build_contextual_prompt


class SafetyGuardrailsReachBothPromptPathsTests(unittest.TestCase):
    """The safety-guardrail block (no fabricated dialogue, no prompt-injection
    compliance, no leaking internals, no real harmful instructions) is fixed
    in code, not personality data, so it has to reach every prompt build
    regardless of which personality YAML is loaded or missing. These tests
    guard against a future refactor silently dropping it from one path."""

    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_present_in_chat_prompt_even_with_no_personality_data(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            system, _user = build_contextual_prompt(
                username="nova",
                message="hi",
                context="general",
            )
        self.assertIn(SAFETY_GUARDRAILS, system)

    def test_present_in_command_prompt_even_with_no_personality_data(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            config_path = Path(tmp) / "jsons" / "configs" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({}), encoding="utf-8")
            prompt = build_prompt_from_keyword(
                "greet",
                context={"name": "nova"},
                registry={},
                templates={"greet": "Say hi to {name}."},
            )
        self.assertIn(SAFETY_GUARDRAILS, prompt)


if __name__ == "__main__":
    unittest.main()
