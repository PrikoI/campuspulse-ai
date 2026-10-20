"""Loopback LMS API. No frontend, academic fixtures or automatic cloud calls."""
import argparse
import asyncio
import importlib.util
import json
import os
import threading
import time
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .agent import settings
from .lms_agent import run_lms_query
from .lms_store import KINDS, LmsError
from .lms_repository import open_repository
from .lms_tools import LmsTools
from .lms_validation import identifier
from .lms_openapi import openapi_document
from .lms_data import query_request
from .grading import evaluate_grades
from .server import Handler, LIMIT, SLOTS, exception_leaves
from .free_gemini import ConnectionError as GeminiError

LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LmsError("Повторяющиеся поля JSON запрещены.")
        result[key] = value
    return result


def invalid_constant(value):
    raise LmsError("JSON не допускает NaN и Infinity.")


class LmsHandler(Handler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    @property
    def repository(self):
        return self.server.repository

    def lms_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        item = cookie.get("campuspulse_lms")
        return item.value if item else ""

    def actor(self):
        return self.repository.principal(self.lms_token())

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/lms", "/lms/"}:
            if not self.trusted_host():
                return
            self.json_reply({"service": "CampusPulse LMS backend", "api": "/api/v1", "status": "/api/v1/status",
                             "frontend_connected": False, "source": self.repository.source})
            return
        if not parsed.path.startswith("/api/v1/"):
            if not self.trusted_host():
                return
            self.json_reply({"error": "Endpoint не найден. API находится в /api/v1/."}, 404)
            return
        self.dispatch_lms("GET")

    def do_POST(self):
        if not urlparse(self.path).path.startswith("/api/v1/"):
            if not self.trusted_host():
                return
            return self.json_reply({"error": "Endpoint не найден. Используй /api/v1/."}, 404)
        self.dispatch_lms("POST")

    def do_PATCH(self):
        self.dispatch_lms("PATCH")

    def do_DELETE(self):
        self.dispatch_lms("DELETE")

    def do_OPTIONS(self):
        # Same-origin proxy is required; no permissive cross-origin preflight.
        if self.trusted_host():
            self.json_reply({"error": "Используй same-origin proxy для фронтенда."}, 405)

    def dispatch_lms(self, method):
        if not self.trusted_host():
            return
        if not SLOTS.acquire(blocking=False):
            self.json_reply({"error": "Два запроса уже выполняются. Подожди."}, 429); return
        self.sse_started = False
        try:
            parsed = urlparse(self.path)
            route = parsed.path.removeprefix("/api/v1/").strip("/").split("/")
            methods = {("status",): {"GET"}, ("openapi.json",): {"GET"}, ("auth", "login"): {"POST"},
                       ("auth", "logout"): {"POST"}, ("me",): {"GET"}, ("grading", "calculate"): {"POST"},
                       ("admin", "users"): {"GET"}, ("admin", "students"): {"POST"},
                       ("agent", "query"): {"POST"}, ("agent", "stream"): {"POST"},
                       ("data", "resources"): {"GET"}, ("data", "query"): {"POST"},
                       ("grade-summary",): {"GET"}, ("attendance-summary",): {"GET"}}
            supported = methods.get(tuple(route))
            if len(route) == 1 and route[0] in KINDS:
                supported = {"GET"}
            if len(route) in {2, 3} and route[0] == "admin" and route[1] in KINDS:
                supported = {"GET", "POST"} if len(route) == 2 else {"PATCH"}
            if supported is None:
                raise LmsError("Endpoint не найден.", 404)
            if method not in supported:
                raise LmsError("Метод не поддерживается.", 405)
            query = parse_qs(parsed.query, keep_blank_values=True)
            query_fields = {"course_id", "target"} if route == ["grade-summary"] else {"course_id"} if method == "GET" and (route == ["attendance-summary"] or route[-1] in KINDS) else set()
            if set(query) - query_fields or any(len(values) != 1 for values in query.values()):
                raise LmsError("Неизвестные параметры. Student ID берётся из сессии.")
            if "course_id" in query:
                query["course_id"] = [identifier(query["course_id"][0])]
            payload = {}
            if method in {"POST", "PATCH"}:
                if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                    raise LmsError("Нужен единственный Content-Length; Transfer-Encoding не поддерживается.")
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    raise LmsError("Нужен Content-Type application/json.", 415)
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= LIMIT:
                    raise LmsError("Размер запроса: от 1 байта до 8 МБ.", 413)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise LmsError("Тело запроса получено не полностью.")
                payload = json.loads(raw, object_pairs_hook=strict_object, parse_constant=invalid_constant)
                if not isinstance(payload, dict):
                    raise LmsError("Ожидается объект JSON.")
            if route == ["status"] and method == "GET":
                return self.json_reply({"version": "0.4.0", "source": self.repository.source,
                    "team_database_connected": self.repository.team_database_connected, "cloud_deployed": False, "default_engine": "local",
                    "mcp_available": settings()["mcp_available"], "auto_model_calls": False,
                    "transport": getattr(self.server, "transport", "mcp"), "authentication": "temporary-local",
                    "gemini_available": False, "frontend_connected": False, "openapi": "/api/v1/openapi.json",
                    "notice": "Командная база не подключена. Собственные базы и учебные примеры не используются." if not self.repository.team_database_connected else "Используется адаптер команды."})
            if route == ["openapi.json"] and method == "GET":
                return self.json_reply(openapi_document())
            if route == ["auth", "login"] and method == "POST":
                if set(payload) != {"username", "password"}:
                    raise LmsError("Нужны только username и password.")
                key = (self.client_address[0], str(payload.get("username"))[:100])
                with LOGIN_LOCK:
                    attempts = [at for at in LOGIN_ATTEMPTS.get(key, []) if time.monotonic()-at < 60]
                    if len(attempts) >= 5:
                        raise LmsError("Слишком много попыток входа. Подожди минуту.", 429)
                    LOGIN_ATTEMPTS[key] = attempts + [time.monotonic()]
                token, actor = self.repository.login(payload.get("username"), payload.get("password"))
                with LOGIN_LOCK:
                    LOGIN_ATTEMPTS.pop(key, None)
                self.extra_cookies = [f"campuspulse_lms={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"]
                return self.json_reply({"user": actor.public()})
            actor = self.actor()
            if route == ["auth", "logout"] and method == "POST":
                if payload:
                    raise LmsError("Для выхода передай пустой объект JSON.")
                self.repository.logout(self.lms_token())
                self.extra_cookies = ["campuspulse_lms=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"]
                return self.json_reply({"logged_out": True})
            if route == ["me"] and method == "GET":
                return self.json_reply({"user": actor.public()})
            if route == ["data", "resources"] and method == "GET":
                return self.json_reply(self.repository.data_resources(actor))
            if route == ["data", "query"] and method == "POST":
                return self.json_reply(self.repository.query_data(actor, query_request(payload)))
            if route == ["grading", "calculate"] and method == "POST":
                if set(payload) - {"items", "policy", "target"}:
                    raise LmsError("Нужны только items, policy и target.")
                items = payload.get("items")
                if not isinstance(items, list) or len(items) > 100 or any(not isinstance(item, dict) or set(item)-{"component", "score", "max_score", "weight"} for item in items):
                    raise LmsError("items: до 100 объектов component, score, max_score, weight.")
                return self.json_reply({"calculation": evaluate_grades(items, payload.get("policy"), payload.get("target", 50)),
                                        "simulation": True, "source": "explicit-request-input", "database_accessed": False,
                                        "notice": "Проверка формулы по введённым числам; это не оценки из LMS и не запись в ведомость."})
            if route == ["admin", "users"] and method == "GET":
                return self.json_reply({"items": self.repository.users(actor)})
            if route == ["admin", "students"] and method == "POST":
                return self.json_reply({"user": self.repository.create_student(actor, payload)}, 201)
            if route[0] == "admin":
                self.repository.require_admin(actor)
                kind = route[1] if len(route) > 1 else ""
                if kind not in KINDS:
                    raise LmsError("Коллекция не найдена.", 404)
                if method == "GET" and len(route) == 2:
                    audit = []
                    items = self.repository.list(kind, actor, query.get("course_id", [None])[0], audit)
                    return self.json_reply({"items": items, "data_access": audit, "source": self.repository.source})
                if (method == "POST" and len(route) == 2) or (method == "PATCH" and len(route) == 3):
                    result = self.repository.save(kind, actor, payload, unquote(route[2]) if len(route) == 3 else None)
                    return self.json_reply({"item": result, "source": self.repository.source}, 201 if method == "POST" else 200)
                raise LmsError("Метод не поддерживается.", 405)
            if actor.role != "student":
                raise LmsError("Студенческий endpoint: войди как студент.", 403)
            cid = query.get("course_id", [None])[0]
            if len(route) == 1 and route[0] in KINDS and method == "GET":
                audit = []
                return self.json_reply({"items": self.repository.list(route[0], actor, cid, audit), "data_access": audit,
                                        "source": self.repository.source, "team_database_connected": self.repository.team_database_connected})
            if route in [["grade-summary"], ["attendance-summary"]] and method == "GET":
                if not cid:
                    raise LmsError("Выбери course_id.")
                args = {"course_id": cid}
                name = "get_attendance"
                if route == ["grade-summary"]:
                    name = "get_grades"; args["target"] = query.get("target", [50])[0]
                result = LmsTools(self.repository, actor).call(name, args)
                return self.json_reply(result, result.get("status", 200))
            if route in [["agent", "query"], ["agent", "stream"]] and method == "POST":
                connection = None  # Provider integration is a separate, explicitly configured step.
                emit = None
                if route[-1] == "stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers(); self.sse_started = True
                    emit = self.emit
                    emit({"type": "started", "source": self.repository.source})
                result = asyncio.run(asyncio.wait_for(run_lms_query(self.repository, self.lms_token(), payload, connection, emit,
                                    transport=getattr(self.server, "transport", "mcp")), timeout=100))
                if self.sse_started:
                    self.emit({"type": "complete", "response": result})
                    return
                return self.json_reply(result)
            raise LmsError("Endpoint не найден.", 404)
        except Exception as error:
            leaves = exception_leaves(error)
            safe = next((item for item in leaves if isinstance(item, (LmsError, GeminiError))), None)
            if safe:
                message, status = str(safe), getattr(safe, "status", 400)
            elif isinstance(error, (ValueError, KeyError, TypeError)):
                message, status = "Проверь формат и обязательные поля запроса.", 400
            elif isinstance(error, TimeoutError):
                message, status = "Превышено время ожидания.", 504
            else:
                message, status = "Ошибка обработки LMS. Содержимое и секреты не записаны в журнал.", 500
            if isinstance(error, (BrokenPipeError, ConnectionResetError)):
                return
            if self.sse_started:
                self.emit({"type": "error", "error": message, "status": status, "data_access": getattr(safe, "data_access", [])})
            else:
                self.json_reply({"error": message, "data_access": getattr(safe, "data_access", [])}, status)
        finally:
            SLOTS.release()

    def emit(self, event):
        self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
        self.wfile.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--check", action="store_true", help="Validate local configuration and dependencies without opening a port or calling a model")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if importlib.util.find_spec("mcp") is None:
        raise SystemExit("MCP missing. Install requirements.txt into the project .venv. No direct fallback is used.")
    try:
        repository = open_repository()
    except LmsError as error:
        raise SystemExit(str(error)) from None
    if args.check:
        print(f"OK: repository={repository.source}, temporary local auth, MCP installed; no database/model/network request performed.")
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), LmsHandler)
    except OSError:
        raise SystemExit(f"Cannot bind 127.0.0.1:{args.port}. Check the port or pass --port <number>.") from None
    server.repository, server.transport = repository, "mcp"
    server.daemon_threads = True
    print(f"CampusPulse backend: http://127.0.0.1:{args.port}/api/v1/status | {repository.source} | cloud deployment disabled", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
