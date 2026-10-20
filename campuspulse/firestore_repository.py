"""Firestore implementation of the existing LMS Repository/DataGateway contracts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from contextvars import ContextVar

from .domain import TZ, parse_time
from .firestore_client import FirebaseConfig, FirestoreStorage, firebase_client
from .firestore_personal import PersonalDataMixin
from .grading import policy_config
from .lms_data import RESERVED_FILTERS, check_query_catalog, query_request
from .lms_pending import DEV_ACCOUNTS, PendingRepository
from .lms_json import json_value
from .lms_store import FIELDS, KINDS, LmsError, Principal
from .lms_team_adapter import TeamRepository
from .lms_validation import collection, identifier, record_payload, student_payload


DEFAULTS = {
<<<<<<< HEAD
    "courses": {"archived": False, "instructor_ids": []}, "enrollments": {"archived": False},
    "assignments": {"description": "", "due": None, "minutes": None, "week": None},
=======
    "courses": {"archived": False}, "enrollments": {"archived": False},
    "assignments": {"description": "", "due": None, "minutes": None, "week": None, "item_id":None, "lesson_id":None},
>>>>>>> 126ecb7 (full rework)
    "grade_items": {"max_score": 100, "weight": 1, "week": None},
    "grades": {"comment": ""}, "lessons": {"kind": ""},
    "attendance": {}, "materials": {"week": None, "source_url": ""},
}
NATURAL_KEYS = {"enrollments": ("course_id", "student_id"),
                "grades": ("student_id", "item_id"), "attendance": ("student_id", "lesson_id")}


def default_grade_items(course_id):
    return [{"course_id": course_id,
             "title": "Midterm" if i == 5 else "Endterm" if i == 10 else f"Assignment {i}",
             "component": "midterm" if i == 5 else "endterm" if i == 10 else "regmid" if i < 5 else "regend",
             "max_score": 100, "weight": 1, "week": None} for i in range(1, 11)]


def compound_id(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def stored_record(kind, row):
    return {key: parse_time(value) if key in {"due", "starts_at", "ends_at"} and value is not None else value
            for key, value in row.items()}


def public_record(kind, key, row):
    clean = {**DEFAULTS[kind], **{field: json_value(value) for field, value in row.items() if field in FIELDS[kind]}}
    if kind == "courses":
        clean["policy"] = policy_config(clean.get("policy"))
    try:
        clean = record_payload(kind, clean)
    except (ValueError, TypeError, KeyError):
        raise LmsError("Запись Firestore не соответствует контракту LMS.", 502) from None
    return {"id": identifier(key, "id"), **clean}


def projected_record(kind, key, row, fields):
    """Validate only the selected public columns, without inventing missing data."""
    fields = set(fields)
    defaults = {**DEFAULTS[kind]}
    if kind == "courses" and "policy" in fields:
        defaults["policy"] = policy_config()
    selected = {field: json_value(row.get(field, defaults.get(field))) for field in fields - {"id"}}
    if any(field not in row and field not in defaults for field in fields - {"id"}):
        raise LmsError("В документе отсутствует запрошенное публичное поле.", 502)
    try:
        clean = record_payload(kind, selected, key) if selected else {}
    except (ValueError, TypeError):
        raise LmsError("Запрошенные поля не соответствуют контракту LMS.", 502) from None
    return {**({"id": identifier(key, "id")} if "id" in fields else {}), **clean}


class FirestoreRepository(PersonalDataMixin, TeamRepository):
    def __init__(self, storage=None, config=None):
        PendingRepository.__init__(self)
        self.config = config or FirebaseConfig.from_environment()
        self.source = f"firestore:{self.config.project}/{self.config.database}"
        if self.config.test_namespace:
            self.source += "/system_tests/" + self.config.test_namespace
        self.team_database_connected = self.connected = False
        self.gateway_factory = None
        self.gateway = self
        self._snapshot = ContextVar(f"firestore_snapshot_{id(self)}", default=None)
        try:
            prefix = "system_tests/" + self.config.test_namespace if self.config.test_namespace else ""
            self.storage = storage or FirestoreStorage(firebase_client(self.config), prefix=prefix)
            # A missing document is a successful read, not a reason to seed data.
            self.storage.get("courses/campuspulse-readiness")
        except Exception:
            raise LmsError("Firestore недоступен. Проверьте серверные credentials, IAM и сеть.", 503) from None
        self.team_database_connected = self.connected = True

    def _run(self, actor, kind, operation, callback, *, read_only=False):
        try:
            state = self._snapshot.get()
            if state is not None and read_only:
                return callback(state["transaction"])
            return self.storage.transaction(callback, read_only=read_only)
        except LmsError:
            raise
        except Exception:
            event = self._event(kind, actor, operation, None)
            event.update(status="failed", executed=None)
            error = LmsError("Ошибка Firestore: проверьте соединение, квоту и индексы. Данные не подменялись.", 503)
            error.data_access = [event]
            raise error from None

    def read_tool(self, actor, name, callback):
        """One consistent snapshot and authorization cache per synchronous tool call."""
        def read(tx):
            token = self._snapshot.set({"transaction": tx, "courses": {}, "enrollments": {}})
            try:
                return callback()
            finally:
                self._snapshot.reset(token)
        return self._run(actor, name, "read", read, read_only=True)

    def _scan(self, kind, filters, tx, **options):
        rows = self.storage.scan(kind, filters, tx, **options)
        if len(rows) > 100:
            raise LmsError("Более 100 записей. Уточните курс; неполные данные не используются.", 413)
        return rows

    @staticmethod
    def _actor(actor):
        identifier(actor.user_id, "user_id")
        if actor.role not in {"student", "admin"}:
            raise LmsError("Неизвестная роль.", 403)

    def _courses(self, actor, tx, course_id=None):
        state = self._snapshot.get()
        key = (actor.user_id, actor.role, course_id)
        full_key = (actor.user_id, actor.role, None)
        if state is not None and course_id and full_key in state["courses"]:
            return {cid: row for cid, row in state["courses"][full_key].items() if cid == course_id}
        if state is not None and key in state["courses"]:
            return state["courses"][key]
        courses = self._load_courses(actor, tx, course_id)
        if state is not None:
            state["courses"][key] = courses
        return courses

    def _load_courses(self, actor, tx, course_id=None):
        self._actor(actor)
        if course_id is not None:
            # A single-course operation never enumerates all the student's courses.
            if actor.role == "student":
                enrollment_id = compound_id(course_id, actor.user_id)
                enrollment = self.storage.get(f"enrollments/{enrollment_id}", tx, fields=sorted(FIELDS["enrollments"]))
                state = self._snapshot.get()
                if state is not None:
                    state["enrollments"][(actor.user_id, course_id)] = [(enrollment_id, enrollment)] if enrollment else []
                if (enrollment is None or enrollment.get("archived", False)
                        or enrollment.get("student_id") != actor.user_id or enrollment.get("course_id") != course_id):
                    return {}
            row = self.storage.get(f"courses/{course_id}", tx, fields=sorted(FIELDS["courses"] | {"owner_id"}))
            if row is None or (actor.role == "student" and row.get("archived", False)):
                return {}
            if actor.role == "admin" and actor.user_id not in {row.get("owner_id"), *row.get("instructor_ids", [])}:
                return {}
            return {course_id: row}
        if actor.role == "admin":
            owned = self._scan("courses", [("owner_id", "==", actor.user_id)], tx,
                               fields=sorted(FIELDS["courses"] | {"owner_id"}))
            assigned = self._scan("courses", [("instructor_ids", "array_contains", actor.user_id)], tx,
                                  fields=sorted(FIELDS["courses"] | {"owner_id"}))
            return dict([*owned, *assigned])
        enrollments = self._scan("enrollments", [("student_id", "==", actor.user_id)], tx, fields=sorted(FIELDS["enrollments"]))
        state = self._snapshot.get()
        if state is not None:
            state["enrollments"][(actor.user_id, None)] = enrollments
        paths = [f"courses/{identifier(row['course_id'])}" for _, row in enrollments if not row.get("archived", False)]
        return {path.split("/")[-1]: row for path, row in self.storage.get_many(paths, tx, fields=sorted(FIELDS["courses"])).items()
                if row is not None and not row.get("archived", False)}

    def allowed_courses(self, actor):
        return set(self._run(actor, "courses", "read", lambda tx: self._courses(actor, tx), read_only=True))

    def check_course(self, actor, course_id):
        course_id = identifier(course_id)
        courses = self._run(actor, "courses", "read", lambda tx: self._courses(actor, tx, course_id), read_only=True)
        if course_id not in courses:
            raise LmsError("Курс недоступен текущему пользователю.", 403)

    def _list(self, kind, actor, course_id, tx, fields=None):
        courses = self._courses(actor, tx, course_id)
        if course_id is not None:
            if course_id not in courses:
                raise LmsError("Курс недоступен текущему пользователю.", 403)
            courses = {course_id: courses[course_id]}
        if kind == "courses":
            rows = list(courses.items())
        elif kind == "enrollments" and actor.role == "student" and self._snapshot.get() is not None:
            cached = self._snapshot.get()["enrollments"]
            enrollments = cached.get((actor.user_id, None), cached.get((actor.user_id, course_id), []))
            rows = [(key, row) for key, row in enrollments
                    if row["course_id"] in courses]
        else:
            rows = []
            ids = sorted(courses)
            for start in range(0, len(ids), 30):
                filters = [("course_id", "in", ids[start:start + 30])]
                if actor.role == "student" and kind in {"enrollments", "grades", "attendance"}:
                    filters.append(("student_id", "==", actor.user_id))
                rows.extend(self._scan(kind, filters, tx, fields=sorted(set(fields) - {"id"}) if fields else sorted(FIELDS[kind])))
                if len(rows) > 100:
                    raise LmsError("Более 100 записей. Уточните курс.", 413)
        if len(rows) > 100:
            raise LmsError("Более 100 записей. Уточните курс.", 413)
        result = [(projected_record(kind, key, row, fields) if fields else public_record(kind, key, row))
                  for key, row in sorted(rows)]
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 1_000_000:
            raise LmsError("Ответ превышает 1 МБ. Уточните курс.", 413)
        return result

    def list(self, kind, actor, course_id=None, audit=None):
        collection(kind)
        if course_id is not None:
            course_id = identifier(course_id)
        try:
            rows = self._run(actor, kind, "read", lambda tx: self._list(kind, actor, course_id, tx), read_only=True)
        except LmsError as error:
            if audit is not None:
                audit.extend(getattr(error, "data_access", []))
            raise
        if audit is not None:
            audit.append(self._event(kind, actor, "read", len(rows)))
        return rows

    def list_fields(self, kind, actor, fields, course_id=None, audit=None):
        collection(kind)
        if set(fields) - (FIELDS[kind] | {"id"}):
            raise LmsError("Недоступные поля проекции.")
        if course_id is not None:
            course_id = identifier(course_id)
        try:
            rows = self._run(actor, kind, "read", lambda tx: self._list(kind, actor, course_id, tx, fields), read_only=True)
        except LmsError as error:
            if audit is not None:
                audit.extend(getattr(error, "data_access", []))
            raise
        if audit is not None:
            audit.append(self._event(kind, actor, "read", len(rows)))
        return rows

    def describe(self, actor):
        self._actor(actor)
        types = {"policy": "object", "archived": "boolean", "minutes": "integer", "week": "integer",
                 "score": "number", "max_score": "number", "weight": "number"}
        return [{"name": kind, "label": kind, "description": "Учебные данные в области доступа текущей сессии.",
                 "fields": {field: types.get(field, "string") for field in sorted(FIELDS[kind] | {"id"})},
                 "filterable": sorted((FIELDS[kind] | {"id"}) - RESERVED_FILTERS - {"policy"})} for kind in sorted(KINDS)]

    def query(self, actor, resource, *, filters, fields, limit, cursor):
        request = query_request(dict(resource=resource, filters=filters, fields=fields, limit=limit, cursor=cursor))
        check_query_catalog(request, self.describe(actor))
        selected = set(fields or (FIELDS[resource] | {"id"}))
        needed = selected | set(filters)
        try:
            native_filters = {key: parse_time(value) if key in {"due", "starts_at", "ends_at"} and value is not None else value
                              for key, value in filters.items()}
            canonical = json_value(native_filters)
        except ValueError:
            raise LmsError("Фильтр даты должен содержать ISO 8601 с часовым поясом.") from None
        decoded = None
        if cursor:
            try:
                body, signature = cursor.rsplit(".", 1)
                if not hmac.compare_digest(signature, self._signature(body)):
                    raise ValueError()
                decoded = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
                identifier(decoded["after"], "cursor")
            except Exception:
                raise LmsError("Курсор недействителен. Начните с первой страницы.") from None

        def read(tx):
            cid = filters.get("course_id")
            key = identifier(filters["id"], "id") if "id" in filters else None
            direct = None
            if key and resource != "courses":
                auth_fields = {"course_id"} | ({"student_id"} if resource in {"enrollments", "grades", "attendance"} else set())
                direct = self.storage.get(f"{resource}/{key}", tx, fields=sorted((needed | auth_fields) - {"id"}))
                if direct is None or cid and direct.get("course_id") != cid:
                    return {"items": [], "next_cursor": None}
                cid = identifier(direct["course_id"])
            courses = self._courses(actor, tx, key if resource == "courses" and key else cid)
            if cid and cid not in courses:
                raise LmsError("Курс недоступен текущему пользователю.", 403)
            binding = compound_id(self.source, actor.user_id, actor.role, resource, canonical, fields, limit, sorted(courses))
            if decoded is not None and decoded.get("binding") != binding:
                raise LmsError("Курсор не соответствует запросу или текущим правам.")
            after = decoded["after"] if decoded else None
            if resource == "courses":
                candidates = [(doc_id, row) for doc_id, row in sorted(courses.items()) if after is None or doc_id > after]
            elif key:
                if actor.role == "student" and resource in {"enrollments", "grades", "attendance"} and direct.get("student_id") != actor.user_id:
                    return {"items": [], "next_cursor": None}
                candidates = [(key, direct)] if after is None or key > after else []
            else:
                # Missing legacy columns keep their model defaults. A filter equal
                # to a default needs bounded post-filtering because Firestore ==
                # does not match a missing field. Other filters run on the server.
                post_filter = any(field in DEFAULTS[resource] and value == DEFAULTS[resource][field]
                                  for field, value in canonical.items())
                db_filters = [(field, "==", native_filters[field])
                              for field, value in canonical.items() if field != "course_id"
                              and not (field in DEFAULTS[resource] and value == DEFAULTS[resource][field])]
                if actor.role == "student" and resource in {"enrollments", "grades", "attendance"}:
                    db_filters.append(("student_id", "==", actor.user_id))
                candidates = []
                ids = sorted(courses)
                for start in range(0, len(ids), 30):
                    scope = ids[start:start + 30]
                    scope_filter = ("course_id", "==", scope[0]) if len(scope) == 1 else ("course_id", "in", scope)
                    candidates.extend(self.storage.scan(resource, [scope_filter, *db_filters], tx,
                        limit=101 if post_filter else limit + 1, fields=sorted(needed - {"id"}), after=after))
                    if post_filter and len(candidates) > 100:
                        raise LmsError("Фильтр по отсутствующему полю требует просмотра более 100 записей. Уточните курс.", 413)
            rows = []
            for doc_id, raw in sorted(candidates):
                public = projected_record(resource, doc_id, raw, needed | {"id"})
                if all(public.get(field) == value for field, value in canonical.items()):
                    rows.append(public)
            next_cursor = None
            if len(rows) > limit:
                body = base64.urlsafe_b64encode(json.dumps({"binding": binding, "after": rows[limit - 1]["id"]}).encode()).decode().rstrip("=")
                next_cursor = body + "." + self._signature(body)
            return {"items": [{field: value for field, value in row.items() if field in selected} for row in rows[:limit]],
                    "next_cursor": next_cursor}

        return self._run(actor, resource, "read", read, read_only=True)

    def save(self, kind, actor, payload, record_id=None):
        self.require_admin(actor)
        if kind == "courses" and record_id is None and isinstance(payload, dict) and set(payload) == {"name"}:
            payload = {**payload, "code": "SUB-" + uuid.uuid4().hex[:10]}
        clean = record_payload(kind, payload, record_id)
        keys = NATURAL_KEYS.get(kind, ())
        key = record_id or (compound_id(*(clean[field] for field in keys)) if keys else uuid.uuid4().hex)
        path = f"{kind}/{key}"

        def write(tx):
            current = self.storage.get(path, tx)
            if record_id and current is None:
                raise LmsError("Запись не найдена; PATCH не создаёт документ.", 404)
            previous = {field: json_value(value) for field, value in (current or {}).items() if field in FIELDS[kind]}
            merged = {**DEFAULTS[kind], **previous, **clean}
            if kind == "courses":
                if current is not None and actor.user_id not in {current.get("owner_id"), *current.get("instructor_ids", [])}:
                    raise LmsError("Нет прав на изменение курса.", 403)
                if "instructor_ids" in clean and current is not None and current.get("owner_id") != actor.user_id:
                    raise LmsError("Назначать преподавателей может только владелец курса.", 403)
                merged["policy"] = policy_config(merged.get("policy"))
            else:
                for cid in {merged["course_id"], previous.get("course_id", merged["course_id"])}:
                    course = self.storage.get(f"courses/{cid}", tx)
                    if course is None or actor.user_id not in {course.get("owner_id"), *course.get("instructor_ids", [])}:
                        raise LmsError("Курс отсутствует или не назначен этому преподавателю.", 403)
                if keys and current and any(merged[field] != previous[field] for field in keys):
                    raise LmsError("Связи этой записи неизменяемы; архивируйте зачисление.", 409)
                if kind in {"enrollments", "grades", "attendance"}:
                    user = self.storage.get(f"users/{merged['student_id']}", tx)
                    if user is None or user.get("role") != "student":
                        raise LmsError("Студент не найден.", 404)
                if kind == 'assignments':
                    for field, related_kind in [('item_id','grade_items'),('lesson_id','lessons')]:
                        if merged.get(field):
                            related = self.storage.get(f"{related_kind}/{merged[field]}",tx)
                            if related is None or related.get('course_id') != merged['course_id']:
                                raise LmsError('Работа и занятие должны принадлежать тому же предмету.',409)
                if kind in {"grades", "attendance"}:
                    related_kind, related_key = ("grade_items", "item_id") if kind == "grades" else ("lessons", "lesson_id")
                    related = self.storage.get(f"{related_kind}/{merged[related_key]}", tx)
                    if related is None or related.get("course_id") != merged["course_id"]:
                        raise LmsError("Связанная запись не найдена в этом курсе.", 404)
                    enrollment = self.storage.get(f"enrollments/{compound_id(merged['course_id'], merged['student_id'])}", tx)
                    if enrollment is None or enrollment.get("archived", False):
                        raise LmsError("Студент не зачислен на курс.", 409)
                    if kind == "grades" and merged["score"] is not None and merged["score"] > related.get("max_score", 100):
                        raise LmsError("Балл превышает максимум работы.")
                if kind in {"grade_items", "lessons"} and current:
                    if previous["course_id"] != merged["course_id"]:
                        raise LmsError("Нельзя переносить работу или занятие в другой курс.", 409)
                    if kind == "grade_items":
                        grades = self._scan("grades", [("item_id", "==", key)], tx)
                        if any(row.get("score") is not None and row["score"] > merged["max_score"] for _, row in grades):
                            raise LmsError("Максимум меньше уже выставленного балла.", 409)
            try:
                merged = record_payload(kind, merged)
            except LmsError:
                raise
            except (ValueError, TypeError):
                raise LmsError("Некорректные поля объединённой записи.") from None
            normalized = public_record(kind, key, merged)
            if current is not None and not record_id and any(previous.get(field) != normalized[field] for field in clean):
                raise LmsError("Такая связанная запись уже существует. Используйте PATCH.", 409)
            data = stored_record(kind, {field: value for field, value in normalized.items() if field != "id"})
            if kind == "courses":
                data["owner_id"] = actor.user_id
            if kind == "courses" and current is None:
                for index, work in enumerate(default_grade_items(key), 1):
                    self.storage.put(tx, f"grade_items/{compound_id(key, 'default-work-' + str(index))}", stored_record("grade_items", work))
            if current != data:
                self.storage.put(tx, path, data)
            return normalized

        return self._run(actor, kind, "update" if record_id else "create", write)

    def ensure_default_grade_items(self, actor, course_id):
        self.require_admin(actor)
        key = identifier(course_id)
        def ensure(tx):
            course = self.storage.get(f"courses/{key}", tx)
            if course is None or course.get('owner_id') != actor.user_id:
                raise LmsError("Нет прав на изменение дисциплины.", 403)
            existing = self._scan('grade_items', [('course_id', '==', key)], tx)
            titles = {row.get('title') for _, row in existing}
            missing = [(index, work) for index, work in enumerate(default_grade_items(key), 1) if work['title'] not in titles]
            # Read every destination before writing, as required by Firestore transactions.
            destinations = [(f"grade_items/{compound_id(key, 'default-work-' + str(index))}", work) for index, work in missing]
            for path, _ in destinations:
                if self.storage.get(path, tx) is not None:
                    raise LmsError("ID стандартной работы уже занят.", 409)
            for path, work in destinations:
                self.storage.put(tx, path, stored_record('grade_items', work))
            return len(destinations)
        return self._run(actor, 'grade_items', 'create', ensure)

    def delete_course(self, actor, record_id):
        self.require_admin(actor)
        key = identifier(record_id, "record_id")
        def remove(tx):
            course = self.storage.get(f"courses/{key}", tx)
            if course is None:
                raise LmsError("Дисциплина не найдена.", 404)
            if course.get("owner_id") != actor.user_id:
                raise LmsError("Нет прав на удаление дисциплины.", 403)
            for kind in sorted(KINDS - {"courses"}):
                if self.storage.scan(kind, [("course_id", "==", key)], tx, limit=1):
                    raise LmsError("У дисциплины есть связанные данные. Используйте архивирование.", 409)
            self.storage.delete(tx, f"courses/{key}")
            return {"deleted": True, "id": key}
        return self._run(actor, "courses", "delete", remove)

    def delete_grade(self, actor, record_id):
        self.require_admin(actor)
        path = f"grades/{identifier(record_id, 'record_id')}"
        def remove(tx):
            row = self.storage.get(path, tx)
            if row is None:
                raise LmsError("Оценка не найдена.", 404)
            course = self.storage.get(f"courses/{row['course_id']}", tx)
            if course is None or course.get("owner_id") != actor.user_id:
                raise LmsError("Нет прав на изменение оценки.", 403)
            self.storage.delete(tx, path)
            return {"deleted": True, "id": record_id}
        return self._run(actor, "grades", "delete", remove)

    def login(self, username, password):
        token, actor = super().login(username, password)
        # Only public development identity, once. No password or token in Firestore.
        def ensure(tx):
            path = f"users/{actor.user_id}"
            existing = self.storage.get(path, tx)
            if existing is None:
                self.storage.put(tx, path, {"role": actor.role, "name": actor.name})
            elif existing.get("role") != actor.role:
                raise LmsError("Роль профиля не совпадает с локальной сессией.", 403)
        self._run(actor, "users", "create", ensure)
        return token, actor

    def principal(self, session_token):
        actor = PendingRepository.principal(self,session_token)
        key = hashlib.sha256(session_token.encode()).hexdigest()
        if self.storage.get(f'users/{actor.user_id}/revoked_sessions/{key}') is not None:
            raise LmsError('Сессия завершена. Войдите заново.',401)
        return actor

    def logout(self, token):
        actor = self.principal(token)
        key = hashlib.sha256(token.encode()).hexdigest()
        self._run(actor,'sessions','delete',lambda tx:self.storage.put(tx,f'users/{actor.user_id}/revoked_sessions/{key}',{'revoked':True}))
        PendingRepository.logout(self,token)

    def users(self, actor):
        self.require_admin(actor)
        def read(tx):
<<<<<<< HEAD
            ids = {uid for uid, account in DEV_ACCOUNTS.items() if account[2] == "student"}
            profiles = self.storage.get_many([f"users/{uid}" for uid in sorted(ids)], tx, fields=["name", "role"])
            return [{"id": path.split("/")[-1], "role": "student", "name": row.get("name", "")}
                    for path, row in profiles.items() if row is not None and row.get("role") == "student"]
=======
            profiles = self._scan('users',[('role','==','student')],tx,fields=['name','role'])
            return [{"id": key, "role":"student", "name":row.get('name','')} for key,row in profiles]
>>>>>>> 126ecb7 (full rework)
        return self._run(actor, "users", "read", read, read_only=True)

    def create_student(self, actor, payload):
        self.require_admin(actor)
        student_payload(payload)
        raise LmsError("Создание учётных записей требует провайдера аутентификации. Пароли в Firestore не сохраняются.", 503)

    def mcp_environment(self):
        return {**self.config.environment(), "CAMPUSPULSE_LMS_REPOSITORY": "firestore",
                "CAMPUSPULSE_LMS_SESSION_SECRET": self.secret}
