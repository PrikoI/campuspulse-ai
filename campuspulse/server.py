"""Loopback-only web client and API. Nothing is stored on the server."""
from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import io
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse

from .agent import ROOT, run_query, settings
from .free_gemini import Connections, FREE_MODEL, ConnectionError as GeminiConnectionError

WEB = ROOT / "web"
LIMIT = 8_000_000
SLOTS = threading.BoundedSemaphore(2)
CONNECTIONS = Connections()


def exception_leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in exception_leaves(child)]
    return [error]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Avoid recording query text, uploaded material or credentials.
        print(f"{self.command} {self.path.split('?')[0]}", flush=True)

    def headers_for(self, status, mime, size):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if getattr(self, "new_session", False):
            self.send_header("Set-Cookie", f"campuspulse_session={self.session_token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")
        for cookie in getattr(self, "extra_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()

    def json_reply(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.headers_for(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def trusted_host(self):
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in expected:
            self.json_reply({"error": "Недопустимый Host."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in expected}:
            self.json_reply({"error": "Внешние сайты не могут отправлять запросы."}, 403)
            return False
        return True

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        token = cookie.get("campuspulse_session")
        self.session_token, self.new_session = CONNECTIONS.session(token.value if token else None)
        return CONNECTIONS.get(self.session_token)

    def status(self, connection):
        config = settings()
        return {**config, "mode": "developer" if connection else "local",
                "model": FREE_MODEL, "gemini_connected": connection is not None,
                "key_project": connection.project if connection else None,
                "billing_checked_disabled": connection is not None,
                "version": "0.2.0", "cloud_deployed": False,
                "pdf_available": importlib.util.find_spec("pypdf") is not None}

    def do_GET(self):
        if not self.trusted_host():
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            self.json_reply(self.status(self.session()))
            return
        files = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        if path not in files:
            self.json_reply({"error": "Не найдено"}, 404)
            return
        file = WEB / files[path]
        data = file.read_bytes()
        mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.headers_for(200, mime + "; charset=utf-8", len(data))
        self.wfile.write(data)

    def do_POST(self):
        if not self.trusted_host():
            return
        if not SLOTS.acquire(blocking=False):
            self.json_reply({"error": "Два запроса уже выполняются. Подождите."}, 429)
            return
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.json_reply({"error": "Нужен Content-Type application/json."}, 415)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > LIMIT:
                self.json_reply({"error": "Размер запроса должен быть от 1 байта до 8 МБ."}, 413)
                return
            raw = json.loads(self.rfile.read(length))
            if self.path == "/api/query":
                connection = self.session()
                config = {**settings(), "mode": "local"}
                if raw.get("mode") == "developer" and not connection:
                    raise ValueError("Сессия Gemini закончилась. Подключи ключ заново; запрос к модели не отправлен.")
                if connection and raw.get("mode") != "local":
                    config.update(mode="developer", model=connection.model, connection=connection)
                result = asyncio.run(asyncio.wait_for(run_query(raw.get("message", ""), raw.get("context", {}), config), timeout=100))
                self.json_reply(result)
            elif self.path == "/api/gemini/connect":
                self.session()
                connection = CONNECTIONS.connect(self.session_token, raw.get("api_key"))
                self.json_reply(self.status(connection))
            elif self.path == "/api/gemini/disconnect":
                self.session()
                CONNECTIONS.disconnect(self.session_token)
                self.json_reply(self.status(None))
            elif self.path == "/api/extract":
                name = str(raw.get("name", ""))
                data = base64.b64decode(raw.get("data", ""), validate=True)
                if len(data) > 5_000_000:
                    raise ValueError("Материал должен быть меньше 5 МБ.")
                if name.lower().endswith(".pdf"):
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(data))
                    if reader.is_encrypted:
                        raise ValueError("Зашифрованный PDF не поддерживается.")
                    if len(reader.pages) > 50:
                        raise ValueError("Допускается PDF до 50 страниц.")
                    pages = [page.extract_text() or "" for page in reader.pages]
                    if not any(page.strip() for page in pages):
                        raise ValueError("Нет извлекаемого текста. Для сканов требуется OCR, он не включён.")
                    text = "\n\n".join(f"[Страница {i+1}]\n{page}" for i, page in enumerate(pages))
                elif name.lower().endswith((".txt", ".md")):
                    text = data.decode("utf-8-sig")
                else:
                    raise ValueError("Поддерживаются PDF, TXT и Markdown.")
                if not text.strip():
                    raise ValueError("Нет извлекаемого текста. Для сканов требуется OCR, он не включён.")
                self.json_reply({"name": Path(name).name[:150], "text": text[:50000], "truncated": len(text) > 50000})
            else:
                self.json_reply({"error": "Не найдено"}, 404)
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError) as exc:
            self.json_reply({"error": str(exc)[:500]}, 400)
        except (TimeoutError, asyncio.TimeoutError):
            self.json_reply({"error": "Запрос превысил 100 секунд. Попробуйте ещё раз."}, 504)
        except ImportError:
            self.json_reply({"error": "Не установлены библиотеки. Выполните установку по README."}, 503)
        except Exception as exc:
            leaves = exception_leaves(exc)
            known = next((leaf for leaf in leaves if isinstance(leaf, GeminiConnectionError)), None)
            if known:
                # anyio/MCP can wrap a safe provider error in an ExceptionGroup.
                self.json_reply({"error": str(known)}, 400)
            else:
                # Only exception classes and code locations, never messages,
                # request bodies, credentials, locals, or remote error bodies.
                for leaf in leaves:
                    tb = leaf.__traceback__
                    while tb and tb.tb_next:
                        tb = tb.tb_next
                    where = f"{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}" if tb else "unknown"
                    print(f"Request failed: {type(leaf).__name__} at {where}", flush=True)
                self.json_reply({"error": "Ошибка обработки. Проверьте формат материала или настройки подключения. Секреты и содержимое документов не записаны в журнал."}, 500)
        finally:
            SLOTS.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    config = settings()
    if config["mode"] != "local" and not config["cloud_allowed"]:
        raise SystemExit("Cloud calls are disabled. Use CAMPUSPULSE_MODE=local.")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"CampusPulse: http://127.0.0.1:{args.port} | {config['mode']} | {config['transport']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
