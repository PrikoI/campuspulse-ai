"""Database-neutral discovery/query contract. No dataset names or storage here."""
from typing import Protocol

from .lms_store import LmsError, Principal, text

QUERY_PROPERTIES = {
    "resource": {"type": "string", "minLength": 1, "maxLength": 120,
                 "description": "Exact resource name returned by list_data_resources."},
    "filters": {"type": "object", "description": "Equality filters on fields declared filterable by the resource catalog."},
    "fields": {"type": ["array", "null"], "maxItems": 100, "items": {"type": "string"}},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    "cursor": {"type": ["string", "null"], "maxLength": 2000},
}
RESERVED_FILTERS = {"student_id", "user_id", "actor", "role", "tenant_id"}


class DataGateway(Protocol):
    """Implemented by the DB teammate; both calls MUST enforce actor's scope.

    describe returns metadata only: [{name,label,description,fields,filterable}].
    fields maps public column names to type names (string/number/integer/boolean/
    object/array). query returns {items:[dict], next_cursor:str|None}. Neither
    method may return another actor's records or silently swallow DB failures.
    """
    source: str
    connected: bool  # Set after an actual readiness check, not merely a URL.

    def describe(self, actor: Principal) -> list[dict]: ...
    def query(self, actor: Principal, resource: str, *, filters: dict,
              fields: list[str] | None, limit: int, cursor: str | None) -> dict: ...
    def mcp_environment(self) -> dict[str, str]: ...


def resource_name(value):
    value = text(value, "resource", 120)
    if any(not (char.isalnum() or char in "_.-") for char in value):
        raise LmsError("Имя ресурса: буквы, цифры, _, . или -.")
    return value


def query_request(raw):
    if not isinstance(raw, dict) or set(raw) - set(QUERY_PROPERTIES) or "resource" not in raw:
        raise LmsError("Нужны resource и необязательные filters, fields, limit, cursor.")
    resource = resource_name(raw["resource"])
    filters = raw.get("filters", {})
    if not isinstance(filters, dict) or len(filters) > 30 or set(filters) & RESERVED_FILTERS:
        raise LmsError("filters: до 30 полей; личность и область доступа задаёт сервер.")
    import math
    for key, value in filters.items():
        resource_name(key)
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise LmsError("Фильтры принимают только скалярные значения или null.")
        if isinstance(value, str) and len(value) > 2000 or isinstance(value, float) and not math.isfinite(value):
            raise LmsError("Некорректное значение фильтра.")
    fields = raw.get("fields")
    if fields is not None:
        if not isinstance(fields, list) or not 1 <= len(fields) <= 100:
            raise LmsError("fields: от 1 до 100 названий полей.")
        fields = [resource_name(field) for field in fields]
        if len(set(fields)) != len(fields):
            raise LmsError("Названия полей не должны повторяться.")
    limit = raw.get("limit", 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise LmsError("limit: целое число от 1 до 100.")
    cursor = raw.get("cursor")
    if cursor is not None:
        cursor = text(cursor, "cursor", 2000)
    return {"resource": resource, "filters": dict(filters), "fields": fields, "limit": limit, "cursor": cursor}


def catalog_metadata(resources):
    if not isinstance(resources, list) or len(resources) > 100:
        raise LmsError("Адаптер вернул некорректный каталог ресурсов.", 502)
    names = set()
    for item in resources:
        if not isinstance(item, dict) or set(item) != {"name", "label", "description", "fields", "filterable"}:
            raise LmsError("Некорректная схема ресурса адаптера.", 502)
        name = resource_name(item["name"])
        if name in names:
            raise LmsError("Адаптер вернул повторяющиеся ресурсы.", 502)
        names.add(name)
        text(item["label"], "label", 200)
        text(item["description"], "description", 2000, required=False)
        fields, filters = item["fields"], item["filterable"]
        if not isinstance(fields, dict) or not 1 <= len(fields) <= 100 or not isinstance(filters, list):
            raise LmsError("Некорректные поля ресурса адаптера.", 502)
        for field, kind in fields.items():
            resource_name(field)
            if not isinstance(kind, str) or kind not in {"string", "number", "integer", "boolean", "object", "array"}:
                raise LmsError("Неизвестный тип поля ресурса.", 502)
        if any(not isinstance(field, str) or field not in fields or field in RESERVED_FILTERS for field in filters):
            raise LmsError("Некорректные фильтруемые поля ресурса.", 502)
    return resources


def check_query_catalog(request, resources):
    spec = next((item for item in resources if item["name"] == request["resource"]), None)
    if spec is None:
        raise LmsError("Ресурс не найден или недоступен текущей сессии.", 404)
    if set(request["filters"]) - set(spec["filterable"]) or request["fields"] is not None and set(request["fields"]) - set(spec["fields"]):
        raise LmsError("Запрошенные поля или фильтры отсутствуют в доступной схеме ресурса.")
    types = {"string": str, "number": (int, float), "integer": int, "boolean": bool}
    for field, value in request["filters"].items():
        kind = spec["fields"][field]
        if value is not None and (kind not in types or not isinstance(value, types[kind]) or isinstance(value, bool) and kind != "boolean"):
            raise LmsError("Тип фильтра не соответствует схеме ресурса.")
    return spec
