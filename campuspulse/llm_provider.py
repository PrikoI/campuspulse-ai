"""Server-selected LMS provider. Model/user arguments cannot select credentials."""
import os

from .alem_llm import AlemConfig, LOCAL_CONFIG, alem_loop, env_config
from .lms_store import LmsError
from .vertex_gemini import VertexConfig, vertex_loop, vertex_status


def provider_name():
    name = os.getenv("CAMPUSPULSE_LLM_PROVIDER", env_config().get("CAMPUSPULSE_LLM_PROVIDER", "alem" if LOCAL_CONFIG.is_file() else "vertex"))
    if name not in {"alem", "vertex"}:
        raise LmsError("Неизвестный серверный LLM provider.", 503)
    return name


def model_provider():
    if provider_name() == "alem":
        return "alem", AlemConfig.from_environment(), alem_loop
    return "vertex-ai", VertexConfig.from_environment(), vertex_loop


def llm_status():
    name, config, _ = model_provider()
    if name == "vertex-ai":
        return vertex_status()
    return {"provider": name, "model": config.model, "configured": config.configured,
            "calls_enabled": config.enabled and config.configured, "live_verified": False}
