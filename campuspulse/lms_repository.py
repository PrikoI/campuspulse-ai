"""The single adapter selection point shared by the API and MCP subprocess.

Register the teammate's implementation here; never silently pretend it exists.
Auth/session and model-budget methods are part of the repository contract too.
"""
import os
from .lms_store import LmsError
from .lms_pending import PendingRepository


def open_repository(path=None, seed_demo=False, bootstrap=True):
    if path is not None:
        raise LmsError("Локальные файлы базы не поддерживаются. Используйте только будущий адаптер команды.")
    if seed_demo:
        raise LmsError("Заполнение учебной базы отключено по запросу команды.")
    name = os.getenv("CAMPUSPULSE_LMS_REPOSITORY", "pending")
    if name == "team":
        from .lms_team_adapter import TeamRepository
        return TeamRepository()
    if name != "pending":
        raise LmsError("Командный адаптер ещё не подключён. Собственные базы отключены; локальная подмена не выполнялась.", 503)
    return PendingRepository()
