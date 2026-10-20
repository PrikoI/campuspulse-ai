"""Validated request-scoped data and a deterministic, deadline-aware planner."""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Qyzylorda")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Укажите часовой пояс в дате, например +05:00.")
    return result.astimezone(TZ)


def validate_context(raw: dict | None) -> dict:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError("Контекст должен быть объектом JSON.")
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list) or len(tasks) > 100:
        raise ValueError("Допускается до 100 задач.")
    clean, ids = [], set()
    for item in tasks:
        title = str(item.get("title", "")).strip()
        if not title or len(title) > 200:
            raise ValueError("Название задачи: от 1 до 200 символов.")
        minutes = item.get("minutes", 60)
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not math.isfinite(minutes) or not 10 <= minutes <= 2400:
            raise ValueError("Оценка задачи: от 10 до 2400 минут.")
        due = item.get("due")
        if due:
            due = parse_time(due).isoformat()
        task_id = str(item.get("id") or uuid.uuid4().hex)[:120]
        if task_id in ids:
            raise ValueError("Идентификаторы задач должны быть уникальны.")
        ids.add(task_id)
        clean.append({"id": task_id, "title": title, "course": str(item.get("course", "Личное"))[:80],
                      "due": due, "minutes": int(minutes), "done": item.get("done") is True,
                      "source": "user", "url": None})
    hours = raw.get("hours_per_day", 3)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or not 1 <= hours <= 8:
        raise ValueError("Учебная нагрузка: от 1 до 8 часов в день.")
    repository = str(raw.get("repository", "")).strip()
    if repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Репозиторий указывается как owner/repository.")
    notes = raw.get("notes", [])
    if not isinstance(notes, list) or len(notes) > 5:
        raise ValueError("Можно приложить до пяти материалов.")
    clean_notes = [{"name": str(n.get("name", "Материал"))[:150], "text": str(n.get("text", ""))[:50000]} for n in notes]
    busy = []
    for block in raw.get("busy", []):
        start, end = parse_time(block["start"]), parse_time(block["end"])
        if end <= start:
            raise ValueError("Конец занятого интервала должен быть позже начала.")
        busy.append({"start": start.isoformat(), "end": end.isoformat()})
    if len(busy) > 100:
        raise ValueError("Допускается до 100 занятых интервалов.")
    return {"tasks": clean, "hours_per_day": hours, "repository": repository,
            "notes": clean_notes, "busy": busy}


def build_plan(tasks: list[dict], hours_per_day: float = 3, busy: list[dict] | None = None,
               now: datetime | None = None) -> dict:
    """Earliest deadline first; 50-minute blocks, 10-minute breaks, 09:00–21:00.

    The daily limit counts study time. Busy intervals and breaks consume wall time.
    Overdue tasks are not silently rescheduled beyond their deadlines.
    """
    now = (now or datetime.now(TZ)).astimezone(TZ)
    horizon = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)
    cursor = now.replace(second=0, microsecond=0)
    if cursor < now:
        cursor += timedelta(minutes=1)
    occupied = sorted((parse_time(b["start"]), parse_time(b["end"])) for b in (busy or []))
    capacity = int(hours_per_day * 60)
    usage, blocks, risks, unscheduled = {}, [], [], []
    pending = [t for t in tasks if not t.get("done")]
    pending.sort(key=lambda t: parse_time(t["due"]) if t.get("due") else horizon + timedelta(days=365))
    for task in pending:
        if not task.get("due"):
            unscheduled.append({"task_id": task["id"], "title": task["title"], "minutes": task["minutes"], "reason": "Нет подтверждённого дедлайна. Укажите дату и оценку времени."})
            continue
        deadline = parse_time(task["due"])
        remaining = task["minutes"]
        if deadline <= now:
            risks.append({"task_id": task["id"], "title": task["title"], "reason": "Дедлайн уже прошёл", "remaining_minutes": remaining})
            continue
        # Use a task-local cursor: an infeasible early deadline must not consume
        # empty time that can be used for a later assignment.
        position = cursor
        while remaining and position < min(deadline, horizon):
            opening = position.replace(hour=9, minute=0, second=0, microsecond=0)
            closing = position.replace(hour=21, minute=0, second=0, microsecond=0)
            if position < opening:
                position = opening
            date_key = position.date().isoformat()
            available = capacity - usage.get(date_key, 0)
            if position >= closing or available <= 0:
                position = (position + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
                continue
            overlapping = next(((a, b) for a, b in occupied if a <= position < b), None)
            if overlapping:
                position = overlapping[1]
                continue
            next_busy = min((a for a, _ in occupied if a > position), default=horizon)
            limit = min(closing, deadline, horizon, next_busy)
            minutes = min(50, remaining, available, int((limit - position).total_seconds() // 60))
            if minutes <= 0:
                break
            end = position + timedelta(minutes=minutes)
            blocks.append({"task_id": task["id"], "title": task["title"], "course": task.get("course", ""),
                           "start": position.isoformat(), "end": end.isoformat(), "minutes": minutes,
                           "source": task.get("source", "user"), "url": task.get("url")})
            usage[date_key] = usage.get(date_key, 0) + minutes
            remaining -= minutes
            position = end + timedelta(minutes=10)
            cursor = position
        if remaining:
            risks.append({"task_id": task["id"], "title": task["title"],
                          "reason": "Не помещается в доступное время до дедлайна / за 7 дней", "remaining_minutes": remaining})
    blocks.sort(key=lambda b: b["start"])
    return {"blocks": blocks, "risks": risks, "unscheduled": unscheduled,
            "scheduled_minutes": sum(b["minutes"] for b in blocks), "daily_minutes": usage,
            "timezone": "Asia/Qyzylorda", "generated_at": now.isoformat(), "horizon_end": horizon.isoformat(),
            "policy": "09:00–21:00; блоки до 50 минут; перерыв 10 минут; ближайший дедлайн первым"}
