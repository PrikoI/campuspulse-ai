"""Read-only tools. External text is data, never executable instructions."""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import TZ, build_plan

SCHEMAS = [
    {"name": "list_assignments", "description": "Read the student's current assignments with confirmed deadlines.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "github_assignments", "description": "Fetch current open issues from the public GitHub repository explicitly provided by the student. Milestone due dates are real deadlines; never infer a deadline from updated_at.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "plan_week", "description": "Calculate a 7-day study schedule using assignments, daily capacity, busy intervals and any GitHub issues already retrieved. Reports overdue and infeasible work.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "search_notes", "description": "Search materials that the student explicitly uploaded; return excerpts with filenames.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Words to look for in the study materials"}}, "required": ["query"]}},
]


def fetch_github(repository: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Добавьте публичный репозиторий owner/repository в настройках.")
    url = f"https://api.github.com/repos/{repository}/issues?state=open&per_page=30&sort=updated"
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "CampusPulse-Hackathon/0.1", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urlopen(request, timeout=15) as response:
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("Ответ GitHub слишком большой.")
            issues = json.loads(data)
    except HTTPError as exc:
        explanations = {403: "GitHub ограничил запросы. Повторите позже.", 429: "GitHub ограничил запросы. Повторите позже.", 404: "Репозиторий не найден или приватный."}
        raise ValueError(explanations.get(exc.code, f"GitHub вернул HTTP {exc.code}.")) from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("GitHub недоступен. Проверьте интернет; данные не подменяются примерами.") from exc
    result = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        milestone = issue.get("milestone") or {}
        result.append({"id": f"github:{repository}:{issue['number']}", "title": str(issue["title"])[:200],
                       "course": repository, "due": milestone.get("due_on"), "minutes": 60, "done": False,
                       "source": "github", "url": issue["html_url"], "estimate_is_assumption": True,
                       "labels": [label["name"] for label in issue.get("labels", [])]})
    return {"tasks": result, "source_url": f"https://github.com/{repository}/issues", "fetched_at": datetime.now(TZ).isoformat(),
            "warning": "До 30 последних issues/PR в ответе; PR исключаются. Дедлайн берётся только из milestone. Оценка 60 минут — предположение, уточните её."}


class ToolRegistry:
    def __init__(self, context: dict):
        self.context = context
        self.github = []
        self.last_plan = None

    def call(self, name: str, arguments: dict | None = None) -> dict:
        arguments = arguments or {}
        if name not in {schema["name"] for schema in SCHEMAS}:
            raise ValueError("Неизвестный инструмент.")
        allowed = {"query"} if name == "search_notes" else set()
        if set(arguments) - allowed:
            raise ValueError("Недопустимые аргументы инструмента.")
        if name == "list_assignments":
            return {"tasks": self.context["tasks"], "source": "Данные, введённые студентом в этом браузере"}
        if name == "github_assignments":
            result = fetch_github(self.context["repository"])
            self.github = result["tasks"]
            return result
        if name == "plan_week":
            self.last_plan = build_plan(self.context["tasks"] + self.github, self.context["hours_per_day"], self.context["busy"])
            return self.last_plan
        query = str(arguments.get("query", "")).strip()
        if not query or len(query) > 500:
            raise ValueError("Поисковый запрос: от 1 до 500 символов.")
        words = set(re.findall(r"\w{2,}", query.casefold()))
        matches = []
        for note in self.context["notes"]:
            paragraphs = re.split(r"\n\s*\n|(?<=[.!?])\s+", note["text"])
            for paragraph in paragraphs:
                score = sum(word in paragraph.casefold() for word in words)
                if score:
                    matches.append({"filename": note["name"], "excerpt": paragraph[:1400], "score": score})
        matches.sort(key=lambda match: match["score"], reverse=True)
        return {"matches": matches[:5], "method": "Лексический поиск по загруженным материалам; не семантический RAG"}
