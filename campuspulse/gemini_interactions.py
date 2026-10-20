"""Google Gemini Developer API provider using the Interactions API."""
import asyncio
import inspect
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from .domain import TZ
from .lms_store import LmsError


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str = field(repr=False)
    model: str = "gemini-3.8-flash"
    enabled: bool = False

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("CAMPUSPULSE_GEMINI_API_KEY", "").strip(),
                   os.getenv("CAMPUSPULSE_GEMINI_MODEL", "gemini-3.8-flash").strip(),
                   os.getenv("CAMPUSPULSE_GEMINI_ENABLED", "0") == "1")

    @property
    def configured(self):
        return bool(self.api_key and re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", self.model))

    def require_enabled(self):
        if not self.enabled:
            raise LmsError("Вызовы Gemini API выключены: задайте CAMPUSPULSE_GEMINI_ENABLED=1.", 503)
        if not self.configured:
            raise LmsError("Укажите серверный CAMPUSPULSE_GEMINI_API_KEY и корректную CAMPUSPULSE_GEMINI_MODEL.", 503)


def gemini_status():
    config = GeminiConfig.from_environment()
    return {"provider": "gemini-api", "model": config.model, "configured": config.configured,
            "calls_enabled": config.enabled and config.configured, "live_verified": False}


async def gemini_loop(message, schemas, invoke, config, instruction, report=None, *, before_request=None, history=None):
    config.require_enabled()
    from google import genai

    try:
        client = await asyncio.to_thread(genai.Client, api_key=config.api_key)
    except Exception:
        raise LmsError("Не удалось создать клиент Gemini API.", 503) from None

    tools = [{"type": "function", "name": spec["name"], "description": spec["description"],
              "parameters": spec["inputSchema"]} for spec in schemas]
    turns = [{"role": "model" if item["role"] == "assistant" else "user", "content": item["content"]}
             for item in history or []]
    turns.append({"role": "user", "content": message})
    instruction += f"\nТекущее время: {datetime.now(TZ).isoformat()}."
    allowed = {spec["name"] for spec in schemas}
    calls = 0
    try:
        for step in range(3):
            if before_request:
                if inspect.iscoroutinefunction(before_request):
                    await before_request()
                else:
                    await asyncio.to_thread(before_request)
            if report:
                report({"type": "model_start", "provider": "gemini-api", "model": config.model, "step": step + 1})
            started = time.perf_counter()
            try:
                response = await asyncio.to_thread(
                    client.interactions.create, model=config.model, input=turns,
                    system_instruction=instruction, tools=tools, store=False, timeout=45,
                )
            except Exception:
                if report:
                    report({"type": "model_result", "provider": "gemini-api", "model": config.model, "status": "error"})
                raise LmsError("Gemini API недоступен: проверьте ключ, модель и квоту. Автоповтора нет.", 503) from None
            if report:
                report({"type": "model_result", "provider": "gemini-api", "model": config.model, "status": "ok",
                        "duration_ms": round((time.perf_counter() - started) * 1000)})

            outputs = getattr(response, "outputs", None)
            if getattr(response, "status", None) not in {None, "completed", "requires_action"} or not isinstance(outputs, list):
                raise LmsError("Gemini API не вернул завершённый ответ.", 502)
            functions = [item for item in outputs if getattr(item, "type", None) == "function_call"]
            if not functions:
                text = "\n".join(item.text for item in outputs
                                 if getattr(item, "type", None) == "text" and isinstance(item.text, str))
                if not text.strip():
                    raise LmsError("Gemini API не вернул текст ответа или вызов инструмента.", 502)
                return text
            if calls + len(functions) > 8:
                raise LmsError("Достигнут лимит восьми инструментов.", 502)

            turns.append({"role": "model", "content": [
                item.model_dump(exclude_none=True) for item in outputs
            ]})
            results = []
            for function in functions:
                name, call_id, arguments = function.name, function.id, function.arguments
                if name not in allowed or not isinstance(call_id, str) or not call_id or not isinstance(arguments, dict):
                    raise LmsError("Gemini API вернул недопустимый вызов инструмента.", 502)
                calls += 1
                result = await invoke(name, dict(arguments))
                item = {"type": "function_result", "call_id": call_id, "name": name,
                        "result": json.dumps(result, ensure_ascii=False, allow_nan=False)}
                signature = getattr(function, "signature", None)
                if signature:
                    item["signature"] = signature
                results.append(item)
            turns.append({"role": "user", "content": results})
        return "Достигнут лимит трёх шагов модели. Уточните запрос."
    finally:
        await asyncio.to_thread(client.close)
