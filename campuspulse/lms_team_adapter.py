"""Integration slot for the teammate's real database, with no storage of its own.

Implement DataGateway in team_gateway.py; see docs/DATABASE_QUICKSTART.md.
This wrapper handles catalog validation, named queries and MCP configuration.
It has no database driver, connection URL, academic rows or seeding. Optional
semantic LMS writes still require the marked methods and transactional checks.

Temporary local auth is inherited solely for development. Production identity,
shared revocation and durable model budgets require separate integration.
"""
from __future__ import annotations

import importlib
import json
import os
from datetime import datetime

from .domain import TZ
from .lms_data import DataGateway, catalog_metadata, check_query_catalog, query_request
from .lms_pending import PendingRepository
from .lms_store import LmsError, Principal
from .lms_validation import collection, identifier, record_payload, student_payload


class TeamRepository(PendingRepository):
    source = "team-unconfigured"
    team_database_connected = False

    def __init__(self, gateway: DataGateway | None = None):
        super().__init__()
        # Trusted server setting only; never accepted from HTTP or the model.
        target = os.getenv("CAMPUSPULSE_TEAM_GATEWAY")
        self.gateway_factory = target
        if gateway is None and target:
            try:
                module, factory = target.split(":", 1)
                gateway = getattr(importlib.import_module(module), factory)()
            except Exception:
                raise LmsError("Не удалось инициализировать шлюз команды. Проверьте серверную конфигурацию.", 503) from None
        self.gateway = gateway
        if gateway is not None:
            self.source = gateway.source
            self.team_database_connected = gateway.connected is True

    def _event(self, resource, actor, operation, rows):
        return {"type": "database_request", "operation": operation, "collection": resource,
                "filters": {"scope": "authenticated-actor", "user_id": actor.user_id},
                "source": self.source, "status": "ok", "executed": True, "rows": rows,
                "at": datetime.now(TZ).isoformat()}

    def _gateway_failure(self, resource, actor, operation):
        event = self._event(resource, actor, operation, None)
        # A driver exception cannot prove whether the remote query executed.
        event.update(status="failed", executed=None)
        error = LmsError("Шлюз базы завершился ошибкой. Результат выполнения неизвестен; данные не получены.", 503)
        error.data_access = [event]
        raise error

    def data_resources(self, actor):
        if self.gateway is None or self.gateway.connected is not True:
            return self.unavailable("resource_catalog", actor, operation="describe")
        try:
            resources = catalog_metadata(self.gateway.describe(actor))
        except LmsError:
            raise
        except Exception:
            return self._gateway_failure("resource_catalog", actor, "describe")
        return {"resources": resources, "source": self.source, "team_database_connected": True,
                "data_access": [self._event("resource_catalog", actor, "describe", len(resources))]}

    def query_data(self, actor, request):
        request = query_request(request)
        if self.gateway is None or self.gateway.connected is not True:
            return self.unavailable(request["resource"], actor)
        catalog = self.data_resources(actor)
        spec = check_query_catalog(request, catalog["resources"])
        try:
            result = self.gateway.query(actor, **request)
        except LmsError:
            raise
        except Exception:
            return self._gateway_failure(request["resource"], actor, "read")
        if not isinstance(result, dict) or set(result) != {"items", "next_cursor"} or not isinstance(result["items"], list):
            raise LmsError("Шлюз вернул некорректный ответ.", 502)
        if len(result["items"]) > request["limit"] or any(not isinstance(row, dict) or set(row) - set(request["fields"] or spec["fields"]) for row in result["items"]):
            raise LmsError("Ответ шлюза выходит за запрошенную схему или лимит.", 502)
        if result["next_cursor"] is not None and (not isinstance(result["next_cursor"], str) or not 1 <= len(result["next_cursor"]) <= 2000):
            raise LmsError("Шлюз вернул некорректный курсор.", 502)
        try:
            size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (ValueError, TypeError):
            raise LmsError("Ответ шлюза должен быть конечным JSON.", 502) from None
        if size > 1_000_000:
            raise LmsError("Слишком большой ответ. Сузьте набор полей, фильтры или limit.", 413)
        event = self._event(request["resource"], actor, "read", len(result["items"]))
        event["filters"] = {"scope": "authenticated-actor", "fields": sorted(request["filters"]), "limit": request["limit"]}
        return {**result, "resource": request["resource"], "source": self.source, "team_database_connected": True,
                "data_access": [*catalog["data_access"], event]}

    def list(self, kind: str, actor: Principal, course_id=None, audit=None) -> list[dict]:
        collection(kind)
        if course_id is not None:
            course_id = identifier(course_id)
        if self.gateway is not None and self.gateway.connected is True:
            # Optional semantic LMS mapping: the gateway advertises normalized
            # resources with these names. Other resources remain fully generic.
            request = {"resource": kind, "filters": {"course_id": course_id} if course_id else {}, "limit": 100}
            try:
                result = self.query_data(actor, request)
            except LmsError as error:
                if audit is not None:
                    audit.extend(getattr(error, "data_access", []))
                raise
            if audit is not None:
                audit.extend(result["data_access"])
            if result["next_cursor"] is not None:
                raise LmsError("Данных больше лимита LMS-расчёта. Уточните курс; неполный набор не используется.", 413)
            return result["items"]
        return self.unavailable(kind, actor, course_id, audit=audit)

    def save(self, kind: str, actor: Principal, payload: dict, record_id=None) -> dict:
        self.require_admin(actor)
        payload = record_payload(kind, payload, record_id)
        # TODO: Inside a transaction, enforce ownership, foreign keys, score
        # bounds against grade_items.max_score, and compound uniqueness. PATCH
        # must validate the merged record and never silently create a new row.
        return self.unavailable(kind, actor, payload.get("course_id"),
                                operation="update" if record_id else "create", record_id=record_id)

    def users(self, actor: Principal) -> list[dict]:
        self.require_admin(actor)
        # TODO: Scoped public identities only; never expose hashes or secrets.
        return self.unavailable("users", actor)

    def create_student(self, actor: Principal, payload: dict) -> dict:
        self.require_admin(actor)
        student_payload(payload)
        # TODO: Use the agreed identity provider. Never store plaintext passwords.
        return self.unavailable("users", actor, operation="create")

    def allowed_courses(self, actor: Principal) -> set[str]:
        # Gateway MUST scope normalized courses to active enrollments/ownership.
        return {row["id"] for row in self.list("courses", actor) if not row["archived"]}

    def check_course(self, actor: Principal, course_id: str):
        course_id = identifier(course_id)
        if course_id not in self.allowed_courses(actor):
            raise LmsError("Курс недоступен текущей сессии.", 403)

    def mcp_environment(self) -> dict:
        # TODO: Forward only explicitly needed team DB connection settings.
        # The subprocess must reach the SAME real source and verify the SAME
        # principal as HTTP. Do not put a DB password in logs or tool schemas.
        config = self.gateway.mcp_environment() if self.gateway is not None else {}
        if self.gateway_factory:
            config = {**config, "CAMPUSPULSE_TEAM_GATEWAY": self.gateway_factory}
        return {**config, "CAMPUSPULSE_LMS_REPOSITORY": "team", "CAMPUSPULSE_LMS_SESSION_SECRET": self.secret}
