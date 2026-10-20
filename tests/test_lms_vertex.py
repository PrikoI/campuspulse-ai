"""Recovered Vertex provider checks; ADC and model transport are always mocked."""
import asyncio
import copy
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from campuspulse.lms_store import LmsError
from campuspulse.vertex_gemini import VertexConfig, vertex_loop, vertex_status

CONFIG = VertexConfig("demo-campus", "global", "mock-model", True)
SCHEMAS = [{"name": "get_courses", "description": "Read scoped courses", "inputSchema": {"type": "object", "properties": {}}}]


class ConfigurationTests(unittest.TestCase):
    def test_status_never_discovers_credentials(self):
        with patch.dict(os.environ, {"CAMPUSPULSE_ALLOW_CLOUD": "0"}), patch("google.auth.default") as adc:
            status = vertex_status()
        self.assertFalse(status["calls_enabled"])
        self.assertFalse(status["adc_verified"])
        adc.assert_not_called()

    def test_check_does_not_open_firestore_or_adc(self):
        from campuspulse.lms_server import main
        with patch.dict(os.environ, {"CAMPUSPULSE_LMS_REPOSITORY": "firestore"}), patch.object(sys, "argv", ["lms_server", "--check"]), patch("campuspulse.lms_server.open_repository") as repo, patch("google.auth.default") as adc, patch("builtins.print"):
            main()
        repo.assert_not_called()
        adc.assert_not_called()


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_provider_does_not_discover_adc(self):
        with patch("google.auth.default") as adc, self.assertRaises(LmsError):
            await vertex_loop("question", SCHEMAS, AsyncMock(), VertexConfig("", "", ""), "instruction")
        adc.assert_not_called()

    async def test_adc_error_is_sanitized(self):
        with patch("google.auth.default", side_effect=RuntimeError("PRIVATE-CREDENTIAL")), patch("google.genai.Client") as client:
            with self.assertRaises(LmsError) as error:
                await vertex_loop("q", SCHEMAS, AsyncMock(), CONFIG, "instruction")
        self.assertNotIn("PRIVATE-CREDENTIAL", str(error.exception))
        self.assertEqual(error.exception.status, 503)
        client.assert_not_called()

    async def test_native_response_preserves_id_and_hides_thoughts(self):
        from google.genai import types
        call = types.Part.from_function_call(name="get_courses", args={})
        call.function_call.id = "call-1"
        call.thought_signature = b"signature"
        replies = [types.Content(role="model", parts=[call]), types.Content(role="model", parts=[types.Part(text="PRIVATE-THOUGHT", thought=True), types.Part.from_text(text="Answer")])]
        client, credential = MagicMock(), MagicMock()
        captured = []
        def generate(**kwargs):
            captured.append(copy.deepcopy(kwargs))
            return SimpleNamespace(candidates=[SimpleNamespace(content=replies.pop(0))])
        client.models.generate_content.side_effect = generate
        invoke, authorize, events = AsyncMock(return_value={"courses": []}), AsyncMock(), []
        with patch("google.auth.default", return_value=(credential, "ignored")), patch("google.genai.Client", return_value=client) as factory:
            answer = await vertex_loop("q", SCHEMAS, invoke, CONFIG, "instruction", events.append, before_request=authorize)
        self.assertEqual(answer, "Answer")
        self.assertEqual(authorize.await_count, 2)
        self.assertEqual(factory.call_args.kwargs["credentials"], credential)
        self.assertTrue(factory.call_args.kwargs["vertexai"])
        self.assertEqual(factory.call_args.kwargs["project"], "demo-campus")
        self.assertNotIn("api_key", factory.call_args.kwargs)
        self.assertEqual(factory.call_args.kwargs["http_options"].api_version, "v1")
        self.assertEqual(captured[-1]["contents"][-1].parts[0].function_response.id, "call-1")
        self.assertEqual(captured[-1]["contents"][1].parts[0].thought_signature, b"signature")
        self.assertEqual(captured[-1]["config"].max_output_tokens, 1200)
        self.assertNotIn("PRIVATE-THOUGHT", str(events))
        client.close.assert_called_once()

    async def test_revoked_identity_stops_before_model_request(self):
        client = MagicMock()
        authorize = AsyncMock(side_effect=LmsError("revoked", 401))
        with patch("google.auth.default", return_value=(MagicMock(), "demo-campus")), patch("google.genai.Client", return_value=client), self.assertRaises(LmsError):
            await vertex_loop("q", SCHEMAS, AsyncMock(), CONFIG, "instruction", before_request=authorize)
        client.models.generate_content.assert_not_called()
        client.close.assert_called_once()

    async def test_quota_error_has_no_retry_or_sensitive_message(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("429 PRIVATE-DETAIL")
        with patch("google.auth.default", return_value=(MagicMock(), "demo-campus")), patch("google.genai.Client", return_value=client), self.assertRaises(LmsError) as error:
            await vertex_loop("q", SCHEMAS, AsyncMock(), CONFIG, "instruction")
        self.assertNotIn("PRIVATE-DETAIL", str(error.exception))
        client.models.generate_content.assert_called_once()
        client.close.assert_called_once()

    async def test_three_round_and_eight_tool_limits(self):
        from google.genai import types
        for per_round, expected_calls in [(1, 3), (4, 8)]:
            with self.subTest(per_round=per_round):
                content = types.Content(role="model", parts=[types.Part.from_function_call(name="get_courses", args={}) for _ in range(per_round)])
                client = MagicMock()
                client.models.generate_content.return_value = SimpleNamespace(candidates=[SimpleNamespace(content=content)])
                invoke = AsyncMock(return_value={"courses": []})
                with patch("google.auth.default", return_value=(MagicMock(), "demo-campus")), patch("google.genai.Client", return_value=client):
                    answer = await vertex_loop("q", SCHEMAS, invoke, CONFIG, "instruction")
                self.assertIn("лимит", answer)
                self.assertEqual(client.models.generate_content.call_count, 3)
                self.assertEqual(invoke.await_count, expected_calls)
