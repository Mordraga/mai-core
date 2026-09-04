import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine import ask_openrouter


class AskOpenrouterOverrideTests(unittest.TestCase):
    """model/temperature overrides exist so a caller (like the safety
    classifier in mai_personality.py) can run on a different model than
    the one configured for Mai's own voice, without touching every other
    ask_openrouter caller's behavior."""

    def _isolated_root(self, tmp):
        config_path = Path(tmp) / "jsons" / "configs" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"Mai-config": {"model": "default/model", "temperature_normal": 0.85}}),
            encoding="utf-8",
        )
        keys_path = Path(tmp) / "jsons" / "configs" / "keys.json"
        keys_path.write_text(json.dumps({"openrouter_api_key": "test-key"}), encoding="utf-8")
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def _mock_response(self, content="ok"):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        return mock_resp

    def test_model_override_used_instead_of_configured_default(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            with patch("engine.requests.post", return_value=self._mock_response()) as mock_post:
                ask_openrouter("hi", model="anthropic/claude-3.5-haiku")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "anthropic/claude-3.5-haiku")

    def test_no_model_override_uses_configured_default(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            with patch("engine.requests.post", return_value=self._mock_response()) as mock_post:
                ask_openrouter("hi")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "default/model")

    def test_temperature_override_used_instead_of_configured_default(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            with patch("engine.requests.post", return_value=self._mock_response()) as mock_post:
                ask_openrouter("hi", temperature=0.1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.1)

    def test_no_temperature_override_uses_configured_default(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            with patch("engine.requests.post", return_value=self._mock_response()) as mock_post:
                ask_openrouter("hi")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.85)


if __name__ == "__main__":
    unittest.main()
