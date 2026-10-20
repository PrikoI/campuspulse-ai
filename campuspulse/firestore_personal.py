"""Owner-scoped tasks/settings and signed, expiring user-reviewed changes.

Proposals are stateless: preparing an agent action does not write a document.
Only the authenticated HTTP confirmation endpoint applies a signed proposal.
"""
import base64
import hmac
import json
import time
import uuid

from .domain import validate_context
from .lms_store import LmsError
from .lms_json import json_value
from .lms_validation import identifier, planning_options

TASK_FIELDS = {"title", "course", "due", "minutes", "done"}


def personal_change(raw):
    if not isinstance(raw, dict) or set(raw) - {"target", "operation", "record_id", "payload"}:
        raise LmsError("Изменение: target, operation, record_id и payload.")
    target, operation = raw.get("target"), raw.get("operation", "save")
    if target not in {"task", "preferences"} or operation not in {"save", "delete"}:
        raise LmsError("Допустимы task/preferences и save/delete.")
    key = raw.get("record_id")
    if key is not None:
        key = identifier(key, "record_id")
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise LmsError("payload должен быть объектом.")
    if target == "preferences":
        if key is not None or operation != "save" or set(payload) != {"hours_per_day"}:
            raise LmsError("Настройки: только hours_per_day от 1 до 8.")
        planning_options(payload["hours_per_day"])
    elif operation == "delete":
        if key is None or payload:
            raise LmsError("Для удаления нужен record_id и пустой payload.")
    elif not payload or set(payload) - TASK_FIELDS:
        raise LmsError("Задача: title, course, due, minutes, done.")
    return {"target": target, "operation": operation, "record_id": key, "payload": payload}


def task_record(key, raw):
    if "done" in raw and type(raw["done"]) is not bool:
        raise LmsError("done: нужно логическое значение.")
    if "course" in raw and (not isinstance(raw["course"], str) or len(raw["course"]) > 80):
        raise LmsError("course: строка до 80 символов.")
    if "title" in raw and (not isinstance(raw["title"], str) or not raw["title"].strip() or len(raw["title"]) > 200):
        raise LmsError("title: строка от 1 до 200 символов.")
    if "due" in raw and raw["due"] is not None and not isinstance(raw["due"], str):
        raise LmsError("due: ISO-дата с часовым поясом или null.")
    try:
        task = validate_context({"tasks": [{**raw, "id": key}]})["tasks"][0]
    except (ValueError, TypeError, KeyError):
        raise LmsError("Некорректные поля личной задачи или дата без часового пояса.") from None
    return {field: task[field] for field in TASK_FIELDS}


class PersonalDataMixin:
    def _personal_path(self, actor, target, key=None):
        self._actor(actor)
        if actor.role != "student":
            raise LmsError("Личные задачи доступны только студенту.", 403)
        return f"users/{actor.user_id}" + (f"/tasks/{identifier(key, 'record_id')}" if target == "task" else "")

    def personal_data(self, actor):
        path = self._personal_path(actor, "preferences")
        def read(tx):
            profile = self.storage.get(path, tx) or {}
            preferences = profile.get("preferences", {"hours_per_day": 3})
            hours, _ = planning_options(preferences.get("hours_per_day", 3))
            rows = self._scan(path + "/tasks", [], tx)
            tasks = [{"id": key, **task_record(key, self._json(row)), "source": self.source, "url": None}
                     for key, row in sorted(rows)]
            return {"tasks": tasks, "preferences": {"hours_per_day": hours}, "source": self.source,
                    "team_database_connected": True,
                    "data_access": [self._event("personal_data", actor, "read", len(tasks) + bool(profile))]}
        return self._run(actor, "personal_data", "read", read, read_only=True)

    @staticmethod
    def _json(row):
        return json_value(row)

    @staticmethod
    def _digest(value):
        import hashlib
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    def prepare_personal_change(self, actor, change):
        change = personal_change(change)
        key = change["record_id"] or uuid.uuid4().hex
        path = self._personal_path(actor, change["target"], key)
        def prepare(tx):
            current = self.storage.get(path, tx)
            previous = self._json(current) if change["target"] == "task" else (current or {}).get("preferences")
            if change["record_id"] is not None and current is None:
                raise LmsError("Личная задача не найдена.", 404)
            if change["target"] == "task":
                after = None if change["operation"] == "delete" else task_record(key, {**(previous or {}), **change["payload"]})
                public_before = {field: previous[field] for field in TASK_FIELDS if field in (previous or {})}
            else:
                hours, _ = planning_options(change["payload"]["hours_per_day"])
                after = {"hours_per_day": hours}
                public_before = {"hours_per_day": previous["hours_per_day"]} if previous and "hours_per_day" in previous else None
            if previous is None:
                public_before = None
            proposal = {"actor": actor.user_id, "target": change["target"], "operation": change["operation"],
                        "record_id": key if change["target"] == "task" else None,
                        "before": self._digest(previous), "after": after, "expires": int(time.time()) + 600}
            body = base64.urlsafe_b64encode(json.dumps(proposal, ensure_ascii=False).encode()).decode().rstrip("=")
            return {"proposal": body + "." + self._signature(body), "change": {"target": proposal["target"],
                    "operation": proposal["operation"], "record_id": proposal["record_id"], "before": public_before, "after": after},
                    "confirmation_required": True, "expires_at": proposal["expires"], "written": False,
                    "source": self.source, "team_database_connected": True,
                    "data_access": [self._event("personal_data", actor, "read", int(current is not None))]}
        return self._run(actor, "personal_data", "read", prepare, read_only=True)

    def confirm_personal_change(self, actor, token):
        self._actor(actor)
        try:
            if not isinstance(token, str) or len(token) > 10000:
                raise ValueError()
            body, signature = token.rsplit(".", 1)
            if not hmac.compare_digest(signature, self._signature(body)):
                raise ValueError()
            proposal = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if proposal["actor"] != actor.user_id or proposal["expires"] <= time.time():
                raise ValueError()
        except Exception:
            raise LmsError("Подтверждение недействительно или истекло.", 403) from None
        path = self._personal_path(actor, proposal["target"], proposal["record_id"])
        def apply(tx):
            current = self.storage.get(path, tx)
            previous = self._json(current) if proposal["target"] == "task" else (current or {}).get("preferences")
            if previous == proposal["after"]:
                return {"applied": False, "already_applied": True, "record_id": proposal["record_id"]}
            if self._digest(previous) != proposal["before"]:
                raise LmsError("Данные изменились. Подготовьте новое изменение для проверки.", 409)
            if proposal["operation"] == "delete":
                self.storage.delete(tx, path)
            elif proposal["target"] == "task":
                from .firestore_repository import stored_record
                self.storage.put(tx, path, stored_record("assignments", proposal["after"]))
            else:
                self.storage.put(tx, path, {**(current or {}), "preferences": proposal["after"]})
            return {"applied": True, "record_id": proposal["record_id"]}
        return self._run(actor, "personal_data", proposal["operation"], apply)
