"""No database connection and no academic fixtures.

Only temporary login sessions and AI rate counters live in process memory.
Data requests fail explicitly and describe the attempted operation for debugging.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime

from .domain import TZ
from .lms_store import LmsError, Principal, password_hash
from .lms_validation import collection, identifier, record_payload, student_payload


class PendingRepository:
    source = "not-connected"
    team_database_connected = False

    def __init__(self):
        self.secret = os.getenv("CAMPUSPULSE_LMS_SESSION_SECRET") or secrets.token_urlsafe(48)
        self._credentials = {uid: password_hash(uid) for uid in ["admin", "student1", "student2"]}
        self._revoked = set()
        self._usage = {}
        self._lock = threading.Lock()

    def _signature(self, body):
        return hmac.new(self.secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 512:
            raise LmsError("Неверный логин или пароль.", 401)
        stored = self._credentials.get(username, self._credentials["student1"])
        valid = hmac.compare_digest(stored, password_hash(password, stored.split(":")[0]))
        if username not in self._credentials or not valid:
            raise LmsError("Неверный логин или пароль.", 401)
        actor = Principal(username, "admin" if username == "admin" else "student", "Преподаватель" if username == "admin" else f"Тестовая сессия {username}")
        payload = {**actor.public(), "exp": time.time()+28800, "nonce": secrets.token_hex(16)}
        body = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip("=")
        return body + "." + self._signature(body), actor

    def principal(self, session_token):
        try:
            if not isinstance(session_token, str) or len(session_token) > 2048:
                raise ValueError()
            body, signature = session_token.rsplit(".", 1)
            if not hmac.compare_digest(signature, self._signature(body)):
                raise ValueError()
            with self._lock:
                if hashlib.sha256(session_token.encode()).hexdigest() in self._revoked:
                    raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if payload["exp"] <= time.time() or payload["role"] not in {"student", "admin"}:
                raise ValueError()
            return Principal(payload["id"], payload["role"], payload["name"])
        except Exception:
            raise LmsError("Войдите в LMS. Сессия отсутствует или истекла.", 401) from None

    def logout(self, token):
        with self._lock:
            self._revoked.add(hashlib.sha256(str(token).encode()).hexdigest())

    @staticmethod
    def require_admin(actor):
        if actor.role != "admin":
            raise LmsError("Действие доступно только преподавателю.", 403)

    def unavailable(self, collection, actor, course_id=None, operation="read", audit=None, record_id=None):
        event = {"type": "database_request", "operation": operation, "collection": collection,
                 "filters": {"course_id": course_id, "student_id": actor.user_id if actor.role == "student" else None},
                 "source": self.source, "status": "not_connected", "executed": False, "rows": None,
                 "at": datetime.now(TZ).isoformat()}
        if record_id is not None:
            event["record_id"] = record_id
        if audit is not None:
            audit.append(event)
        error = LmsError("Командная база данных ещё не подключена. Запрос подготовлен, но не выполнен; учебные данные не подменяются примерами.", 503)
        error.data_access = [event]
        raise error

    def list(self, kind, actor, course_id=None, audit=None):
        collection(kind)
        if course_id is not None:
            course_id = identifier(course_id)
        self.unavailable(kind, actor, course_id, audit=audit)

    def save(self, kind, actor, payload, record_id=None):
        self.require_admin(actor)
        payload = record_payload(kind, payload, record_id)
        self.unavailable(kind, actor, payload.get("course_id"), operation="update" if record_id else "create", record_id=record_id)

    def users(self, actor):
        self.require_admin(actor)
        self.unavailable("users", actor)

    def create_student(self, actor, payload):
        self.require_admin(actor)
        student_payload(payload)
        self.unavailable("users", actor, operation="create")

    def allowed_courses(self, actor):
        self.unavailable("enrollments", actor)

    def check_course(self, actor, course_id):
        self.unavailable("enrollments", actor, course_id)

    def data_resources(self, actor):
        self.unavailable("resource_catalog", actor, operation="describe")

    def query_data(self, actor, request):
        from .lms_data import query_request
        request = query_request(request)
        self.unavailable(request["resource"], actor)

    def mcp_environment(self):
        return {"CAMPUSPULSE_LMS_REPOSITORY": "pending", "CAMPUSPULSE_LMS_SESSION_SECRET": self.secret}

    def reserve_model_query(self, actor, maximum=10):
        day = datetime.now(TZ).date().isoformat()
        with self._lock:
            key = (actor.user_id, day)
            if self._usage.get(key, 0) >= maximum or sum(count for (uid, date), count in self._usage.items() if date == day) >= 20:
                raise LmsError("Лимит AI-запросов исчерпан. Локальные расчёты доступны.", 429)
            self._usage[key] = self._usage.get(key, 0)+1
