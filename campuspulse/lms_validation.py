"""Request validation shared by HTTP, tools and the pending adapter.

This checks shape only. Database relationships and authorization must also be
checked transactionally by the team's adapter; no records are created here.
"""
from urllib.parse import urlparse

from .domain import parse_time, validate_context
from .grading import COMPONENTS, number, policy_config
from .lms_store import FIELDS, KINDS, LmsError, text

PAGES = {"overview", "courses", "assignments", "grades", "attendance", "materials", "schedule", "plan"}
REQUIRED = {
    "courses": {"code", "name"},
    "enrollments": {"course_id", "student_id"},
    "assignments": {"course_id", "title"},
    "grade_items": {"course_id", "title", "component"},
    "grades": {"course_id", "student_id", "item_id", "score"},
    "lessons": {"course_id", "title", "starts_at", "ends_at"},
    "attendance": {"course_id", "student_id", "lesson_id", "status"},
    "materials": {"course_id", "name", "text"},
}


def identifier(value, name="course_id"):
    value = text(value, name, 120)
    if any(ord(char) < 32 or char in "/\\?#" for char in value):
        raise LmsError(f"Некорректный {name}.")
    return value


def collection(kind):
    if kind not in KINDS:
        raise LmsError("Коллекция не найдена.", 404)


def planning_options(hours=3, busy=None):
    busy = [] if busy is None else busy
    if not isinstance(busy, list) or len(busy) > 100 or any(
        not isinstance(block, dict) or set(block) != {"start", "end"} for block in busy
    ):
        raise LmsError("extra_busy: до 100 объектов start/end с часовым поясом.")
    try:
        context = validate_context({"hours_per_day": hours, "busy": busy})
    except (ValueError, TypeError, KeyError) as error:
        raise LmsError("Некорректная нагрузка или занятые интервалы.") from error
    return context["hours_per_day"], context["busy"]


def tool_arguments(spec, args):
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise LmsError("Аргументы инструмента должны быть объектом.")
    schema = spec["inputSchema"]
    if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
        raise LmsError("Недопустимые аргументы инструмента.")
    clean = dict(args)
    if spec["name"] == "query_data":
        from .lms_data import query_request
        return query_request(clean)
    if "course_id" in clean:
        clean["course_id"] = identifier(clean["course_id"])
    if "target" in clean:
        clean["target"] = float(number(clean["target"], "Целевой итог"))
    if "query" in clean:
        clean["query"] = text(clean["query"], "query", 500)
    if spec["name"] == "plan_study":
        clean["hours_per_day"], clean["extra_busy"] = planning_options(clean.get("hours_per_day", 3), clean.get("extra_busy", []))
    return clean


def agent_payload(payload):
    allowed = {"message", "course_id", "page", "engine", "target", "hours_per_day", "extra_busy", "data_query"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise LmsError("Неизвестные поля запроса. Идентификатор студента берётся из сессии.")
    clean = dict(payload)
    if "data_query" in clean:
        from .lms_data import query_request
        clean["data_query"] = query_request(clean["data_query"])
    clean["message"] = text(clean.get("message"), "message", 5000)
    if clean.get("course_id") is not None:
        clean["course_id"] = identifier(clean["course_id"])
    if not isinstance(clean.get("page", "overview"), str) or clean.get("page", "overview") not in PAGES:
        raise LmsError("Неизвестная страница LMS.")
    if not isinstance(clean.get("engine", "local"), str) or clean.get("engine", "local") not in {"local", "gemini"}:
        raise LmsError("Режим: local или gemini.")
    if "target" in clean:
        clean["target"] = float(number(clean["target"], "Целевой итог"))
    clean["hours_per_day"], clean["extra_busy"] = planning_options(clean.get("hours_per_day", 3), clean.get("extra_busy", []))
    return clean


def record_payload(kind, payload, record_id=None):
    collection(kind)
    if not isinstance(payload, dict) or not payload or set(payload) - FIELDS[kind]:
        raise LmsError("Нужен непустой объект с разрешёнными полями коллекции.")
    if record_id is None and REQUIRED[kind] - set(payload):
        raise LmsError("Отсутствуют обязательные поля: " + ", ".join(sorted(REQUIRED[kind] - set(payload))))
    if record_id is not None:
        identifier(record_id, "record_id")
    clean = dict(payload)
    for key, value in payload.items():
        if key.endswith("_id"):
            clean[key] = identifier(value, key)
        elif key in {"code", "name", "title", "description", "text", "comment", "kind"}:
            limit = {"code": 80, "name": 200, "description": 10000, "text": 50000, "comment": 2000}.get(key, 200)
            clean[key] = text(value, key, limit, required=key not in {"description", "comment"})
        elif key == "archived":
            if not isinstance(value, bool):
                raise LmsError("archived: нужно логическое значение.")
        elif key == "component":
            if not isinstance(value, str) or value not in COMPONENTS:
                raise LmsError("Неизвестный компонент оценки.")
        elif key == "status":
            if not isinstance(value, str) or value not in {"present", "absent", "late", "excused"}:
                raise LmsError("Неизвестный статус посещаемости.")
        elif key in {"due", "starts_at", "ends_at"}:
            if key == "due" and value is None:
                continue
            if not isinstance(value, str):
                raise LmsError(f"{key}: нужна ISO-дата с часовым поясом.")
            clean[key] = parse_time(value).isoformat()
        elif key in {"week", "minutes"}:
            if value is None:
                continue  # Unknown, never an invented week or effort estimate.
            low, high = (1, 100) if key == "week" else (10, 2400)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise LmsError(f"{key}: целое число от {low} до {high} или null.")
        elif key in {"score", "max_score", "weight"}:
            if key == "score" and value is None:
                continue
            low, high = {"score": (0, 100000), "max_score": (0.001, 100000), "weight": (0.001, 1000)}[key]
            clean[key] = float(number(value, key, low, high))
        elif key == "policy":
            clean[key] = policy_config(value)
        elif key == "source_url":
            clean[key] = text(value, key, 2000, required=False)
            if value and (urlparse(value).scheme not in {"https", "http"} or not urlparse(value).netloc):
                raise LmsError("source_url: нужна ссылка http/https.")
    if "starts_at" in clean and "ends_at" in clean and clean["ends_at"] <= clean["starts_at"]:
        raise LmsError("Конец занятия должен быть позже начала.")
    return clean


def student_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"username", "password", "name"}:
        raise LmsError("Нужны только username, password и name.")
    return {"username": identifier(payload["username"], "username"),
            "password": text(payload["password"], "password", 512), "name": text(payload["name"], "name", 200)}
