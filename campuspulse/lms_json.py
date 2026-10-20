"""JSON-compatible values and errors shared by repository, tools and agent.

This is a serialization boundary, not a second data model or a disk cache.
"""
import json
import math
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from .domain import TZ
from .lms_store import LmsError


def json_value(value):
    if isinstance(value, Enum):
        return json_value(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise LmsError("Дата результата должна содержать часовой пояс.", 502)
        return value.astimezone(TZ).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    # No default=str: SDK objects, credentials and references must never leak.
    raise LmsError("Результат содержит неподдерживаемое JSON-значение.", 502)


def json_result(value):
    result = json_value(value)
    if not isinstance(result, dict):
        raise LmsError("Результат инструмента должен быть объектом.", 502)
    return result


def json_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


def tool_error(error):
    status = error.status if isinstance(error, LmsError) else 503
    codes = {400: "invalid_request", 401: "authentication_required", 403: "access_denied",
             404: "not_found", 409: "conflict", 413: "result_too_large", 429: "quota_exceeded",
             502: "invalid_result", 503: "source_unavailable", 504: "timeout"}
    return {"error": str(error) if isinstance(error, LmsError) else "Источник данных недоступен.",
            "status": status, "error_code": codes.get(status, "tool_error"),
            "retryable": status in {429, 503, 504}}


def model_result(result):
    """Keep user-review tokens and access audit in the API, outside model context."""
    return {key: value for key, value in result.items() if key not in {"data_access", "proposal"}}
