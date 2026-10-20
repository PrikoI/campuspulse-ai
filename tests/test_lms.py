import asyncio
import base64
import http.client
import json
import os
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from campuspulse.grading import evaluate_grades, letter_grade, policy_config
from campuspulse.lms_agent import run_lms_query, lms_tool_session
from campuspulse.lms_repository import open_repository
from campuspulse.lms_server import LmsHandler
from campuspulse.lms_store import LmsError
from campuspulse.lms_tools import LmsTools
from campuspulse.lms_store import KINDS
from campuspulse.lms_openapi import openapi_document
from campuspulse.lms_data import catalog_metadata, check_query_catalog, query_request


def grade(component, score, **extra):
    return {"component": component, "score": score, **extra}


class GradingTests(unittest.TestCase):
    def test_aitu_register_total_and_final_target(self):
        result = evaluate_grades([grade("attestation1", 82), grade("attestation2", 74), grade("final", 60)], target=70)
        self.assertEqual(result["register"], 78)
        self.assertEqual(result["total"], 70.8)
        self.assertEqual(result["required_final"], 58)
        self.assertTrue(result["passed"])
        self.assertEqual(result["grade"]["letter"], "C+")

    def test_minimum_final_and_each_attestation_cannot_be_compensated(self):
        low_final = evaluate_grades([grade("attestation1", 100), grade("attestation2", 100), grade("final", 49)])
        self.assertFalse(low_final["passed"])
        low_mid = evaluate_grades([grade("attestation1", 24), grade("attestation2", 100), grade("final", 100)])
        self.assertEqual(low_mid["register"], 62)
        self.assertFalse(low_mid["academic_admission"])
        self.assertFalse(low_mid["target_reachable"])

    def test_missing_is_unknown_not_zero_or_renormalized(self):
        result = evaluate_grades([grade("attestation1", 80), grade("attestation2", None)])
        self.assertIsNone(result["total"])
        self.assertIsNone(result["register"])
        self.assertIsNone(result["required_final"])
        mixed = evaluate_grades([grade("attestation1", 80), grade("attestation1", None), grade("attestation2", 100)])
        self.assertIsNone(mixed["attestation1"])

    def test_coursework_weights_are_not_invented(self):
        items = [grade("regmid", 100), grade("midterm", 50), grade("regend", 80), grade("endterm", 60)]
        result = evaluate_grades(items)
        self.assertIsNone(result["attestation1"])
        self.assertTrue(result["warnings"])
        configured = evaluate_grades(items, {"coursework_weight": 0.4, "exam_weight": 0.6})
        self.assertEqual(configured["attestation1"], 70)
        self.assertEqual(configured["attestation2"], 68)

    def test_normalization_relative_weights_and_unreachable_target(self):
        result = evaluate_grades([grade("attestation1", 40, max_score=50), grade("attestation2", 70, weight=1), grade("attestation2", 90, weight=3)], target=100)
        self.assertEqual(result["attestation1"], 80)
        self.assertEqual(result["attestation2"], 85)
        self.assertFalse(result["target_reachable"])
        self.assertGreater(result["required_final"], 100)

    def test_grade_boundaries_and_2025_fx_gpa(self):
        for value, expected in [(100, "A"), (94.99, "A-"), (89.99, "B+"), (70, "C+"), (50, "D"), (49.99, "FX"), (24.99, "F")]:
            self.assertEqual(letter_grade(value)["letter"], expected)
        self.assertEqual(letter_grade(30)["gpa"], 0)

    def test_invalid_scores_and_policies(self):
        for value in [-1, 101, True, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                evaluate_grades([grade("final", value)])
        for policy in [{"coursework_weight": 0.4}, {"coursework_weight": 0.6, "exam_weight": 0.6}, {"final_weight": 0}, {"extra": 5}]:
            with self.assertRaises(ValueError):
                policy_config(policy)


class PendingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = open_repository()
        cls.token, cls.student = cls.repo.login("student1", "student1")
        cls.admin_token, cls.admin = cls.repo.login("admin", "admin")

    def test_no_database_adapter_can_be_used(self):
        self.assertEqual(self.repo.source, "not-connected")
        with patch.dict(os.environ, {"CAMPUSPULSE_LMS_REPOSITORY": "sqlite-development"}), self.assertRaises(LmsError):
            open_repository()
        with self.assertRaises(LmsError):
            open_repository(seed_demo=True)
        with self.assertRaises(LmsError):
            open_repository(path="unused-local-file")

    def test_team_adapter_slot_is_disconnected_and_mcp_selects_same_adapter(self):
        with patch.dict(os.environ, {"CAMPUSPULSE_LMS_REPOSITORY": "team"}):
            repo = open_repository()
            self.assertEqual(repo.source, "team-unconfigured")
            self.assertFalse(repo.team_database_connected)
            token, actor = repo.login("student1", "student1")
            self.assertEqual(repo.mcp_environment()["CAMPUSPULSE_LMS_REPOSITORY"], "team")
            result = LmsTools(repo, actor).call("get_courses")
            self.assertEqual(result["status"], 503)
            self.assertFalse(result["data_access"][0]["executed"])
            self.assertNotIn(token, json.dumps(result))

    def test_roles_signed_sessions_logout_and_tampering(self):
        self.assertEqual(self.repo.principal(self.token).role, "student")
        with self.assertRaises(LmsError):
            self.repo.require_admin(self.student)
        body, signature = self.token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "="*(-len(body)%4)))
        payload["role"] = "admin"
        tampered = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + "." + signature
        with self.assertRaises(LmsError):
            self.repo.principal(tampered)
        token, _ = self.repo.login("student2", "student2")
        self.repo.logout(token)
        with self.assertRaises(LmsError):
            self.repo.principal(token)
        with self.assertRaises(LmsError):
            self.repo.login("admin", "bad-password")

    def test_reads_and_writes_fail_explicitly_without_fixtures(self):
        with self.assertRaises(LmsError) as read:
            self.repo.list("grades", self.student, "requested-course")
        self.assertEqual(read.exception.status, 503)
        access = read.exception.data_access[0]
        self.assertFalse(access["executed"])
        self.assertIsNone(access["rows"])
        with self.assertRaises(LmsError) as write:
            self.repo.save("courses", self.admin, {"archived": True}, "requested-record")
        self.assertEqual(write.exception.data_access[0]["operation"], "update")
        self.assertEqual(write.exception.data_access[0]["record_id"], "requested-record")

    def test_invalid_writes_are_rejected_before_database_attempts(self):
        for kind, payload in [("courses", {}), ("courses", {"archived": "yes"}),
                              ("grades", {"score": -1}), ("grade_items", {"component": "unknown"}),
                              ("lessons", {"starts_at": "2026-10-20T10:00:00"}),
                              ("materials", {"source_url": "file:///private"}), ("attendance", {"status": []})]:
            with self.subTest(kind=kind), self.assertRaises(ValueError) as caught:
                self.repo.save(kind, self.admin, payload, "requested-record")
            self.assertFalse(getattr(caught.exception, "data_access", []))

    def test_tool_validation_precedes_any_read(self):
        for name, args in [("get_grades", {"course_id": []}), ("get_grades", {"course_id": "requested-course", "target": 101}),
                           ("get_attendance", {"course_id": " "}), ("get_courses", []),
                           ("plan_study", {"hours_per_day": True}), ("plan_study", {"extra_busy": [{}]}),
                           ("read_materials", {"course_id": "requested-course", "query": ""})]:
            with self.subTest(name=name, args=args), patch.object(self.repo, "list") as read, self.assertRaises(ValueError):
                LmsTools(self.repo, self.student).call(name, args)
            read.assert_not_called()

    def test_generic_request_and_metadata_validation_without_records(self):
        # Schema metadata only, no academic rows or database fixture.
        catalog = catalog_metadata([{"name": "custom_resource", "label": "Custom", "description": "",
                                     "fields": {"id": "string", "category": "string"}, "filterable": ["category"]}])
        request = query_request({"resource": "custom_resource", "filters": {"category": "selected"}, "fields": ["id"]})
        self.assertEqual(check_query_catalog(request, catalog)["name"], "custom_resource")
        for bad in [{"resource": "custom_resource", "filters": {"student_id": "student2"}},
                    {"resource": "custom_resource", "limit": True}, {"resource": "custom_resource", "filters": {"category": {"sql": "text"}}},
                    {"resource": "custom_resource", "fields": ["id", "id"]}]:
            with self.assertRaises(LmsError):
                query_request(bad)
        with self.assertRaises(LmsError):
            check_query_catalog(query_request({"resource": "custom_resource", "fields": ["private_field"]}), catalog)
        with self.assertRaises(LmsError):
            check_query_catalog(query_request({"resource": "other_resource"}), catalog)

    def test_gateway_driver_failure_does_not_claim_no_execution_or_leak_details(self):
        from campuspulse.lms_team_adapter import TeamRepository
        class FailingGateway:
            source = "failure-check"
            connected = True
            def describe(self, actor):
                raise RuntimeError("private-driver-details")
        repo = TeamRepository(gateway=FailingGateway())
        with self.assertRaises(LmsError) as caught:
            repo.data_resources(self.student)
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn("private-driver-details", str(caught.exception))
        event = caught.exception.data_access[0]
        self.assertEqual(event["status"], "failed")
        self.assertIsNone(event["executed"])
        self.assertIsNone(event["rows"])

    def test_tools_show_attempted_collection_not_fake_success(self):
        result = LmsTools(self.repo, self.student).call("get_grades", {"course_id": "requested-course"})
        self.assertEqual(result["status"], 503)
        self.assertNotIn("calculation", result)
        self.assertEqual(result["data_access"][0]["type"], "database_request")
        self.assertEqual(result["data_access"][0]["status"], "not_connected")


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = open_repository()
        self.token, self.actor = self.repo.login("student1", "student1")

    async def test_real_mcp_reports_disconnected_source_without_model(self):
        with patch("google.genai.Client") as model:
            result = await run_lms_query(self.repo, self.token, {"message": "Оценки", "course_id": "requested-course"})
        model.assert_not_called()
        requests = [event for event in result["trace"] if event["type"] == "database_request"]
        self.assertTrue(requests)
        self.assertTrue(all(not event["executed"] for event in requests))
        self.assertIn("не подключена", result["answer"])
        self.assertNotIn(self.token, json.dumps(result))
        self.assertFalse(result["reasoning_loop"])

    async def test_gemini_is_blocked_while_database_is_pending(self):
        with patch("google.genai.Client") as model, self.assertRaises(LmsError) as caught:
            await run_lms_query(self.repo, self.token, {"message": "test", "engine": "gemini"})
        model.assert_not_called()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.repo._usage, {})

    async def test_identity_cannot_be_supplied_by_client_or_model(self):
        with self.assertRaises(LmsError):
            await run_lms_query(self.repo, self.token, {"message": "test", "student_id": "student2"})
        with self.assertRaises(LmsError):
            LmsTools(self.repo, self.actor).call("get_courses", {"student_id": "student2"})

    async def test_missing_page_context_still_reports_disconnection(self):
        result = await run_lms_query(self.repo, self.token, {"message": "Посещаемость"}, transport="direct")
        self.assertIn("не подключена", result["answer"])
        self.assertNotIn("получено заданий: 0", result["answer"])

    async def test_page_context_selects_tool_without_inventing_data(self):
        result = await run_lms_query(self.repo, self.token, {"message": "Покажи", "page": "attendance", "course_id": "requested-course"}, transport="direct")
        self.assertEqual([event["tool"] for event in result["trace"] if event["type"] == "tool_start"], ["get_attendance"])
        self.assertFalse(result["model_called"])

    async def test_real_mcp_hides_bootstrap_and_rechecks_parent_logout(self):
        events = []
        async with lms_tool_session(self.repo, self.actor, self.token, report=events.append) as call:
            self.assertNotIn("load_session", events[-1]["tools"])
            self.assertEqual(len(events[-1]["tools"]), 8)
            self.assertEqual((await call("get_courses", {}))["status"], 503)
            self.repo.logout(self.token)
            with self.assertRaises(LmsError) as caught:
                await call("get_courses", {})
            self.assertEqual(caught.exception.status, 401)

    async def test_team_template_uses_real_mcp_and_same_disconnected_source(self):
        with patch.dict(os.environ, {"CAMPUSPULSE_LMS_REPOSITORY": "team"}):
            repo = open_repository()
            token, _ = repo.login("student1", "student1")
        with patch("google.genai.Client") as model:
            result = await run_lms_query(repo, token, {"message": "Покажи предметы"})
        model.assert_not_called()
        access = [event for event in result["trace"] if event["type"] == "database_request"]
        self.assertEqual(access[0]["source"], "team-unconfigured")
        self.assertFalse(access[0]["executed"])
        self.assertEqual(result["transport"], "mcp")

    async def test_bad_context_never_starts_mcp_or_model(self):
        for bad in [{"page": []}, {"hours_per_day": 0}, {"target": float("nan")}, {"extra_busy": [{}]}]:
            with patch("campuspulse.lms_agent.lms_tool_session") as mcp, patch("google.genai.Client") as model, self.assertRaises(ValueError):
                await run_lms_query(self.repo, self.token, {"message": "Покажи", **bad})
            mcp.assert_not_called()
            model.assert_not_called()

    async def test_real_mcp_generic_database_catalog_and_arbitrary_resource(self):
        result = await run_lms_query(self.repo, self.token, {"message": "Покажи доступные данные базы"})
        self.assertEqual([event["tool"] for event in result["trace"] if event["type"] == "tool_start"], ["list_data_resources"])
        self.assertEqual(result["results"]["list_data_resources"]["status"], 503)
        result = await run_lms_query(self.repo, self.token, {"message": "Запрос данных", "data_query": {"resource": "custom_resource", "limit": 5}})
        access = [event for event in result["trace"] if event["type"] == "database_request"]
        self.assertEqual(access[0]["collection"], "custom_resource")
        self.assertFalse(access[0]["executed"])
        self.assertNotIn("items", result["results"]["query_data"])

    async def test_concrete_gateway_entry_point_is_recreated_in_mcp(self):
        target = "campuspulse.team_gateway:create_gateway"
        with patch.dict(os.environ, {"CAMPUSPULSE_LMS_REPOSITORY": "team", "CAMPUSPULSE_TEAM_GATEWAY": target}):
            repo = open_repository()
            token, _ = repo.login("student1", "student1")
        self.assertEqual(repo.mcp_environment()["CAMPUSPULSE_TEAM_GATEWAY"], target)
        result = await run_lms_query(repo, token, {"message": "Покажи доступные данные базы"})
        self.assertEqual(result["results"]["list_data_resources"]["source"], "team-unconfigured")
        self.assertEqual(result["results"]["list_data_resources"]["status"], 503)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = open_repository()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LmsHandler)
        cls.server.repository, cls.server.transport = cls.repo, "mcp"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def request(self, method, path, data=None, cookie=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        supplied = {"Content-Type": "application/json", **(headers or {})}
        if cookie:
            supplied["Cookie"] = cookie
        conn.request(method, path, json.dumps(data).encode() if data is not None else None, supplied)
        response = conn.getresponse(); body = response.read().decode()
        result = {"status": response.status, "body": body, "cookie": response.getheader("Set-Cookie"), "type": response.getheader("Content-Type")}
        if "application/json" in result["type"]:
            result["json"] = json.loads(body)
        conn.close(); return result

    def login(self, username="student1"):
        result = self.request("POST", "/api/v1/auth/login", {"username": username, "password": username})
        self.assertEqual(result["status"], 200)
        self.assertIn("HttpOnly", result["cookie"])
        return result["cookie"].split(";",1)[0]

    def test_team_frontend_is_same_origin_without_legacy_bypass(self):
        for path in ["/", "/lms", "/lms/"]:
            response = self.request("GET", path)
            self.assertEqual(response["status"], 200)
            self.assertIn("text/html", response["type"])
            self.assertIn('/lms-assets/app.mjs', response["body"])
            self.assertNotIn("fonts.googleapis.com", response["body"])
        self.assertTrue(self.request("GET", "/api/v1/status")["json"]["frontend_connected"])
        self.assertEqual(self.request("GET", "/api/v1/status")["json"]["source"], "not-connected")
        self.assertEqual(self.request("POST", "/api/query", {"message": "test"})["status"], 404)
        self.assertEqual(self.request("GET", "/app.js")["status"], 404)
        self.assertEqual(self.request("POST", "/api/gemini/connect", {"api_key": "fake"})["status"], 404)

    def test_static_allowlist_blocks_project_files_and_keeps_host_checks(self):
        from campuspulse.lms_server import FRONTEND_FILES
        for path in FRONTEND_FILES:
            response = self.request("GET", path)
            self.assertEqual(response["status"], 200, path)
        for path in ["/lms-assets/../.env", "/lms-assets/%2e%2e/README.md", "/lms-assets/..%5c.env", "/.env", "/campuspulse/team_gateway.py", "/frontend-draft/web/index.html", "/frontend-team-source/app.js", "/lms-assets/missing.mjs"]:
            self.assertEqual(self.request("GET", path)["status"], 404, path)
        self.assertEqual(self.request("GET", "/lms-assets/app.mjs", headers={"Host": "evil.example"})["status"], 403)
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/")
        response = conn.getresponse()
        self.assertIn("script-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertNotIn("unsafe-inline", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        response.read(); conn.close()

    def test_student_cannot_write_or_choose_another_identity(self):
        cookie = self.login()
        self.assertEqual(self.request("GET", "/api/v1/admin/users", cookie=cookie)["status"], 403)
        self.assertEqual(self.request("POST", "/api/v1/admin/courses", {"name": "fake"}, cookie)["status"], 403)
        self.assertEqual(self.request("GET", "/api/v1/grades?student_id=student2", cookie=cookie)["status"], 400)
        self.assertEqual(self.request("POST", "/api/v1/agent/query", {"message": "test", "student_id": "student2"}, cookie)["status"], 400)

    def test_data_endpoints_return_503_and_attempt_metadata(self):
        cookie = self.login()
        for path in ["/api/v1/courses", "/api/v1/grades?course_id=course", "/api/v1/grade-summary?course_id=course", "/api/v1/attendance-summary?course_id=course"]:
            result = self.request("GET", path, cookie=cookie)
            self.assertEqual(result["status"], 503, result)
            self.assertFalse(result["json"]["data_access"][0]["executed"])
        admin = self.login("admin")
        result = self.request("PATCH", "/api/v1/admin/courses/requested-record", {"archived": True}, admin)
        self.assertEqual(result["status"], 503)
        self.assertEqual(result["json"]["data_access"][0]["operation"], "update")

    def test_sse_is_honest_about_requests_that_did_not_execute(self):
        cookie = self.login()
        with patch("google.genai.Client") as model:
            result = self.request("POST", "/api/v1/agent/stream", {"message": "Оценки", "course_id": "course"}, cookie)
        model.assert_not_called()
        events = [json.loads(line[6:]) for line in result["body"].splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "complete")
        self.assertTrue(any(event["type"] == "mcp_ready" and len(event["tools"]) == 8 for event in events))
        self.assertTrue(all(event.get("transport") == "mcp" for event in events if event["type"] == "tool_start"))
        self.assertTrue(any(event["type"] == "database_request" and event["executed"] is False for event in events))
        self.assertNotIn(cookie.split("=",1)[1], result["body"])

    def test_auth_logout_and_calculator_without_any_database(self):
        self.assertEqual(self.request("GET", "/api/v1/me")["status"], 401)
        cookie = self.login()
        result = self.request("POST", "/api/v1/grading/calculate", {"items": [grade("attestation1",82), grade("attestation2",74)], "target": 70}, cookie)
        self.assertEqual(result["status"], 200)
        self.assertFalse(result["json"]["database_accessed"])
        self.assertEqual(result["json"]["calculation"]["required_final"], 58)
        self.request("POST", "/api/v1/auth/logout", {}, cookie)
        self.assertEqual(self.request("GET", "/api/v1/me", cookie=cookie)["status"], 401)

    def test_host_and_origin_are_checked(self):
        self.assertEqual(self.request("GET", "/api/v1/status", headers={"Host":"evil.example"})["status"], 403)
        self.assertEqual(self.request("POST", "/api/v1/auth/login", {"username":"admin", "password":"admin"}, headers={"Origin":"https://evil.example"})["status"], 403)

    def test_every_collection_reports_attempts_and_never_returns_records(self):
        student, admin = self.login(), self.login("admin")
        for kind in sorted(KINDS):
            for prefix, cookie in [("", student), ("admin/", admin)]:
                with self.subTest(kind=kind, prefix=prefix):
                    result = self.request("GET", "/api/v1/" + prefix + kind, cookie=cookie)
                    self.assertEqual(result["status"], 503)
                    self.assertNotIn("items", result["json"])
                    event = result["json"]["data_access"][0]
                    self.assertEqual(event["collection"], kind)
                    self.assertEqual(event["filters"]["student_id"], "student1" if not prefix else None)

    def test_query_validation_and_methods(self):
        cookie = self.login()
        for path in ["grades?course_id=", "grades?course_id=a&course_id=b", "grades?target=70", "me?course_id=a"]:
            self.assertEqual(self.request("GET", "/api/v1/" + path, cookie=cookie)["status"], 400)
        self.assertEqual(self.request("POST", "/api/v1/courses", {}, cookie)["status"], 405)
        self.assertEqual(self.request("GET", "/api/v1/unknown", cookie=cookie)["status"], 404)
        self.assertEqual(self.request("POST", "/api/v1/auth/logout", {"extra": True}, cookie)["status"], 400)
        self.assertEqual(self.request("POST", "/api/v1/agent/query", {"message": "Покажи", "engine": "gemini"}, cookie)["status"], 503)
        admin = self.login("admin")
        self.assertEqual(self.request("POST", "/api/v1/agent/query", {"message": "Покажи"}, admin)["status"], 403)
        self.assertEqual(self.request("GET", "/api/v1/courses", cookie=admin)["status"], 403)

    def test_generic_gateway_api_works_for_both_roles_without_fake_results(self):
        for username in ["student1", "admin"]:
            cookie = self.login(username)
            self.assertEqual(self.request("GET", "/api/v1/data/resources", cookie=cookie)["status"], 503)
            result = self.request("POST", "/api/v1/data/query", {"resource": "custom_resource", "limit": 5}, cookie)
            self.assertEqual(result["status"], 503)
            self.assertEqual(result["json"]["data_access"][0]["collection"], "custom_resource")
            self.assertNotIn("items", result["json"])

    def test_strict_json_and_safe_errors(self):
        for raw in [b'{"username":"admin","username":"student1","password":"admin"}', b'{"username":NaN,"password":"admin"}', b'[]', b'{']:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/api/v1/auth/login", raw, {"Content-Type": "application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            self.assertNotIn("Traceback", response.read().decode())
            conn.close()

    def test_login_throttle_and_expired_session(self):
        from campuspulse.lms_server import LOGIN_ATTEMPTS, LOGIN_LOCK
        with LOGIN_LOCK:
            LOGIN_ATTEMPTS.clear()
        for _ in range(5):
            self.assertEqual(self.request("POST", "/api/v1/auth/login", {"username": "unknown", "password": "invalid"})["status"], 401)
        self.assertEqual(self.request("POST", "/api/v1/auth/login", {"username": "unknown", "password": "invalid"})["status"], 429)
        cookie = self.login()
        with patch("campuspulse.lms_pending.time.time", return_value=time.time() + 28801):
            self.assertEqual(self.request("GET", "/api/v1/me", cookie=cookie)["status"], 401)

    def test_sse_failure_has_terminal_error_and_no_model_call(self):
        cookie = self.login()
        with patch("google.genai.Client") as model:
            result = self.request("POST", "/api/v1/agent/stream", {"message": "Покажи", "engine": "gemini"}, cookie)
        model.assert_not_called()
        events = [json.loads(line[6:]) for line in result["body"].splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["status"], 503)
        self.assertNotIn("complete", [event["type"] for event in events])

    def test_openapi_is_available_and_has_all_collection_routes(self):
        result = self.request("GET", "/api/v1/openapi.json")
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["json"]["openapi"], "3.1.0")
        for kind in KINDS:
            self.assertIn("patch", result["json"]["paths"][f"/api/v1/admin/{kind}/{{id}}"])
        self.assertEqual(result["json"], openapi_document())

    def test_vertex_status_checks_configuration_without_adc_or_model(self):
        env = {"GOOGLE_CLOUD_PROJECT": "unit-test-project", "GOOGLE_CLOUD_LOCATION": "global",
               "CAMPUSPULSE_VERTEX_MODEL": "gemini-test-model", "CAMPUSPULSE_ALLOW_CLOUD": "1"}
        with patch.dict(os.environ, env), patch("google.auth.default") as adc, patch("google.genai.Client") as client:
            result = self.request("GET", "/api/v1/status")
        self.assertTrue(result["json"]["vertex"]["configured"])
        self.assertFalse(result["json"]["vertex"]["adc_verified"])
        self.assertFalse(result["json"]["vertex"]["live_verified"])
        self.assertFalse(result["json"]["team_database_connected"])
        adc.assert_not_called()
        client.assert_not_called()


