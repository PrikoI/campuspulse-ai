"""Session-only Developer API credentials and fail-closed billing checks.

Only read-only Google APIs are used here. No billing/IAM mutations, retries on a
paid model, Vertex fallback, credential files, or logging of remote error bodies.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field

FREE_MODEL = "gemini-3.1-flash-lite"


class ConnectionError(ValueError):
    """A safe, user-facing connection error (never includes an API key)."""


def verify_unbilled_key(api_key: str) -> str:
    """Resolve the key's actual project, then require billingEnabled == false."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        with AuthorizedSession(credentials) as session:
            lookup = session.get("https://apikeys.googleapis.com/v2/keys:lookupKey",
                                 params={"keyString": api_key}, timeout=15, allow_redirects=False)
            if lookup.status_code != 200:
                raise ConnectionError("Не удалось определить проект ключа. Нужны вход Google ADC, API Keys API и право apikeys.keys.lookup. Запрос к Gemini не отправлен.")
            data = lookup.json()
            parent = data.get("parent", "")
            match = re.fullmatch(r"projects/([A-Za-z0-9_-]+)(?:/locations/global)?", parent)
            if not match or not data.get("name"):
                raise ConnectionError("Google не подтвердил проект действующего ключа. Gemini заблокирован.")
            project = match.group(1)
            billing = session.get(f"https://cloudbilling.googleapis.com/v1/projects/{project}/billingInfo",
                                  timeout=15, allow_redirects=False)
            if billing.status_code != 200:
                raise ConnectionError("Не удалось проверить биллинг проекта ключа. Проверь вход Google ADC и доступ к проекту. Gemini заблокирован.")
            if billing.json().get("billingEnabled") is not False:
                raise ConnectionError("Биллинг проекта ключа включён или его статус не подтверждён. Разрешён только проект с отключённым биллингом; запрос к Gemini не отправлен.")
            return project
    except ConnectionError:
        raise
    except Exception:
        # Requests exceptions can contain a URL with keyString. Never expose them.
        raise ConnectionError("Не удалось безопасно проверить ключ и биллинг через Google. Проверь сеть и вход Google ADC; запрос к Gemini не отправлен.") from None


@dataclass
class DeveloperConnection:
    api_key: str = field(repr=False)
    project: str
    model: str = FREE_MODEL

    def client_options(self) -> dict:
        if self.model != FREE_MODEL:
            raise ConnectionError("Эта модель не разрешена для бесплатного подключения.")
        if verify_unbilled_key(self.api_key) != self.project:
            raise ConnectionError("Проект ключа изменился. Подключи ключ заново.")
        return {"vertexai": False, "api_key": self.api_key}


class Connections:
    """One credential per opaque HttpOnly browser session, with a 12h lifetime."""
    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def session(self, token: str | None) -> tuple[str, bool]:
        with self._lock:
            now = time.monotonic()
            self._items = {key: item for key, item in self._items.items() if now - item[0] < 43200}
            if token in self._items:
                return token, False
            if len(self._items) >= 128:
                oldest = min(self._items, key=lambda key: self._items[key][0])
                del self._items[oldest]
            token = secrets.token_urlsafe(32)
            self._items[token] = (now, None)
            return token, True

    def get(self, token: str) -> DeveloperConnection | None:
        with self._lock:
            item = self._items.get(token)
            return item[1] if item and time.monotonic() - item[0] < 43200 else None

    def connect(self, token: str, api_key: str) -> DeveloperConnection:
        # Auth keys can contain punctuation (unlike legacy AIza keys). Reject
        # whitespace/control characters, rather than assuming a legacy format.
        if not isinstance(api_key, str) or not re.fullmatch(r"[\x21-\x7e]{20,4096}", api_key.strip()):
            raise ConnectionError("Вставь ключ Gemini API из Google AI Studio.")
        api_key = api_key.strip()
        # Drop any old key even when validation of a replacement fails.
        self.disconnect(token)
        connection = DeveloperConnection(api_key, verify_unbilled_key(api_key))
        with self._lock:
            self._items[token] = (time.monotonic(), connection)
        return connection

    def disconnect(self, token: str):
        with self._lock:
            self._items[token] = (time.monotonic(), None)


def model_error(code) -> str:
    return {400: "Gemini отклонил запрос. Проверь модель и содержимое запроса.",
            401: "Google отклонил ключ. Создай действующий ключ в Google AI Studio.",
            403: "Gemini недоступен этому ключу, проекту или региону. Проверь настройки в Google AI Studio. Платный доступ не включался.",
            404: "Бесплатная модель сейчас недоступна. Переход на другую модель не выполнялся.",
            429: "Лимит бесплатного Gemini исчерпан. Подожди и попробуй позже. Платный тариф не включался.",
            503: "Gemini временно недоступен. Попробуй позже."}.get(code, "Ошибка соединения с Gemini. Повтори запрос; платный сервис не подключался.")
