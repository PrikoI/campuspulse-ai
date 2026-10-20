"""LMS contracts and validation helpers. No database implementation is active."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol


KINDS = {"courses", "enrollments", "assignments", "grade_items", "grades", "lessons", "attendance", "materials"}
FIELDS = {
    "courses": {"code", "name", "policy", "archived"},
    "enrollments": {"course_id", "student_id", "archived"},
    "assignments": {"course_id", "title", "description", "due", "minutes", "week"},
    "grade_items": {"course_id", "title", "component", "max_score", "weight", "week"},
    "grades": {"course_id", "student_id", "item_id", "score", "comment"},
    "lessons": {"course_id", "title", "starts_at", "ends_at", "kind"},
    "attendance": {"course_id", "student_id", "lesson_id", "status"},
    "materials": {"course_id", "name", "text", "week", "source_url"},
}


class LmsError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    name: str

    def public(self):
        return {"id": self.user_id, "role": self.role, "name": self.name}


class LmsRepository(Protocol):
    """Team integration contract; see docs/LMS_DATABASE_CONTRACT.md.

    list/save normalize native DB fields into FIELDS plus a stable string id.
    Enforce permissions and relationships in the adapter, not just in HTTP.
    An unavailable source raises 503; never fabricate rows or return [] on an
    outage. API and MCP construct independent instances against the same source.
    """
    source: str
    team_database_connected: bool
    def list(self, kind: str, actor: Principal, course_id=None, audit=None) -> list[dict]: ...
    def save(self, kind: str, actor: Principal, payload: dict, record_id=None) -> dict: ...
    def principal(self, session_token: str) -> Principal: ...
    def login(self, username: str, password: str) -> tuple[str, Principal]: ...
    def logout(self, token: str): ...
    def users(self, actor: Principal) -> list[dict]: ...
    def create_student(self, actor: Principal, payload: dict) -> dict: ...
    def allowed_courses(self, actor: Principal) -> set[str]: ...
    def check_course(self, actor: Principal, course_id: str): ...
    def require_admin(self, actor: Principal): ...
    def data_resources(self, actor: Principal) -> dict: ...
    def query_data(self, actor: Principal, request: dict) -> dict: ...
    def reserve_model_query(self, actor: Principal, maximum=10): ...
    def mcp_environment(self) -> dict: ...


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260000).hex()
    return f"{salt}:{digest}"


def text(value, name, limit=200, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise LmsError(f"{name}: строка от {1 if required else 0} до {limit} символов.")
    return value.strip()


