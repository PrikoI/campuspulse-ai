"""Offline Firestore contract tests. No real SDK credentials or cloud data."""
import asyncio
import copy
import http.client
import json
import os
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from campuspulse.firestore_client import FirebaseConfig, FirestoreStorage, firebase_client
from campuspulse.firestore_repository import FirestoreRepository, compound_id
from campuspulse.lms_agent import run_lms_query
from campuspulse.lms_repository import open_repository
from campuspulse.lms_server import LmsHandler
from campuspulse.lms_store import LmsError, Principal
from campuspulse.lms_tools import LMS_SCHEMAS, LmsTools, schemas_for

STUDENT = Principal("student1", "student", "Student")
OTHER = Principal("student2", "student", "Other")
ADMIN = Principal("admin", "admin", "Teacher")
CONFIG = FirebaseConfig("demo-campus", "(default)", "adc")


class MemoryStorage:
    """Injectable transactional test double; backing dict survives repository recreation."""
    def __init__(self, data=None):
        self.data = data if data is not None else {}
        self.lock = threading.RLock()
        self.fail = False
        self.writes = 0
        self.calls = []

    def get(self, path, transaction=None, *, fields=None):
        if self.fail:
            raise RuntimeError("private-connection-details")
        self.calls.append(("get", path))
        data = self.data if transaction is None else transaction
        row = copy.deepcopy(data.get(path))
        return {field: row[field] for field in fields if field in row} if row is not None and fields is not None else row

    def get_many(self, paths, transaction=None, fields=None):
        if self.fail:
            raise RuntimeError("private-driver-error")
        paths = list(dict.fromkeys(paths))
        self.calls.append(("get_many", paths, fields))
        data = self.data if transaction is None else transaction
        return {path: ({field: row[field] for field in fields if field in row} if fields is not None else copy.deepcopy(row))
                if (row := data.get(path)) is not None else None for path in paths}

    def scan(self, path, filters=(), transaction=None, limit=101, *, fields=None, after=None):
        if self.fail:
            raise RuntimeError("private-driver-error")
        self.calls.append(("scan", path, filters))
        data = self.data if transaction is None else transaction
        rows = []
        for key, row in sorted(data.items()):
            if not key.startswith(path + "/") or "/" in key[len(path) + 1:]:
                continue
            doc_id = key.rsplit("/", 1)[1]
            if after is not None and doc_id <= after:
                continue
            if all(row.get(field) == value if op == "==" else row.get(field) in value for field, op, value in filters):
                selected = {field: row[field] for field in fields if field in row} if fields is not None else row
                rows.append((doc_id, copy.deepcopy(selected)))
        return rows[:limit]

    def transaction(self, callback, *, read_only=False):
        with self.lock:
            original = copy.deepcopy(self.data)
            working = copy.deepcopy(self.data)
            result = callback(working)
            if read_only and working != original:
                raise AssertionError("Write in read-only transaction")
            self.writes += sum(original.get(key) != working.get(key) for key in original.keys() | working.keys())
            self.data.clear()
            self.data.update(working)
            return result

    def put(self, transaction, path, row):
        transaction[path] = copy.deepcopy(row)

    def delete(self, transaction, path):
        transaction.pop(path, None)


def seeded_storage():
    data = {
        "users/student1": {"role": "student", "name": "Student"},
        "users/student2": {"role": "student", "name": "Other"},
        "courses/course": {"code": "CS", "name": "CS", "owner_id": "admin", "archived": False},
        "courses/other": {"code": "BIO", "name": "BIO", "owner_id": "teacher2", "archived": False},
        "assignments/a": {"course_id": "course", "title": "Work", "due": datetime(2030, 1, 1, tzinfo=timezone.utc), "minutes": 60},
        "assignments/b": {"course_id": "other", "title": "Private work", "minutes": 30},
        "grades/g1": {"course_id": "course", "student_id": "student1", "item_id": "i", "score": 70},
        "grades/g2": {"course_id": "course", "student_id": "student2", "item_id": "i", "score": 80},
    }
    for cid, uid in [("course", "student1"), ("course", "student2"), ("other", "student2")]:
        data[f"enrollments/{compound_id(cid, uid)}"] = {"course_id": cid, "student_id": uid, "archived": False}
    return MemoryStorage(data)


class InitializationTests(unittest.TestCase):
    def test_sdk_initializes_once_and_uses_explicit_key_without_reading_it_in_test(self):
        app, client = SimpleNamespace(project_id="demo-campus"), object()
        config = FirebaseConfig("demo-campus", "(default)", "mock-key.json")
        with patch("campuspulse.firestore_client._CLIENTS", {}), \
             patch("firebase_admin.get_app", side_effect=ValueError), \
             patch("firebase_admin.initialize_app", return_value=app) as initialize, \
             patch("firebase_admin.credentials.Certificate", return_value=object()) as certificate, \
             patch("firebase_admin.firestore.client", return_value=client):
            self.assertIs(firebase_client(config), client)
            self.assertIs(firebase_client(config), client)
            initialize.assert_called_once()
            certificate.assert_called_once_with("mock-key.json")

    def test_adc_and_existing_application(self):
        app = SimpleNamespace(project_id="demo-campus")
        with patch("campuspulse.firestore_client._CLIENTS", {}), patch("firebase_admin.get_app", side_effect=ValueError), \
             patch("firebase_admin.initialize_app", return_value=app), \
             patch("firebase_admin.credentials.ApplicationDefault") as adc, patch("firebase_admin.firestore.client"):
            firebase_client(CONFIG)
            adc.assert_called_once()
        with patch("campuspulse.firestore_client._CLIENTS", {}), patch("firebase_admin.get_app", return_value=app), \
             patch("firebase_admin.initialize_app") as initialize, patch("firebase_admin.firestore.client"):
            firebase_client(CONFIG)
            initialize.assert_not_called()

    def test_wrong_project_cannot_reuse_existing_app(self):
        with patch("campuspulse.firestore_client._CLIENTS", {}), \
             patch("firebase_admin.get_app", return_value=SimpleNamespace(project_id="other")), \
             patch("firebase_admin.initialize_app") as initialize, self.assertRaises(LmsError):
            firebase_client(CONFIG)
        initialize.assert_not_called()

    def test_cloud_configuration_uses_adc_and_only_needed_environment(self):
        with patch.dict(os.environ, {"K_SERVICE": "test", "GEMINI_API_KEY": "private"}, clear=True):
            config = FirebaseConfig.from_environment()
            self.assertEqual(config.credentials, "adc")
            self.assertNotIn("GEMINI_API_KEY", config.environment())

    def test_readiness_failure_and_no_silent_fallback(self):
        storage = MemoryStorage(); storage.fail = True
        with self.assertRaises(LmsError) as caught:
            FirestoreRepository(storage, CONFIG)
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn("private", str(caught.exception))

    def test_repository_selection_and_process_config(self):
        storage = seeded_storage()
        with patch.dict(os.environ, {"CAMPUSPULSE_LMS_REPOSITORY": "firestore"}), \
             patch("campuspulse.firestore_repository.firebase_client"), \
             patch("campuspulse.firestore_repository.FirestoreStorage", return_value=storage):
            repo = open_repository()
        env = repo.mcp_environment()
        self.assertEqual(env["CAMPUSPULSE_LMS_REPOSITORY"], "firestore")
        self.assertEqual(env["CAMPUSPULSE_LMS_SESSION_SECRET"], repo.secret)
        self.assertNotIn("PRIVATE_KEY", str(env.keys()))

    def test_sdk_boundary_has_explicit_read_timeout_and_no_retry(self):
        client = MagicMock()
        client.document.return_value.get.return_value.exists = False
        store = FirestoreStorage(client)
        self.assertIsNone(store.get("courses/missing"))
        client.document.return_value.get.assert_called_once_with(transaction=None, retry=None, timeout=10)
        query = client.collection.return_value.where.return_value
        query.limit.return_value.stream.return_value = []
        self.assertEqual(store.scan("enrollments", [("student_id", "==", "student1")]), [])
        query.limit.return_value.stream.assert_called_once_with(transaction=None, retry=None, timeout=10)
        for path in ["courses/.", "courses/..", "courses/__reserved__"]:
            with self.assertRaises(LmsError):
                store.get(path)

    def test_sdk_transaction_encodes_writes_and_deletes_without_network(self):
        from google.auth.credentials import AnonymousCredentials
        from google.cloud.firestore_v1 import Client
        from google.cloud.firestore_v1.types import CommitResponse, BeginTransactionResponse
        client = Client(project="demo-campus", credentials=AnonymousCredentials())
        transport = MagicMock()
        client._firestore_api_internal = transport
        transport.begin_transaction.return_value = BeginTransactionResponse(transaction=b"test-transaction")
        transport.commit.return_value = CommitResponse()
        store = FirestoreStorage(client)
        store.transaction(lambda tx: store.put(tx, "users/student1/tasks/one", {"title": "Task", "due": datetime(2030, 1, 1, tzinfo=timezone.utc)}))
        write = transport.commit.call_args.kwargs["request"]["writes"][0]
        self.assertEqual(write.update.fields["title"].string_value, "Task")
        self.assertEqual(write.update.fields["due"].timestamp_value.year, 2030)
        store.transaction(lambda tx: store.delete(tx, "users/student1/tasks/one"))
        write = transport.commit.call_args.kwargs["request"]["writes"][0]
        self.assertTrue(write.delete.endswith("/users/student1/tasks/one"))


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.storage = seeded_storage()
        self.repo = FirestoreRepository(self.storage, CONFIG)

    def test_create_read_update_and_restart(self):
        created = self.repo.save("assignments", ADMIN, {"course_id": "course", "title": "New", "due": "2030-01-01T00:00:00Z"})
        self.assertTrue(created["due"].endswith("+05:00"))
        self.assertIsInstance(self.storage.data[f"assignments/{created['id']}"]["due"], datetime)
        self.repo.save("assignments", ADMIN, {"title": "Updated"}, created["id"])
        restarted = FirestoreRepository(self.storage, CONFIG)
        self.assertIn("Updated", [row["title"] for row in restarted.list("assignments", STUDENT)])
        self.assertEqual(self.storage.data["assignments/a"]["title"], "Work")

    def test_missing_document_and_patch_never_upserts(self):
        with self.assertRaises(LmsError) as caught:
            self.repo.save("assignments", ADMIN, {"title": "Missing"}, "absent")
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn("assignments/absent", self.storage.data)

    def test_user_isolation_and_course_ownership(self):
        self.assertEqual({row["id"] for row in self.repo.list("courses", STUDENT)}, {"course"})
        self.assertEqual({row["student_id"] for row in self.repo.list("grades", STUDENT)}, {"student1"})
        self.assertEqual({row["id"] for row in self.repo.list("courses", ADMIN)}, {"course"})
        for action in [lambda: self.repo.list("assignments", STUDENT, "other"),
                       lambda: self.repo.save("assignments", STUDENT, {"course_id": "course", "title": "No"}),
                       lambda: self.repo.save("assignments", ADMIN, {"course_id": "other", "title": "No"}),
                       lambda: self.repo.save("courses", ADMIN, {"name": "No"}, "other")]:
            with self.assertRaises(LmsError) as caught:
                action()
            self.assertEqual(caught.exception.status, 403)
        self.assertNotIn("owner_id", self.repo.list("courses", STUDENT)[0])

    def test_archived_enrollment_and_course_revoke_access(self):
        eid = compound_id("course", "student1")
        self.repo.save("enrollments", ADMIN, {"archived": True}, eid)
        self.assertEqual(self.repo.list("assignments", STUDENT), [])
        self.repo.save("enrollments", ADMIN, {"archived": False}, eid)
        self.repo.save("courses", ADMIN, {"archived": True}, "course")
        self.assertEqual(self.repo.list("assignments", STUDENT), [])

    def test_foreign_keys_uniqueness_and_score_bounds(self):
        item = self.repo.save("grade_items", ADMIN, {"course_id": "course", "title": "Final", "component": "final", "max_score": 20})
        payload = {"course_id": "course", "student_id": "student1", "item_id": item["id"], "score": 15}
        grade = self.repo.save("grades", ADMIN, payload)
        self.assertEqual(self.repo.save("grades", ADMIN, payload), grade)
        for bad in [{"score": 21}, {"student_id": "missing"}, {"item_id": "missing"}]:
            with self.assertRaises(LmsError):
                self.repo.save("grades", ADMIN, {**payload, **bad})
        with self.assertRaises(LmsError):
            self.repo.save("grade_items", ADMIN, {"max_score": 10}, item["id"])
        with self.assertRaises(LmsError):
            self.repo.save("grades", ADMIN, {"student_id": "student2"}, grade["id"])

    def test_concurrent_repeated_enrollment_does_not_duplicate_documents(self):
        from concurrent.futures import ThreadPoolExecutor
        payload = {"course_id": "course", "student_id": "student1"}
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.repo.save("enrollments", ADMIN, payload)["id"], range(8)))
        self.assertEqual(set(ids), {compound_id("course", "student1")})

    def test_lesson_patch_checks_merged_dates(self):
        lesson = self.repo.save("lessons", ADMIN, {"course_id": "course", "title": "Lecture", "starts_at": "2030-01-01T10:00:00+05:00", "ends_at": "2030-01-01T11:00:00+05:00"})
        with self.assertRaises(LmsError):
            self.repo.save("lessons", ADMIN, {"ends_at": "2030-01-01T09:00:00+05:00"}, lesson["id"])

    def test_generic_queries_projection_pagination_and_cursor_binding(self):
        self.repo.save("assignments", ADMIN, {"course_id": "course", "title": "Another"})
        request = {"resource": "assignments", "fields": ["title"], "limit": 1}
        result = self.repo.query_data(STUDENT, request)
        self.assertIsNotNone(result["next_cursor"])
        page = self.repo.query_data(STUDENT, {**request, "cursor": result["next_cursor"]})
        self.assertEqual(set(page["items"][0]), {"title"})
        for bad in [{**request, "cursor": result["next_cursor"], "fields": ["id"]},
                    {**request, "cursor": "bad"}, {**request, "filters": {"student_id": "student2"}},
                    {**request, "fields": ["owner_id"]}]:
            with self.assertRaises(LmsError):
                self.repo.query_data(STUDENT, bad)
        with self.assertRaises(LmsError):
            self.repo.query_data(OTHER, {**request, "cursor": result["next_cursor"]})

    def test_outage_is_not_empty_success_and_preserves_data(self):
        before = copy.deepcopy(self.storage.data)
        self.storage.fail = True
        audit = []
        with self.assertRaises(LmsError) as caught:
            self.repo.list("assignments", STUDENT, audit=audit)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(audit[0]["status"], "failed")
        self.assertIsNone(audit[0]["executed"])
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(self.storage.data, before)

    def test_large_lists_are_rejected_without_silent_truncation(self):
        for index in range(101):
            self.storage.data[f"assignments/bulk{index}"] = {"course_id": "course", "title": "Work"}
        with self.assertRaises(LmsError) as caught:
            self.repo.list("assignments", STUDENT)
        self.assertEqual(caught.exception.status, 413)

    def test_login_writes_only_public_profile_once(self):
        self.storage.data.pop("users/student1")
        self.repo.login("student1", "student1")
        self.assertEqual(set(self.storage.data["users/student1"]), {"role", "name"})
        writes = self.storage.writes
        self.repo.login("student1", "student1")
        self.assertEqual(self.storage.writes, writes)
        with self.assertRaises(LmsError):
            self.repo.create_student(ADMIN, {"username": "new", "password": "secret", "name": "New"})

    def test_existing_mcp_contracts_and_schedule_access(self):
        tools = LmsTools(self.repo, STUDENT)
        self.assertEqual(len(LMS_SCHEMAS), 8)
        self.assertEqual(len(schemas_for(self.repo)), 10)
        self.assertEqual(tools.call("get_courses")["courses"][0]["id"], "course")
        self.assertTrue(tools.call("get_assignments")["assignments"])
        self.assertEqual(tools.call("query_data", {"resource": "lessons"})["items"], [])
        with self.assertRaises(LmsError):
            tools.call("confirm_personal_change", {})

    def test_tool_uses_one_snapshot_and_permission_cache_expires_between_calls(self):
        self.storage.calls.clear()
        LmsTools(self.repo, STUDENT).call("plan_study")
        enrollment_checks = [call for call in self.storage.calls if call[0:2] == ("scan", "enrollments")
                             and call[2] == [("student_id", "==", "student1")]]
        self.assertEqual(len(enrollment_checks), 1)
        self.storage.data[f"enrollments/{compound_id('course', 'student1')}"]["archived"] = True
        self.assertEqual(LmsTools(self.repo, STUDENT).call("get_assignments")["assignments"], [])

    def test_invalid_tool_arguments_do_not_start_a_database_transaction(self):
        with patch.object(self.storage, "transaction", wraps=self.storage.transaction) as transaction:
            with self.assertRaises(LmsError):
                LmsTools(self.repo, STUDENT).call("query_data", {"resource": "assignments", "filters": {"student_id": "student2"}})
            transaction.assert_not_called()

    def test_quota_and_timeout_errors_are_safe_failures(self):
        from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded
        for error in [ResourceExhausted("private-quota-details"), DeadlineExceeded("private-timeout-details")]:
            with patch.object(self.storage, "transaction", side_effect=error), self.assertRaises(LmsError) as caught:
                self.repo.list("assignments", STUDENT)
            self.assertEqual(caught.exception.status, 503)
            self.assertNotIn("private", str(caught.exception))


class PersonalTests(unittest.TestCase):
    setUp = RepositoryTests.setUp

    def propose(self, payload, **extra):
        return self.repo.prepare_personal_change(STUDENT, {"target": "task", "payload": payload, **extra})

    def test_create_confirm_update_delete_restart_and_idempotency(self):
        before = copy.deepcopy(self.storage.data)
        proposal = self.propose({"title": "Personal", "due": "2030-01-01T00:00:00Z", "minutes": 30})
        self.assertEqual(self.storage.data, before)
        self.assertFalse(proposal["written"])
        self.repo.confirm_personal_change(STUDENT, proposal["proposal"])
        self.assertTrue(self.repo.confirm_personal_change(STUDENT, proposal["proposal"])["already_applied"])
        restarted = FirestoreRepository(self.storage, CONFIG)
        task = restarted.personal_data(STUDENT)["tasks"][0]
        self.assertEqual(task["title"], "Personal")
        update = self.propose({"done": True}, record_id=task["id"])
        self.repo.confirm_personal_change(STUDENT, update["proposal"])
        self.assertTrue(self.repo.personal_data(STUDENT)["tasks"][0]["done"])
        delete = self.propose({}, record_id=task["id"], operation="delete")
        self.repo.confirm_personal_change(STUDENT, delete["proposal"])
        self.assertEqual(self.repo.personal_data(STUDENT)["tasks"], [])

    def test_scope_tampering_expiry_conflict_and_secret_fields(self):
        proposal = self.propose({"title": "Personal"})
        for actor, token in [(OTHER, proposal["proposal"]), (STUDENT, proposal["proposal"] + "x")]:
            with self.assertRaises(LmsError):
                self.repo.confirm_personal_change(actor, token)
        with patch("campuspulse.firestore_personal.time.time", return_value=time.time() + 601), self.assertRaises(LmsError):
            self.repo.confirm_personal_change(STUDENT, proposal["proposal"])
        self.repo.confirm_personal_change(STUDENT, proposal["proposal"])
        key = proposal["change"]["record_id"]
        old = self.propose({"title": "Stale"}, record_id=key)
        new = self.propose({"title": "Fresh"}, record_id=key)
        self.repo.confirm_personal_change(STUDENT, new["proposal"])
        with self.assertRaises(LmsError) as caught:
            self.repo.confirm_personal_change(STUDENT, old["proposal"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.repo.personal_data(OTHER)["tasks"], [])
        for bad in [{"title": "x", "api_key": "secret"}, {"title": "x", "done": "yes"}, {"title": "x", "due": "2030-01-01"}]:
            with self.assertRaises(ValueError):
                self.propose(bad)

    def test_preferences_and_personal_tasks_used_in_plan(self):
        proposal = self.repo.prepare_personal_change(STUDENT, {"target": "preferences", "payload": {"hours_per_day": 2}})
        self.repo.confirm_personal_change(STUDENT, proposal["proposal"])
        self.assertEqual(FirestoreRepository(self.storage, CONFIG).personal_data(STUDENT)["preferences"]["hours_per_day"], 2)
        task = self.propose({"title": "Personal", "due": "2030-01-01T00:00:00Z", "minutes": 30})
        self.repo.confirm_personal_change(STUDENT, task["proposal"])
        plan = LmsTools(self.repo, STUDENT).call("plan_study")
        self.assertTrue(any(row["title"] == "Personal" for row in plan["plan"]["blocks"]))


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_agent_uses_worker_for_firestore(self):
        repo = FirestoreRepository(seeded_storage(), CONFIG)
        token, _ = await asyncio.to_thread(repo.login, "student1", "student1")
        main_thread = threading.get_ident()
        original = repo.check_course
        threads = []
        def check(*args):
            threads.append(threading.get_ident())
            return original(*args)
        with patch.object(repo, "check_course", side_effect=check):
            result = await run_lms_query(repo, token, {"message": "Задания", "course_id": "course"}, transport="direct")
        self.assertTrue(result["results"]["get_assignments"]["assignments"])
        self.assertTrue(threads and all(thread != main_thread for thread in threads))
        result = await run_lms_query(repo, token, {"message": "Создать", "personal_change": {"target": "task", "payload": {"title": "New"}}}, transport="direct")
        self.assertTrue(result["results"]["prepare_personal_change"]["confirmation_required"])
        self.assertEqual(repo.personal_data(STUDENT)["tasks"], [])

    async def test_real_stdio_mcp_with_firestore_repository_and_mock_storage(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        repo = FirestoreRepository(seeded_storage(), CONFIG)
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
                loaded = await session.call_tool("load_session", {"session_token": token})
                self.assertFalse(loaded.isError)
                advertised = await session.list_tools()
                self.assertTrue({item["name"] for item in LMS_SCHEMAS}.issubset({item.name for item in advertised.tools}))
                result = await session.call_tool("get_assignments", {})
                self.assertFalse(result.isError)
                content = result.structuredContent or json.loads(result.content[0].text)
                self.assertEqual(content["assignments"][0]["title"], "Work")
                result = await session.call_tool("prepare_personal_change", {"target": "task", "payload": {"title": "MCP"}})
                content = result.structuredContent or json.loads(result.content[0].text)
                self.assertTrue(content["confirmation_required"])


class HttpTests(unittest.TestCase):
    def test_user_review_and_confirm_only_through_http(self):
        repo = FirestoreRepository(seeded_storage(), CONFIG)
        token, _ = repo.login("student1", "student1")
        server = ThreadingHTTPServer(("127.0.0.1", 0), LmsHandler)
        server.repository = repo
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(path, data):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            conn.request("POST", "/api/v1/" + path, json.dumps(data), {"Content-Type": "application/json", "Cookie": "campuspulse_lms=" + token})
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            conn.close()
            return result
        try:
            status, proposal = request("actions/prepare", {"target": "task", "payload": {"title": "Reviewed"}})
            self.assertEqual(status, 200)
            self.assertEqual(repo.personal_data(STUDENT)["tasks"], [])
            status, _ = request("actions/confirm", {"proposal": proposal["proposal"], "confirmed": False})
            self.assertEqual(status, 400)
            status, result = request("actions/confirm", {"proposal": proposal["proposal"], "confirmed": True})
            self.assertEqual(status, 200)
            self.assertTrue(result["applied"])
        finally:
            server.shutdown(); server.server_close(); thread.join()
