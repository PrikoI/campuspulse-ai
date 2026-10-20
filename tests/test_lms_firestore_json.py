"""Serialization, request budgets and model/MCP boundaries; no cloud credentials."""
import copy
import json
import math
import os
import sys
import unittest
from datetime import date, datetime, timezone
from enum import Enum, IntEnum
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from test_lms_firestore import MemoryStorage, seeded_storage, STUDENT, OTHER, CONFIG
from campuspulse.firestore_client import FirebaseConfig, FirestoreStorage
from campuspulse.firestore_repository import FirestoreRepository, compound_id
from campuspulse.lms_agent import run_lms_query
from campuspulse.lms_json import json_result, json_value, model_result, tool_error
from campuspulse.lms_store import LmsError
from campuspulse.lms_tools import LmsTools, schemas_for


class CountingStorage(MemoryStorage):
    def __init__(self, data=None):
        super().__init__(data)
        self.requests = []

    def get(self, path, transaction=None, **options):
        result = super().get(path, transaction, **options)
        self.requests.append({"method": "get", "path": path, "documents": int(result is not None), **options})
        return result

    def get_many(self, paths, transaction=None, fields=None):
        result = super().get_many(paths, transaction, fields)
        self.requests.append({"method": "batch", "paths": list(result), "documents": sum(row is not None for row in result.values()), "fields": fields})
        return result

    def scan(self, path, filters=(), transaction=None, limit=101, **options):
        result = super().scan(path, filters, transaction, limit, **options)
        self.requests.append({"method": "scan", "path": path, "filters": filters, "limit": limit, "documents": len(result), **options})
        return result


class JsonTests(unittest.TestCase):
    def test_datetime_date_enum_uuid_and_nested_values(self):
        class Status(str, Enum):
            PENDING = "pending"
        class Number(IntEnum):
            ONE = 1
        key = UUID("00000000-0000-0000-0000-000000000001")
        value = json_result({"id": key, "due": datetime(2030, 1, 1, tzinfo=timezone.utc),
                             "date": date(2030, 1, 1), "nested": (Status.PENDING, Number.ONE, None)})
        self.assertEqual(value["id"], str(key))
        self.assertEqual(value["due"], "2030-01-01T05:00:00+05:00")
        self.assertEqual(value["date"], "2030-01-01")
        self.assertEqual(value["nested"], ["pending", 1, None])
        self.assertEqual(json.loads(json.dumps(value, allow_nan=False)), value)

    def test_unsupported_values_are_rejected_without_stringifying_secrets(self):
        class Credential:
            def __str__(self):
                raise AssertionError("Must not stringify credentials")
        for value in [math.nan, math.inf, datetime(2030, 1, 1), Credential(), {1: "non-string-key"}]:
            with self.assertRaises(LmsError) as caught:
                json_value(value)
            self.assertEqual(caught.exception.status, 502)

    def test_model_view_omits_audit_and_signed_confirmation_token(self):
        raw = {"proposal": "signed-token", "change": {"after": {"title": "Task"}}, "data_access": [{"user_id": "student1"}]}
        self.assertEqual(model_result(raw), {"change": raw["change"]})
        self.assertIn("proposal", raw)
        error = tool_error(RuntimeError("private-driver-details"))
        self.assertEqual(error["status"], 503)
        self.assertTrue(error["retryable"])
        self.assertNotIn("private", json.dumps(error))


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.storage = CountingStorage(copy.deepcopy(seeded_storage().data))
        self.repo = FirestoreRepository(self.storage, CONFIG)
        self.storage.requests.clear()

    def test_courses_use_one_batch_and_do_not_repeat_enrollment_read(self):
        for index in range(20):
            cid = f"course{index}"
            self.storage.data["courses/" + cid] = {"code": "C", "name": cid, "archived": False, "owner_id": "admin"}
            self.storage.data["enrollments/" + compound_id(cid, STUDENT.user_id)] = {"course_id": cid, "student_id": STUDENT.user_id, "archived": False}
        result = LmsTools(self.repo, STUDENT).call("get_courses")
        self.assertEqual(len(result["courses"]), 21)
        self.assertEqual([request["method"] for request in self.storage.requests], ["scan", "batch"])
        self.assertEqual(self.storage.writes, 0)

    def test_one_course_authorization_does_not_enumerate_all_courses(self):
        self.repo.list("assignments", STUDENT, "course")
        self.assertEqual([(request["method"], request.get("path")) for request in self.storage.requests],
                         [("get", "enrollments/" + compound_id("course", "student1")), ("get", "courses/course"), ("scan", "assignments")])
        self.storage.data["enrollments/" + compound_id("course", "student1")]["student_id"] = "student2"
        with self.assertRaises(LmsError):
            self.repo.list("assignments", STUDENT, "course")

    def test_id_lookup_reads_one_assignment_without_collection_scan(self):
        query = {"resource": "assignments", "filters": {"id": "a"}, "fields": ["title", "due"], "limit": 1}
        result = self.repo.query_data(STUDENT, query)
        self.assertEqual(result["items"], [{"title": "Work", "due": "2030-01-01T05:00:00+05:00"}])
        self.assertFalse(any(request["method"] == "scan" for request in self.storage.requests))
        self.assertEqual(self.repo.query_data(STUDENT, {**query, "filters": {"id": "missing"}})["items"], [])
        with self.assertRaises(LmsError):
            self.repo.query_data(STUDENT, {**query, "filters": {"id": "b"}})

    def test_filters_projection_and_limit_are_applied_before_materialization(self):
        for index in range(250):
            self.storage.data[f"assignments/large{index:03}"] = {"course_id": "course", "title": "Noise", "description": "x" * 10000}
        result = self.repo.query_data(STUDENT, {"resource": "assignments", "filters": {"title": "Work"}, "fields": ["title", "due"], "limit": 2})
        self.assertEqual(len(result["items"]), 1)
        request = next(item for item in self.storage.requests if item.get("path") == "assignments")
        self.assertIn(("title", "==", "Work"), request["filters"])
        self.assertEqual(request["fields"], ["due", "title"])
        self.assertEqual(request["limit"], 3)
        self.assertEqual(request["documents"], 1)
        self.assertEqual(self.storage.writes, 0)

    def test_pagination_is_bounded_and_rechecks_user_scope(self):
        for index in range(130):
            self.storage.data[f"assignments/page{index:03}"] = {"course_id": "course", "title": "Page"}
        request = {"resource": "assignments", "fields": ["id", "title"], "limit": 7}
        seen, cursor = set(), None
        for _ in range(30):
            result = self.repo.query_data(STUDENT, {**request, "cursor": cursor})
            keys = {row["id"] for row in result["items"]}
            self.assertFalse(keys & seen)
            seen |= keys
            cursor = result["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(len(seen), 131)
        self.assertTrue(all(item["documents"] <= 8 for item in self.storage.requests if item.get("path") == "assignments"))
        result = self.repo.query_data(STUDENT, request)
        with self.assertRaises(LmsError):
            self.repo.query_data(OTHER, {**request, "cursor": result["next_cursor"]})
        self.storage.data["enrollments/" + compound_id("course", "student1")]["archived"] = True
        with self.assertRaises(LmsError):
            self.repo.query_data(STUDENT, {**request, "cursor": result["next_cursor"]})

    def test_legacy_missing_defaults_and_timezone_filter_remain_compatible(self):
        self.assertEqual(len(self.repo.query_data(STUDENT, {"resource": "assignments", "filters": {"description": ""}})["items"]), 1)
        self.assertEqual(len(self.repo.query_data(STUDENT, {"resource": "assignments", "filters": {"due": "2030-01-01T05:00:00+05:00"}})["items"]), 1)
        self.assertEqual(self.repo.query_data(STUDENT, {"resource": "assignments", "filters": {"title": "absent"}})["items"], [])
        with self.assertRaises(LmsError):
            self.repo.query_data(STUDENT, {"resource": "assignments", "filters": {"due": "2030-01-01"}})

    def test_plan_fetches_only_needed_columns_and_catalog_has_no_transaction(self):
        LmsTools(self.repo, STUDENT).call("plan_study")
        assignment_request = next(item for item in self.storage.requests if item.get("path") == "assignments")
        self.assertNotIn("description", assignment_request["fields"])
        with patch.object(self.storage, "transaction", wraps=self.storage.transaction) as transaction:
            LmsTools(self.repo, STUDENT).call("list_data_resources")
            transaction.assert_not_called()
        original = self.storage.scan
        def fail_lessons(path, *args, **kwargs):
            if path == "lessons":
                raise RuntimeError("private-driver-failure")
            return original(path, *args, **kwargs)
        with patch.object(self.storage, "scan", side_effect=fail_lessons):
            result = LmsTools(self.repo, STUDENT).call("plan_study")
        self.assertEqual(result["status"], 503)
        self.assertTrue(any(event["collection"] == "lessons" and event["status"] == "failed" for event in result["data_access"]))

    def test_confirmation_before_image_never_exposes_unlisted_fields(self):
        self.storage.data["users/student1/tasks/personal"] = {"title": "Owned", "minutes": 30, "internal_token": "private-value"}
        proposal = self.repo.prepare_personal_change(STUDENT, {"target": "task", "record_id": "personal", "payload": {"done": True}})
        self.assertNotIn("private-value", json.dumps(proposal))
        self.assertNotIn("internal_token", proposal["change"]["before"])


class SdkTests(unittest.TestCase):
    def test_real_sdk_query_encodes_projection_cursor_scope_and_limit_without_network(self):
        from google.auth.credentials import AnonymousCredentials
        from google.cloud.firestore_v1 import Client
        client = Client(project="demo-campus", credentials=AnonymousCredentials())
        transport = MagicMock()
        transport.run_query.return_value = iter(())
        client._firestore_api_internal = transport
        prefix = "system_tests/backend-" + "a" * 32
        store = FirestoreStorage(client, prefix=prefix)
        self.assertEqual(store.scan("assignments", [("course_id", "==", "course")], limit=3, fields=["title"], after="one"), [])
        options = transport.run_query.call_args.kwargs
        request = options["request"]
        query = request["structured_query"]
        self.assertEqual(query.limit, 3)
        self.assertEqual([field.field_path for field in query.select.fields], ["title"])
        self.assertEqual(query.where.field_filter.field.field_path, "course_id")
        self.assertTrue(query.start_at.values[0].reference_value.endswith(prefix + "/assignments/one"))
        self.assertTrue(request["parent"].endswith(prefix))
        self.assertEqual(options["timeout"], 10)
        self.assertIsNone(options["retry"])

    def test_batch_preserves_requested_paths_despite_out_of_order_snapshots(self):
        client = MagicMock()
        client.get_all.return_value = [SimpleNamespace(exists=True, reference=SimpleNamespace(path="courses/b"), to_dict=lambda: {"name": "B"}),
                                       SimpleNamespace(exists=False, reference=SimpleNamespace(path="courses/a"))]
        result = FirestoreStorage(client).get_many(["courses/a", "courses/b"], fields=["name"])
        self.assertEqual(result, {"courses/a": None, "courses/b": {"name": "B"}})
        self.assertEqual(client.get_all.call_args.kwargs["field_paths"], ["name"])
        self.assertEqual(client.get_all.call_args.kwargs["timeout"], 10)

    def test_test_namespace_is_validated_and_forwarded_to_mcp(self):
        namespace = "backend-" + "a" * 32
        with patch.dict(os.environ, {"CAMPUSPULSE_FIRESTORE_TEST_NAMESPACE": namespace, "CAMPUSPULSE_FIREBASE_CREDENTIALS": "adc"}):
            config = FirebaseConfig.from_environment()
        self.assertEqual(config.environment()["CAMPUSPULSE_FIRESTORE_TEST_NAMESPACE"], namespace)
        client = MagicMock()
        store = FirestoreStorage(client, prefix="system_tests/" + namespace)
        store.ref("courses/course")
        client.document.assert_called_once_with("system_tests/" + namespace + "/courses/course")
        with self.assertRaises(LmsError):
            FirestoreStorage(client, prefix="users/student1")

    def test_live_harness_exercises_backend_offline_and_requires_explicit_live(self):
        from scripts.check_firestore_backend import run_check, main
        storage = MemoryStorage()
        result = run_check(lambda: FirestoreRepository(storage, CONFIG), transport="direct")
        self.assertTrue(result["restart"])
        self.assertTrue(result["user_isolation"])
        with patch.object(sys, "argv", ["check_firestore_backend"]), patch("sys.stderr"), self.assertRaises(SystemExit):
            main()


class AgentBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_mcp_structured_content_and_standard_errors(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        repo = FirestoreRepository(seeded_storage(), CONFIG)
        import asyncio
        token, _ = await asyncio.to_thread(repo.login, "student1", "student1")
        code = ("import sys; sys.path.insert(0, 'tests'); "
                "from test_lms_firestore import seeded_storage, CONFIG; "
                "from campuspulse.firestore_repository import FirestoreRepository; "
                "import campuspulse.lms_mcp_server as server; "
                "server.open_repository=lambda **kw: FirestoreRepository(seeded_storage(), CONFIG); "
                "server.mcp.run(transport='stdio')")
        params = StdioServerParameters(command=sys.executable, args=["-c", code],
                  env={"CAMPUSPULSE_LMS_SESSION_SECRET": repo.secret, "SYSTEMROOT": os.getenv("SYSTEMROOT", "")})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("load_session", {"session_token": token})
                tools = await session.list_tools()
                selected = [tool for tool in tools.tools if tool.name in {spec["name"] for spec in schemas_for(repo)}]
                self.assertEqual(len(selected), 10)
                self.assertTrue(all(tool.outputSchema and tool.outputSchema.get("type") == "object" for tool in selected))
                result = await session.call_tool("query_data", {"resource": "assignments", "fields": ["title", "due"], "limit": 1})
                self.assertIsNotNone(result.structuredContent)
                self.assertEqual(result.structuredContent["items"][0]["due"], "2030-01-01T05:00:00+05:00")
                self.assertEqual(set(result.structuredContent["items"][0]), {"title", "due"})
                result = await session.call_tool("query_data", {"resource": "assignments", "filters": {"student_id": "student2"}})
                self.assertEqual(result.structuredContent["status"], 400)
                self.assertEqual(result.structuredContent["error_code"], "invalid_request")

    async def test_gemini_receives_projected_dict_function_result_without_review_token(self):
        import asyncio
        from google.genai import types
        repo = FirestoreRepository(seeded_storage(), CONFIG)
        token, _ = await asyncio.to_thread(repo.login, "student1", "student1")
        responses = [
            SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part.from_function_call(
                name="query_data", args={"resource": "assignments", "fields": ["title", "due"], "limit": 1})]))]),
            SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part.from_function_call(
                name="prepare_personal_change", args={"target": "task", "payload": {"title": "Review me"}})]))]),
            SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part.from_text(text="Ответ по данным инструмента")]))]),
        ]
        client = MagicMock()
        captured = []
        def generate(**kwargs):
            captured.append(copy.deepcopy(kwargs["contents"]))
            return responses.pop(0)
        client.models.generate_content.side_effect = generate
        manager = MagicMock(); manager.__enter__.return_value = client
        connection = SimpleNamespace(model="mock-gemini", client_options=lambda: {"api_key": "not-a-real-key"})
        with patch("google.genai.Client", return_value=manager):
            result = await run_lms_query(repo, token, {"message": "Покажи дедлайн", "engine": "gemini"}, connection, transport="direct")
        returned = [part.function_response.response for content in captured[-1] for part in content.parts if part.function_response]
        self.assertEqual(set(returned[0]["items"][0]), {"title", "due"})
        self.assertNotIn("data_access", returned[0])
        self.assertNotIn("proposal", returned[1])
        self.assertIn("proposal", result["results"]["prepare_personal_change"])
        self.assertEqual(repo.personal_data(STUDENT)["tasks"], [])

    async def test_local_plan_does_not_preload_assignments(self):
        import asyncio
        repo = FirestoreRepository(seeded_storage(), CONFIG)
        token, _ = await asyncio.to_thread(repo.login, "student1", "student1")
        result = await run_lms_query(repo, token, {"message": "План подготовки", "hours_per_day": 2}, transport="direct")
        names = [event["tool"] for event in result["trace"] if event["type"] == "tool_start"]
        self.assertIn("plan_study", names)
        self.assertNotIn("get_assignments", names)
