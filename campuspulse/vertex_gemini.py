"""Explicit, bounded Vertex AI provider. Import/status never discover ADC or call cloud."""
import asyncio
import inspect
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime

from .domain import TZ
from .lms_store import LmsError
from .config import google_credentials


@dataclass(frozen=True)
class VertexConfig:
    project: str
    location: str
    model: str
    enabled: bool = False

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
                   os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip(),
                   os.getenv("CAMPUSPULSE_VERTEX_MODEL", "").strip(),
                   os.getenv("CAMPUSPULSE_ALLOW_CLOUD", "0") == "1")

    @property
    def configured(self):
        return bool(re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", self.project)
                    and re.fullmatch(r"[a-z0-9-]{1,63}", self.location)
                    and re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", self.model))

    def require_enabled(self):
        if not self.enabled:
            raise LmsError("Модельные вызовы выключены: требуется явное CAMPUSPULSE_ALLOW_CLOUD=1.", 503)
        if not self.configured:
            raise LmsError("Укажите согласованные GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION и CAMPUSPULSE_VERTEX_MODEL.", 503)


def vertex_status():
    config = VertexConfig.from_environment()
    return {"provider": "vertex-ai", "project": config.project, "location": config.location,
            "model": config.model, "configured": config.configured,
            "calls_enabled": config.enabled and config.configured,
            "adc_verified": False, "live_verified": False}


async def vertex_loop(message, schemas, invoke, config, instruction, report=None, *, before_request=None, history=None):
    config.require_enabled()
    import google.auth
    from google import genai
    from google.genai import types

    try:
        credential = await asyncio.to_thread(google_credentials)
    except Exception:
        raise LmsError("ADC для Vertex AI недоступны. Проверьте серверную identity.", 503) from None
    declarations = [types.FunctionDeclaration(name=spec["name"], description=spec["description"],
                    parameters_json_schema=spec["inputSchema"]) for spec in schemas]
    contents = [types.Content(role="model" if item["role"] == "assistant" else "user",
                              parts=[types.Part.from_text(text=item["content"])]) for item in history or []]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
    instruction += f"\nТекущее время: {datetime.now(TZ).isoformat()}."
    calls = 0
    try:
        client = await asyncio.to_thread(genai.Client, vertexai=True, project=config.project,
            location=config.location, credentials=credential,
            http_options=types.HttpOptions(api_version="v1", timeout=45000,
                                           retry_options=types.HttpRetryOptions(attempts=1)))
    except Exception:
        raise LmsError("Не удалось создать клиент Vertex AI.", 503) from None
    try:
        for step in range(3):
            # Recheck identity/budget before EVERY model request, not only bootstrap.
            if before_request:
                if inspect.iscoroutinefunction(before_request):
                    await before_request()
                else:
                    await asyncio.to_thread(before_request)
            if report:
                report({"type": "model_start", "provider": "vertex-ai", "model": config.model, "step": step + 1})
            started = time.perf_counter()
            try:
                response = await asyncio.to_thread(client.models.generate_content, model=config.model, contents=contents,
                    config=types.GenerateContentConfig(system_instruction=instruction, temperature=1.0,
                        max_output_tokens=1200, tools=[types.Tool(function_declarations=declarations)],
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
            except Exception:
                if report:
                    report({"type": "model_result", "provider": "vertex-ai", "model": config.model, "status": "error"})
                raise LmsError("Vertex AI недоступен: проверьте доступ, квоту и модель. Автоповтора нет.", 503) from None
            if report:
                report({"type": "model_result", "provider": "vertex-ai", "model": config.model, "status": "ok",
                        "duration_ms": round((time.perf_counter() - started) * 1000)})
            if not response.candidates or not response.candidates[0].content:
                raise LmsError("Vertex AI не вернул содержимое ответа.", 502)
            content = response.candidates[0].content
            contents.append(content)  # Preserve call IDs and thought signatures unchanged.
            functions = [part.function_call for part in content.parts or [] if part.function_call]
            if not functions:
                return "\n".join(part.text for part in content.parts or [] if part.text and not part.thought) or "Модель не вернула текст."
            parts = []
            for function in functions:
                calls += 1
                if calls > 8:
                    return "Достигнут лимит восьми инструментов. Уточните запрос."
                result = await invoke(function.name, dict(function.args or {}))
                part = types.Part.from_function_response(name=function.name, response=result)
                if function.id:
                    part.function_response.id = function.id
                parts.append(part)
            contents.append(types.Content(role="tool", parts=parts))
        return "Достигнут лимит трёх шагов модели. Уточните запрос."
    finally:
        await asyncio.to_thread(client.close)
