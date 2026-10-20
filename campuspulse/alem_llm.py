"""Alem Gemma provider. Credentials stay on the server; no SDK dependency."""
import asyncio
import inspect
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from .domain import TZ
from .lms_store import LmsError

LOCAL_CONFIG = Path(__file__).resolve().parent.parent / ".local" / "alem.json"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ENDPOINT = "https://llm.alem.ai/v1/chat/completions"


def env_config():
    """Read only Alem settings. Literal values; no expansion or shell execution."""
    allowed = {"CAMPUSPULSE_LLM_PROVIDER", "CAMPUSPULSE_ALEM_API_KEY",
               "CAMPUSPULSE_ALEM_MODEL", "CAMPUSPULSE_ALEM_ENABLED",
               "OPENAI_API_KEY", "GEMMA_MODEL"}
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return {}
    except OSError:
        raise LmsError("Не удалось прочитать серверный .env.", 503) from None
    values = {}
    for line in lines:
        key, separator, value = line.strip().partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in allowed:
            continue
        if key in values:
            raise LmsError("Повторяющиеся настройки Alem в .env.", 503)
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise LmsError("Некорректные кавычки настройки Alem в .env.", 503)
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def local_config():
    try:
        value = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise LmsError("Не удалось прочитать локальную конфигурацию Alem.", 503) from None


@dataclass(frozen=True)
class AlemConfig:
    api_key: str = field(repr=False)
    model: str = "gemma4"
    enabled: bool = False

    @classmethod
    def from_environment(cls):
        local = local_config()
        dotenv = env_config()
        def setting(primary, alias, default):
            # Explicit Alem settings take priority, including an explicit empty key.
            for name in (primary, alias):
                if name in os.environ:
                    return os.environ[name]
                if name in dotenv:
                    return dotenv[name]
            return default
        enabled = os.getenv("CAMPUSPULSE_ALEM_ENABLED", dotenv.get("CAMPUSPULSE_ALEM_ENABLED"))
        return cls(setting("CAMPUSPULSE_ALEM_API_KEY", "OPENAI_API_KEY", local.get("api_key", "")),
                   setting("CAMPUSPULSE_ALEM_MODEL", "GEMMA_MODEL", local.get("model", "gemma4")),
                   enabled == "1" if enabled is not None else local.get("enabled") is True)

    @property
    def configured(self):
        return bool(isinstance(self.api_key, str) and self.api_key.strip()
                    and isinstance(self.model, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", self.model))

    def require_enabled(self):
        if not self.enabled or not self.configured:
            raise LmsError("Alem выключен или не настроен. Укажите серверный ключ и разрешите вызовы Alem.", 503)


def completion(config, messages, tools=None):
    """One bounded request to the fixed provider origin, without automatic retries."""
    config.require_enabled()
    payload = {"model": config.model, "messages": messages, "max_tokens": 1200}
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    try:
        with requests.post(ENDPOINT, headers={"Authorization": "Bearer " + config.api_key},
                           json=payload, timeout=(10, 45), allow_redirects=False) as response:
            if response.status_code != 200:
                # Never expose upstream bodies/headers: they may contain credentials.
                status = response.status_code
                message = {401: "Alem отклонил ключ API.", 403: "Нет доступа к модели Alem.",
                           429: "Лимит запросов или квота Alem исчерпаны."}.get(status, "Ошибка API Alem; проверьте модель и доступность сервиса.")
                raise LmsError(message, 503)
            result = response.json()
            message = result["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError()
            return message
    except LmsError:
        raise
    except Exception:
        raise LmsError("Alem недоступен или вернул некорректный ответ. Автоповтора нет.", 503) from None


async def alem_loop(message, schemas, invoke, config, instruction, report=None, *, before_request=None, history=None):
    config.require_enabled()
    tools = [{"type": "function", "function": {"name": spec["name"], "description": spec["description"],
              "parameters": spec["inputSchema"]}} for spec in schemas]
    messages = [{"role": "system", "content": instruction + f"\nТекущее время: {datetime.now(TZ).isoformat()}."},
                *({"role": item["role"], "content": item["content"]} for item in history or []),
                {"role": "user", "content": message}]
    allowed = {spec["name"] for spec in schemas}
    calls = 0
    for step in range(3):
        if before_request:
            if inspect.iscoroutinefunction(before_request):
                await before_request()
            else:
                await asyncio.to_thread(before_request)
        if report:
            report({"type": "model_start", "provider": "alem", "model": config.model, "step": step + 1})
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(completion, config, messages, tools)
        except LmsError:
            if report:
                report({"type": "model_result", "provider": "alem", "model": config.model, "status": "error"})
            raise
        if report:
            report({"type": "model_result", "provider": "alem", "model": config.model, "status": "ok",
                    "duration_ms": round((time.perf_counter() - started) * 1000)})
        functions = response.get("tool_calls") or []
        if not functions:
            text = response.get("content")
            if not isinstance(text, str) or not text.strip():
                raise LmsError("Alem не вернул текст ответа или вызов инструмента.", 502)
            return text
        # Keep only protocol fields; never publish provider reasoning_content.
        if not isinstance(functions, list) or len(functions) > 8 - calls:
            raise LmsError("Достигнут лимит восьми инструментов.", 502)
        clean = []
        for item in functions:
            try:
                function = item["function"]
                name, raw, call_id = function["name"], function["arguments"], item["id"]
                if name not in allowed or not isinstance(raw, str) or len(raw) > 10000 or not isinstance(call_id, str) or not call_id or len(call_id) > 200:
                    raise ValueError()
                args = json.loads(raw)
                if not isinstance(args, dict):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise LmsError("Alem вернул недопустимый вызов инструмента.", 502) from None
            clean.append((call_id, name, raw, args))
        messages.append({"role": "assistant", "content": response.get("content") or None,
                         "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}
                                        for call_id, name, raw, _ in clean]})
        for call_id, name, _, args in clean:
            calls += 1
            result = await invoke(name, args)
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": json.dumps(result, ensure_ascii=False, allow_nan=False)})
    return "Достигнут лимит трёх шагов модели. Уточните запрос."
