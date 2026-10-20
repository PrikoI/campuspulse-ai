"""Gemini Interactions provider tests; SDK transport is always mocked."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai._interactions.types import FunctionCallContent, TextContent

from campuspulse.gemini_interactions import GeminiConfig, gemini_loop, gemini_status
from campuspulse.llm_provider import llm_status, model_provider, provider_name
from campuspulse.lms_store import LmsError


CONFIG = GeminiConfig("private-test-key", "gemini-3.8-flash", True)
SCHEMAS = [{"name": "get_courses", "description": "Read scoped courses",
            "inputSchema": {"type": "object", "properties": {}, "required": []}}]


class ConfigurationTests(unittest.TestCase):
    def test_key_is_server_only_and_calls_require_explicit_enablement(self):
        with patch.dict(os.environ, {"CAMPUSPULSE_GEMINI_API_KEY": "private-test-key",
                                     "CAMPUSPULSE_GEMINI_MODEL": "gemini-3.8-flash",
                                     "CAMPUSPULSE_GEMINI_ENABLED": "0"}):
            config = GeminiConfig.from_environment()
            status = gemini_status()
        self.assertTrue(config.configured)
        self.assertFalse(status["calls_enabled"])
        self.assertNotIn("private-test-key", repr(config) + str(status))
        with self.assertRaises(LmsError):
            config.require_enabled()

    def test_provider_selection_and_status_use_gemini(self):
        env = {"CAMPUSPULSE_LLM_PROVIDER": "gemini", "CAMPUSPULSE_GEMINI_API_KEY": "private-test-key",
               "CAMPUSPULSE_GEMINI_ENABLED": "1"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(provider_name(), "gemini")
            self.assertEqual(model_provider()[0], "gemini-api")
            status = llm_status()
        self.assertTrue(status["calls_enabled"])
        self.assertEqual(status["provider"], "gemini-api")
        self.assertNotIn("private-test-key", str(status))


class InteractionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_interactions_tool_round_trip_is_stateless_and_preserves_history(self):
        call = FunctionCallContent(type="function_call", name="get_courses", id="call-1",
                                   arguments={"course_id": "course-1"}, signature="signature")
        answer = TextContent(type="text", text="Your course is Physics")
        client = MagicMock()
        client.interactions.create.side_effect = [
            SimpleNamespace(status="requires_action", outputs=[call]),
            SimpleNamespace(status="completed", outputs=[answer]),
        ]
        invoke, authorize = AsyncMock(return_value={"courses": [{"name": "Physics"}]}), AsyncMock()
        with patch("google.genai.Client", return_value=client) as factory:
            result = await gemini_loop(
                "Show my courses", SCHEMAS, invoke, CONFIG, "System instructions",
                before_request=authorize,
                history=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
            )

        self.assertEqual(result, "Your course is Physics")
        factory.assert_called_once_with(api_key="private-test-key")
        self.assertEqual(authorize.await_count, 2)
        self.assertEqual(client.interactions.create.call_count, 2)
        first, second = [item.kwargs for item in client.interactions.create.call_args_list]
        self.assertEqual(first["model"], "gemini-3.8-flash")
        self.assertEqual(first["input"][:2], [
            {"role": "user", "content": "Hi"}, {"role": "model", "content": "Hello"}])
        self.assertFalse(first["store"])
        self.assertEqual(first["timeout"], 45)
        self.assertEqual(first["tools"][0]["type"], "function")
        self.assertEqual(second["input"][-1]["content"][0]["call_id"], "call-1")
        self.assertEqual(second["input"][-1]["content"][0]["signature"], "signature")
        self.assertEqual(second["input"][-1]["content"][0]["result"], '{"courses": [{"name": "Physics"}]}')
        invoke.assert_awaited_once_with("get_courses", {"course_id": "course-1"})
        client.close.assert_called_once()

    async def test_disabled_and_failed_requests_never_leak_key(self):
        client = MagicMock()
        with patch("google.genai.Client", return_value=client) as factory:
            with self.assertRaises(LmsError):
                await gemini_loop("hello", [], AsyncMock(), GeminiConfig("private-test-key"), "instruction")
        factory.assert_not_called()

        client.interactions.create.side_effect = RuntimeError("private-test-key")
        with patch("google.genai.Client", return_value=client), self.assertRaises(LmsError) as error:
            await gemini_loop("hello", [], AsyncMock(), CONFIG, "instruction")
        self.assertNotIn("private-test-key", str(error.exception))
        self.assertEqual(error.exception.status, 503)
        client.close.assert_called_once()

    async def test_unknown_tools_are_never_invoked(self):
        call = FunctionCallContent(type="function_call", name="delete_database", id="call-1", arguments={})
        client = MagicMock()
        client.interactions.create.return_value = SimpleNamespace(status="requires_action", outputs=[call])
        invoke = AsyncMock()
        with patch("google.genai.Client", return_value=client), self.assertRaises(LmsError):
            await gemini_loop("q", SCHEMAS, invoke, CONFIG, "instruction")
        invoke.assert_not_awaited()
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
