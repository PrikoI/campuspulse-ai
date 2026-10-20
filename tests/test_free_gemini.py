import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from campuspulse.agent import run_query
from campuspulse.free_gemini import Connections, ConnectionError, DeveloperConnection, FREE_MODEL, verify_unbilled_key

KEY = "test_key_is_never_a_real_secret_123456"


class BillingTests(unittest.TestCase):
    def responses(self, lookup=None, billing=None, status=200):
        client = MagicMock()
        client.get.side_effect = [SimpleNamespace(status_code=status, json=lambda: lookup or {"parent": "projects/123/locations/global", "name": "projects/123/locations/global/keys/test"}),
                                  SimpleNamespace(status_code=200, json=lambda: billing if billing is not None else {"billingEnabled": False})]
        manager = MagicMock(); manager.__enter__.return_value = client
        return client, manager

    def test_key_project_is_resolved_and_billing_must_be_false(self):
        client, manager = self.responses()
        with patch("google.auth.default", return_value=(object(), None)), patch("google.auth.transport.requests.AuthorizedSession", return_value=manager):
            self.assertEqual(verify_unbilled_key(KEY), "123")
        self.assertEqual(client.get.call_args_list[0].kwargs["params"], {"keyString": KEY})
        self.assertEqual(client.get.call_args_list[1].args[0], "https://cloudbilling.googleapis.com/v1/projects/123/billingInfo")
        for call in client.get.call_args_list:
            self.assertFalse(call.kwargs["allow_redirects"])

    def test_enabled_unknown_or_unavailable_billing_blocks(self):
        for billing in [{"billingEnabled": True}, {}, {"billingEnabled": "false"}]:
            _, manager = self.responses(billing=billing)
            with patch("google.auth.default", return_value=(object(), None)), patch("google.auth.transport.requests.AuthorizedSession", return_value=manager), self.assertRaises(ConnectionError):
                verify_unbilled_key(KEY)
        client, manager = self.responses(status=403)
        with patch("google.auth.default", return_value=(object(), None)), patch("google.auth.transport.requests.AuthorizedSession", return_value=manager), self.assertRaises(ConnectionError):
            verify_unbilled_key(KEY)
        self.assertEqual(client.get.call_count, 1)

    def test_remote_exception_does_not_leak_key(self):
        with patch("google.auth.default", side_effect=RuntimeError(f"secret URL {KEY}")):
            with self.assertRaises(ConnectionError) as error:
                verify_unbilled_key(KEY)
        self.assertNotIn(KEY, str(error.exception))

    def test_auth_key_format_and_control_character_rejection(self):
        connections = Connections(); token, _ = connections.session(None)
        auth_key = "AQ.Ab_" + "example_" * 60 + ".test"
        with patch("campuspulse.free_gemini.verify_unbilled_key", return_value="123"):
            self.assertEqual(connections.connect(token, auth_key).api_key, auth_key)
        for bad in ["short", "a" * 20 + "\r\nInjected: value", "a" * 4097]:
            with self.assertRaises(ConnectionError):
                connections.connect(token, bad)

    def test_sessions_are_isolated_and_disconnect_forgets_key(self):
        connections = Connections()
        one, _ = connections.session(None); two, _ = connections.session(None)
        with patch("campuspulse.free_gemini.verify_unbilled_key", return_value="123"):
            connection = connections.connect(one, KEY)
        self.assertNotIn(KEY, repr(connection))
        self.assertIs(connections.get(one), connection)
        self.assertIsNone(connections.get(two))
        connections.disconnect(one)
        self.assertIsNone(connections.get(one))


class DeveloperTests(unittest.IsolatedAsyncioTestCase):
    async def test_billing_failure_blocks_before_client_creation(self):
        with patch("campuspulse.free_gemini.verify_unbilled_key", side_effect=ConnectionError("Billing blocked")), patch("google.genai.Client") as client:
            with self.assertRaises(ConnectionError):
                await run_query("План", {}, {"mode": "developer", "transport": "direct", "model": FREE_MODEL,
                                            "connection": DeveloperConnection(KEY, "123")})
        client.assert_not_called()

    async def test_developer_model_calls_real_mcp_and_preserves_function_id(self):
        from google.genai import types
        calls = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="list_assignments", args={}, id="c1")),
                                                   types.Part(function_call=types.FunctionCall(name="plan_week", args={}, id="c2"))])
        final = types.Content(role="model", parts=[types.Part.from_text(text="План готов.")])
        model = MagicMock(); model.models.generate_content.side_effect = [SimpleNamespace(candidates=[SimpleNamespace(content=c)]) for c in [calls, final]]
        manager = MagicMock(); manager.__enter__.return_value = model
        with patch("campuspulse.free_gemini.verify_unbilled_key", return_value="123") as billing, patch("google.genai.Client", return_value=manager) as client:
            result = await run_query("План", {}, {"mode": "developer", "transport": "mcp", "model": FREE_MODEL,
                                                "connection": DeveloperConnection(KEY, "123")})
        self.assertFalse(client.call_args.kwargs["vertexai"])
        self.assertEqual(client.call_args.kwargs["api_key"], KEY)
        self.assertEqual(billing.call_count, 2)
        self.assertEqual(result["provider"], "gemini-developer-api")
        self.assertEqual([item["tool"] for item in result["trace"]], ["list_assignments", "plan_week"])
        self.assertEqual(model.models.generate_content.call_args.kwargs["contents"][2].parts[1].function_response.id, "c2")
        self.assertNotIn(KEY, str(result))

    async def test_quota_error_never_falls_back_or_leaks_remote_error(self):
        model = MagicMock()
        error = RuntimeError(KEY); error.code = 429
        model.models.generate_content.side_effect = error
        manager = MagicMock(); manager.__enter__.return_value = model
        with patch("campuspulse.free_gemini.verify_unbilled_key", return_value="123"), patch("google.genai.Client", return_value=manager):
            with self.assertRaises(ConnectionError) as caught:
                await run_query("План", {}, {"mode": "developer", "transport": "direct", "model": FREE_MODEL,
                                            "connection": DeveloperConnection(KEY, "123")})
        self.assertIn("бесплатного", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(model.models.generate_content.call_count, 1)


if __name__ == "__main__":
    unittest.main()
