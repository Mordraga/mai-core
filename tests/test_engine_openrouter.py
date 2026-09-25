import unittest
from unittest.mock import patch

import engine


class _Resp:
    def __init__(self, status_code, json_data=None, text="", headers=None, reason=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {}
        self.reason = reason

    def json(self):
        return self._json_data


def _cfg(**overrides):
    mai_config = {
        "backend": "openrouter",
        "model": "some/model",
        "max_tokens": 60,
        "temperature_normal": 0.85,
        "temperature_spicy": 0.95,
        "timeout": 30,
    }
    mai_config.update(overrides)
    return {"Mai-config": mai_config}


class AskOpenRouterTests(unittest.TestCase):
    def test_missing_api_key_returns_warning_without_network_call(self):
        with patch.object(engine, "load_config", return_value=_cfg()):
            with patch.object(engine, "load_keys", return_value={}):
                with patch.object(engine.requests, "post") as post:
                    result = engine.ask_openrouter("hi")
        self.assertTrue(result.startswith("WARNING:"))
        post.assert_not_called()

    def test_successful_response_returns_content(self):
        resp = _Resp(200, {"choices": [{"message": {"content": "hello there"}}]})
        with patch.object(engine, "load_config", return_value=_cfg()):
            with patch.object(engine, "load_keys", return_value={"openrouter_api_key": "sk-or-test"}):
                with patch.object(engine.requests, "post", return_value=resp):
                    result = engine.ask_openrouter("hi")
        self.assertEqual(result, "hello there")

    def test_429_is_retried_then_succeeds(self):
        responses = [
            _Resp(429, headers={}, reason="Too Many Requests"),
            _Resp(200, {"choices": [{"message": {"content": "back online"}}]}),
        ]
        with patch.object(engine, "load_config", return_value=_cfg(rate_limit_retries=2)):
            with patch.object(engine, "load_keys", return_value={"openrouter_api_key": "sk-or-test"}):
                with patch.object(engine.requests, "post", side_effect=responses):
                    with patch.object(engine.time, "sleep") as sleep_mock:
                        result = engine.ask_openrouter("hi")
        self.assertEqual(result, "back online")
        sleep_mock.assert_called_once()

    def test_429_exhausts_retries_and_returns_warning(self):
        responses = [_Resp(429, headers={}, reason="Too Many Requests") for _ in range(3)]
        with patch.object(engine, "load_config", return_value=_cfg(rate_limit_retries=2)):
            with patch.object(engine, "load_keys", return_value={"openrouter_api_key": "sk-or-test"}):
                with patch.object(engine.requests, "post", side_effect=responses):
                    with patch.object(engine.time, "sleep") as sleep_mock:
                        result = engine.ask_openrouter("hi")
        self.assertTrue(result.startswith("WARNING:"))
        self.assertIn("429", result)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_429_honors_retry_after_header(self):
        responses = [
            _Resp(429, headers={"Retry-After": "7"}, reason="Too Many Requests"),
            _Resp(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        with patch.object(engine, "load_config", return_value=_cfg(rate_limit_retries=2)):
            with patch.object(engine, "load_keys", return_value={"openrouter_api_key": "sk-or-test"}):
                with patch.object(engine.requests, "post", side_effect=responses):
                    with patch.object(engine.time, "sleep") as sleep_mock:
                        engine.ask_openrouter("hi")
        sleep_mock.assert_called_once_with(7.0)

    def test_non_429_error_is_not_retried(self):
        resp = _Resp(404, {"error": {"message": "model not found"}}, reason="Not Found")
        with patch.object(engine, "load_config", return_value=_cfg()):
            with patch.object(engine, "load_keys", return_value={"openrouter_api_key": "sk-or-test"}):
                with patch.object(engine.requests, "post", return_value=resp) as post:
                    with patch.object(engine.time, "sleep") as sleep_mock:
                        result = engine.ask_openrouter("hi")
        self.assertTrue(result.startswith("WARNING:"))
        self.assertIn("model not found", result)
        post.assert_called_once()
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
