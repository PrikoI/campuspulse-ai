"""Explicit live REST/MCP smoke check, isolated beneath system_tests/{unique run}.

No deployment, model calls, billing changes or production document mutations.
Run with --live to allow cloud operations. Test fixtures are retained for review.
"""
import argparse
import http.client
import json
import os
import threading
import uuid
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from campuspulse.firestore_repository import FirestoreRepository
from campuspulse.lms_server import LmsHandler


@contextmanager
def backend(factory, transport):
    server = ThreadingHTTPServer(("127.0.0.1", 0), LmsHandler)
    server.repository, server.transport = factory(), transport
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


class Client:
    def __init__(self, port):
        self.port, self.cookie = port, ""

    def request(self, method, path, payload=None, expected=200):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=100)
        try:
            headers = {"Content-Type": "application/json"}
            if self.cookie:
                headers["Cookie"] = self.cookie
            conn.request(method, "/api/v1/" + path, json.dumps(payload) if payload is not None else None, headers)
            response = conn.getresponse()
            data = json.loads(response.read())
            if response.status != expected:
                # Never print cookies, proposal bodies or remote exception details.
                raise RuntimeError(f"Backend check failed at {method} {path.split('?')[0]} (HTTP {response.status}).")
            cookie = response.getheader("Set-Cookie")
            if cookie:
                self.cookie = cookie.split(";", 1)[0]
            return data
        finally:
            conn.close()

    def login(self, username):
        self.request("POST", "auth/login", {"username": username, "password": username})


def run_check(factory, transport="mcp"):
    """Exercise the unchanged backend endpoints; injectable for offline testing."""
    with backend(factory, transport) as port:
        admin, student, other = Client(port), Client(port), Client(port)
        admin.login("admin"); student.login("student1"); other.login("student2")
        course = admin.request("POST", "admin/courses", {"code": "INTEGRATION", "name": "Isolated backend check"}, expected=201)["item"]
        cid = course["id"]
        admin.request("POST", "admin/enrollments", {"course_id": cid, "student_id": "student1"}, expected=201)
        if len(student.request("GET", "courses")["items"]) != 1:
            raise RuntimeError("Course batch read verification failed.")
        assignment = admin.request("POST", "admin/assignments", {"course_id": cid, "title": "Backend check task", "due": "2030-01-01T18:00:00+05:00", "minutes": 30}, expected=201)["item"]
        aid = assignment["id"]
        admin.request("POST", "admin/lessons", {"course_id": cid, "title": "Backend check lesson", "starts_at": "2030-01-01T10:00:00+05:00", "ends_at": "2030-01-01T11:00:00+05:00"}, expected=201)
        query = {"resource": "assignments", "filters": {"id": aid}, "fields": ["id", "title", "due"], "limit": 1}
        result = student.request("POST", "data/query", query)
        if result["items"] != [{"id": aid, "title": assignment["title"], "due": assignment["due"]}]:
            raise RuntimeError("Unexpected JSON assignment result.")
        other.request("GET", "assignments?course_id=" + cid, expected=403)
        if student.request("POST", "data/query", {"resource": "assignments", "filters": {"title": "not-present"}, "limit": 1})["items"]:
            raise RuntimeError("Empty result verification failed.")
        admin.request("PATCH", "admin/assignments/" + aid, {"title": "Updated backend task"})
        action = student.request("POST", "actions/prepare", {"target": "task", "payload": {"title": "Personal backend check", "minutes": 30}})
        student.request("POST", "actions/confirm", {"proposal": action["proposal"], "confirmed": True})
        if other.request("GET", "personal")["tasks"]:
            raise RuntimeError("Personal task isolation failed.")
    # New repository/server, same namespaced Firestore; no migration or fixture reset.
    with backend(factory, transport) as port:
        student = Client(port); student.login("student1")
        result = student.request("POST", "agent/query", {"message": "Check stored task", "data_query": query})
        item = result["results"]["query_data"]["items"][0]
        if item["title"] != "Updated backend task" or result["model_called"]:
            raise RuntimeError("Persistence/MCP verification failed.")
        lessons = student.request("POST", "data/query", {"resource": "lessons", "filters": {"course_id": cid}, "fields": ["starts_at", "ends_at"], "limit": 1})
        if len(lessons["items"]) != 1 or len(student.request("GET", "personal")["tasks"]) != 1:
            raise RuntimeError("Schedule or personal persistence verification failed.")
    return {"rest_json": True, "update": True, "user_isolation": True,
            "personal_confirmation": True, "restart": True, "schedule": True,
            "transport": transport, "model_called": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow test reads/writes in real Firestore")
    args = parser.parse_args()
    if not args.live:
        parser.error("Cloud check requires explicit --live; no cloud operations were performed.")
    namespace = "backend-" + uuid.uuid4().hex
    os.environ["CAMPUSPULSE_FIRESTORE_TEST_NAMESPACE"] = namespace
    # The MCP child receives this same explicitly validated namespace.
    try:
        result = run_check(FirestoreRepository)
    except Exception:
        print(json.dumps({"success": False, "test_namespace": "system_tests/" + namespace,
                          "error": "Backend integration check failed; inspect configuration, quota and indexes. Test fixtures were retained."}))
        return 1
    print(json.dumps({"success": True, "test_namespace": "system_tests/" + namespace,
                      "checks": result, "fixtures_retained": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
