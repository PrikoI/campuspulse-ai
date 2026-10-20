<<<<<<< HEAD
"""Alem transport, function calling and LMS boundary, without live services."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import requests

from campuspulse.alem_llm import AlemConfig, ENDPOINT, alem_loop, completion
from campuspulse.llm_provider import llm_status, provider_name
from campuspulse.lms_store import LmsError

CONFIG = AlemConfig("private-test-key", enabled=True)
SCHEMAS = [{"name": "get_courses", "description": "Scoped courses", "inputSchema": {"type": "object", "properties": {}, "required": []}}]


def tool(name="get_courses", arguments="{}"):
    return {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}]}


class ConfigurationTests(unittest.TestCase):
    def test_local_profile_and_env_override_do_not_expose_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alem.json"
            path.write_text(json.dumps({"api_key": "private-test-key", "enabled": True}), encoding="utf-8")
            with patch("campuspulse.alem_llm.ENV_FILE", Path(tmp) / ".env"), patch("campuspulse.alem_llm.LOCAL_CONFIG", path), patch("campuspulse.llm_provider.LOCAL_CONFIG", path), patch.dict(os.environ, {"CAMPUSPULSE_LLM_PROVIDER": "alem", "CAMPUSPULSE_ALEM_ENABLED": "1"}):
                config, status = AlemConfig.from_environment(), llm_status()
                self.assertTrue(config.configured)
                self.assertTrue(status["calls_enabled"])
                self.assertNotIn("private-test-key", str(status) + repr(config))
                with patch.dict(os.environ, {"CAMPUSPULSE_ALEM_ENABLED": "0"}):
                    self.assertFalse(AlemConfig.from_environment().enabled)
                with patch.dict(os.environ, {"CAMPUSPULSE_LLM_PROVIDER": "vertex"}):
                    self.assertEqual(provider_name(), "vertex")

    def test_dotenv_loads_literal_secret_and_environment_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('CAMPUSPULSE_LLM_PROVIDER=alem\nCAMPUSPULSE_ALEM_API_KEY="synthetic-$literal"\nCAMPUSPULSE_ALEM_MODEL=gemma4\nCAMPUSPULSE_ALEM_ENABLED=1\nOTHER_SECRET=ignored\n', encoding="utf-8")
            with patch("campuspulse.alem_llm.ENV_FILE", path), patch("campuspulse.alem_llm.local_config", return_value={}), patch.dict(os.environ):
                for key in ["CAMPUSPULSE_LLM_PROVIDER", "CAMPUSPULSE_ALEM_API_KEY", "CAMPUSPULSE_ALEM_MODEL", "CAMPUSPULSE_ALEM_ENABLED"]:
                    os.environ.pop(key, None)
                config = AlemConfig.from_environment()
                self.assertEqual(config.api_key, "synthetic-$literal")
                self.assertTrue(config.enabled)
                self.assertEqual(provider_name(), "alem")
                self.assertNotIn("OTHER_SECRET", os.environ)
                with patch.dict(os.environ, {"CAMPUSPULSE_ALEM_API_KEY": "process-value", "CAMPUSPULSE_ALEM_ENABLED": "0"}):
                    self.assertEqual(AlemConfig.from_environment().api_key, "process-value")
                    self.assertFalse(AlemConfig.from_environment().enabled)

    def test_disabled_provider_makes_no_request(self):
        with patch("requests.post") as post, self.assertRaises(LmsError):
            completion(AlemConfig("x"), [])
        post.assert_not_called()

    def test_transport_uses_fixed_endpoint_no_redirects_and_bounded_timeout(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "Hi"}}]}
        with patch("requests.post") as post:
            post.return_value.__enter__.return_value = response
            self.assertEqual(completion(CONFIG, [{"role": "user", "content": "Hi"}])["content"], "Hi")
        args = post.call_args
        self.assertEqual(args.args, (ENDPOINT,))
        self.assertFalse(args.kwargs["allow_redirects"])
        self.assertEqual(args.kwargs["timeout"], (10, 45))
        self.assertEqual(args.kwargs["json"]["max_tokens"], 1200)
        self.assertNotIn("private-test-key", json.dumps(args.kwargs["json"]))

    def test_errors_are_sanitized_and_not_retried(self):
        for status in [401, 403, 429, 500, 302]:
            with self.subTest(status=status), patch("requests.post") as post:
                response = MagicMock(status_code=status)
                post.return_value.__enter__.return_value = response
                with self.assertRaises(LmsError) as error:
                    completion(CONFIG, [])
                self.assertEqual(error.exception.status, 503)
                response.json.assert_not_called()
                post.assert_called_once()
        with patch("requests.post", side_effect=requests.Timeout("private-test-key")), self.assertRaises(LmsError) as error:
            completion(CONFIG, [])
        self.assertNotIn("private-test-key", str(error.exception))


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_tool_round_trip_preserves_id_and_hides_reasoning(self):
        captured = []
        replies = [dict(tool(), reasoning_content="PRIVATE-THOUGHT"), {"content": "Answer", "reasoning_content": "PRIVATE-THOUGHT"}]
        def complete(config, messages, tools):
            captured.append(copy.deepcopy(messages))
            return replies.pop(0)
        invoke, authorize, events = AsyncMock(return_value={"courses": []}), AsyncMock(), []
        with patch("campuspulse.alem_llm.completion", side_effect=complete):
            answer = await alem_loop("q", SCHEMAS, invoke, CONFIG, "instruction", events.append, before_request=authorize)
        self.assertEqual(answer, "Answer")
        self.assertEqual(authorize.await_count, 2)
        self.assertEqual(captured[-1][-1], {"role": "tool", "tool_call_id": "call_1", "content": '{"courses": []}'})
        self.assertNotIn("PRIVATE-THOUGHT", str(captured) + str(events))
        invoke.assert_awaited_once_with("get_courses", {})

    async def test_unknown_or_malformed_tools_are_never_executed(self):
        for response in [tool("delete_database"), tool(arguments="[]"), tool(arguments="bad"), {"tool_calls": [None]}]:
            with self.subTest(response=response):
                invoke = AsyncMock()
                with patch("campuspulse.alem_llm.completion", return_value=response), self.assertRaises(LmsError):
                    await alem_loop("q", SCHEMAS, invoke, CONFIG, "instruction")
                invoke.assert_not_awaited()

    async def test_revoked_session_prevents_next_model_request(self):
        authorize = AsyncMock(side_effect=[None, LmsError("revoked", 401)])
        with patch("campuspulse.alem_llm.completion", return_value=tool()) as complete, self.assertRaises(LmsError):
            await alem_loop("q", SCHEMAS, AsyncMock(return_value={}), CONFIG, "instruction", before_request=authorize)
        complete.assert_called_once()

    async def test_three_round_and_eight_tool_limits(self):
        for count in [1, 4]:
            response = {"tool_calls": [{**tool()["tool_calls"][0], "id": f"call_{i}"} for i in range(count)]}
            invoke = AsyncMock(return_value={})
            with patch("campuspulse.alem_llm.completion", return_value=response) as complete:
                if count == 1:
                    answer = await alem_loop("q", SCHEMAS, invoke, CONFIG, "instruction")
                    self.assertIn("трёх", answer)
                else:
                    with self.assertRaises(LmsError):
                        await alem_loop("q", SCHEMAS, invoke, CONFIG, "instruction")
            self.assertEqual(complete.call_count, 3)
            self.assertEqual(invoke.await_count, min(3 * count, 8))

    async def test_lms_gemma_reads_scoped_data_and_preserves_confirmation_boundary(self):
        import asyncio
        from test_lms_firestore import CONFIG as FIRESTORE_CONFIG, STUDENT, seeded_storage
        from campuspulse.firestore_repository import FirestoreRepository
        from campuspulse.lms_agent import run_lms_query
        repo = FirestoreRepository(seeded_storage(), FIRESTORE_CONFIG)
        token, _ = await asyncio.to_thread(repo.login, "student1", "student1")
        replies = [tool("query_data", json.dumps({"resource": "assignments", "fields": ["title", "due"], "limit": 1})),
                   tool("prepare_personal_change", json.dumps({"target": "task", "payload": {"title": "Review me"}})),
                   {"content": "Review the proposed task"}]
        captured = []
        def complete(config, messages, tools):
            captured.append(copy.deepcopy(messages))
            return replies.pop(0)
        with patch.dict(os.environ, {"CAMPUSPULSE_LLM_PROVIDER": "alem", "CAMPUSPULSE_ALEM_ENABLED": "1", "CAMPUSPULSE_ALEM_API_KEY": "private-test-key"}), patch("campuspulse.alem_llm.completion", side_effect=complete):
            result = await run_lms_query(repo, token, {"message": "My tasks", "engine": "llm"}, transport="direct")
        self.assertEqual(result["provider"], "alem")
        self.assertEqual(result["model"], "gemma4")
        responses = [json.loads(item["content"]) for item in captured[-1] if item["role"] == "tool"]
        self.assertEqual(set(responses[0]["items"][0]), {"title", "due"})
        self.assertNotIn("proposal", responses[1])
        self.assertNotIn("data_access", responses[0])
        self.assertIn("proposal", result["results"]["prepare_personal_change"])
        self.assertEqual(repo.personal_data(STUDENT)["tasks"], [])
        self.assertNotIn("private-test-key", json.dumps(result))
=======
"""Alem compatibility contract with mocked HTTP; never sends a real key."""
import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock,patch

from campuspulse.alem_provider import AlemConfig,alem_loop,alem_status,decode_action
from campuspulse.lms_store import LmsError

CONFIG=AlemConfig('fake-private-alem-key',enabled=True)
SCHEMAS=[{'name':'get_courses','description':'Read enrolled courses','inputSchema':{'type':'object','properties':{}}}]


def completion(content=None,tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content,tool_calls=tool_calls))])


class AlemConfigTests(unittest.TestCase):
    def test_key_is_not_in_status_repr_or_missing_key_error(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':CONFIG.api_key,'CAMPUSPULSE_ALLOW_CLOUD':'1'},clear=True):
            status=alem_status()
        self.assertTrue(status['calls_enabled'])
        self.assertNotIn(CONFIG.api_key,repr(status))
        self.assertNotIn(CONFIG.api_key,repr(CONFIG))
        with self.assertRaises(LmsError):AlemConfig('',enabled=True).require_enabled()
        self.assertFalse(AlemConfig('key',base_url='http://unsafe.example/v1').configured)

    def test_action_parser_rejects_commands_and_invalid_arguments(self):
        for raw in ['hello','[]','{"tool":"get_courses","arguments":[]}','{"answer":"","extra":"command"}']:
            with self.assertRaises(LmsError):decode_action(raw)
        self.assertEqual(decode_action('```json\n{"tool":"get_courses","arguments":{}}\n```')['tool'],'get_courses')


class AlemLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_chat_protocol_uses_documented_endpoint_and_validated_tools(self):
        client=MagicMock();captured=[]
        replies=[completion('{"tool":"get_courses","arguments":{}}'),completion('{"answer":"Found courses"}')]
        def create(**kwargs):captured.append(copy.deepcopy(kwargs));return replies.pop(0)
        client.chat.completions.create.side_effect=create
        invoke=AsyncMock(return_value={'courses':[{'id':'one','name':'Math'}]})
        authorize=AsyncMock();events=[]
        with patch('openai.OpenAI',return_value=client) as factory:
            answer=await alem_loop('Plan',SCHEMAS,invoke,CONFIG,'Instructions',events.append,before_request=authorize)
        self.assertEqual(answer,'Found courses')
        self.assertEqual(factory.call_args.kwargs['base_url'],'https://llm.alem.ai/v1')
        self.assertEqual(factory.call_args.kwargs['max_retries'],0)
        self.assertEqual(captured[0]['model'],'gemma4')
        self.assertNotIn('tools',captured[0])
        self.assertIn('Math',captured[1]['messages'][-1]['content'])
        self.assertEqual(authorize.await_count,2)
        invoke.assert_awaited_once_with('get_courses',{})
        self.assertNotIn(CONFIG.api_key,repr(events))
        client.close.assert_called_once()

    async def test_native_tool_call_id_is_returned(self):
        client=MagicMock();captured=[]
        tool=SimpleNamespace(id='call-123',type='function',function=SimpleNamespace(name='get_courses',arguments='{}'))
        replies=[completion(tool_calls=[tool]),completion('Answer')]
        def create(**kwargs):captured.append(copy.deepcopy(kwargs));return replies.pop(0)
        client.chat.completions.create.side_effect=create
        with patch('openai.OpenAI',return_value=client):
            result=await alem_loop('Plan',SCHEMAS,AsyncMock(return_value={'courses':[]}),AlemConfig('key',tool_mode='native',enabled=True),'instruction')
        self.assertEqual(result,'Answer')
        self.assertEqual(captured[1]['messages'][-1]['tool_call_id'],'call-123')
        self.assertEqual(captured[0]['tools'][0]['function']['name'],'get_courses')

    async def test_api_auth_errors_do_not_leak_request_or_key(self):
        client=MagicMock();error=RuntimeError('PRIVATE KEY '+CONFIG.api_key);error.status_code=401
        client.chat.completions.create.side_effect=error
        with patch('openai.OpenAI',return_value=client):
            with self.assertRaises(LmsError) as caught:
                await alem_loop('q',SCHEMAS,AsyncMock(),CONFIG,'instruction')
        self.assertNotIn(CONFIG.api_key,str(caught.exception))
        self.assertEqual(caught.exception.status,503)
        client.chat.completions.create.assert_called_once()

    async def test_unknown_tool_is_never_executed_and_loop_is_bounded(self):
        client=MagicMock();client.chat.completions.create.return_value=completion('{"tool":"shell","arguments":{}}')
        invoke=AsyncMock()
        with patch('openai.OpenAI',return_value=client):
            answer=await alem_loop('q',SCHEMAS,invoke,CONFIG,'instruction')
        self.assertIn('лимит',answer)
        self.assertEqual(client.chat.completions.create.call_count,3)
        invoke.assert_not_awaited()

    async def test_disabled_model_does_not_create_client(self):
        with patch('openai.OpenAI') as factory,self.assertRaises(LmsError):
            await alem_loop('q',SCHEMAS,AsyncMock(),AlemConfig('key'),'instruction')
        factory.assert_not_called()

    async def test_agent_routes_alem_to_the_same_authorized_mcp_registry(self):
        from campuspulse.firestore_repository import FirestoreRepository
        from campuspulse.lms_agent import run_lms_query
        from tests.test_lms_firestore import seeded_storage,CONFIG as FIREBASE_CONFIG
        repo=FirestoreRepository(seeded_storage(),FIREBASE_CONFIG)
        token,_=repo.login('student1','student1')
        client=MagicMock();client.chat.completions.create.side_effect=[completion('{"tool":"get_courses","arguments":{}}'),completion('{"answer":"Done"}')]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-key','CAMPUSPULSE_ALLOW_CLOUD':'1'}),patch('openai.OpenAI',return_value=client):
            result=await run_lms_query(repo,token,{'message':'My courses','engine':'alem'},transport='direct')
        self.assertEqual(result['provider'],'alem')
        self.assertTrue(result['model_called'])
        self.assertIn('get_courses',result['results'])
        self.assertEqual(result['results']['get_courses']['courses'][0]['id'],'course')


if __name__=='__main__':unittest.main()
>>>>>>> 126ecb7 (full rework)
