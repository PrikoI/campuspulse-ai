"""Private stdio MCP process; authenticated session supplied by the API only."""
import os
from typing import Any
from mcp.server.fastmcp import FastMCP
from .lms_repository import open_repository
from .lms_tools import LmsTools
from .lms_store import LmsError
from .lms_json import json_result, tool_error

mcp = FastMCP("CampusPulse LMS")
tools = None
repository = None
token = None


@mcp.tool()
def load_session(session_token: str) -> dict:
    """Internal bootstrap; never advertised to Gemini."""
    global tools, repository, token
    repository = open_repository(bootstrap=False)
    token = session_token
    actor = repository.principal(token)
    tools = LmsTools(repository, actor)
    return {"authenticated": True, "source": repository.source}


def invoke(name, args=None):
    if tools is None:
        raise ValueError("Authenticated LMS session required.")
    try:
        repository.principal(token)  # Recheck expiry/revocation on every invocation.
        return json_result(tools.call(name, args))
    except LmsError as error:
        return {**tool_error(error), "source": repository.source,
                "data_access": getattr(error, "data_access", [])}


@mcp.tool()
def get_schedule(course_id: str | None = None) -> dict[str, Any]:
    """Read upcoming lessons for the next seven days."""
    return invoke('get_schedule', {'course_id': course_id} if course_id else {})


@mcp.tool()
def prepare_study_plan(course_id: str | None = None, hours_per_day: float = 3) -> dict[str, Any]:
    """Calculate and propose personal study tasks; user confirmation is mandatory."""
    return invoke('prepare_study_plan', {'hours_per_day': hours_per_day, **({'course_id': course_id} if course_id else {})})


@mcp.tool()
def get_courses() -> dict[str, Any]:
    """Read enrolled courses for the authenticated student."""
    return invoke("get_courses")


@mcp.tool()
def get_personal_data() -> dict[str, Any]:
    """Read saved tasks and settings owned by the authenticated student."""
    return invoke("get_personal_data")


@mcp.tool()
def prepare_personal_change(target: str, payload: dict, operation: str = "save", record_id: str | None = None) -> dict[str, Any]:
    """Prepare a change for explicit user review; never writes data."""
    return invoke("prepare_personal_change", {"target": target, "payload": payload,
                                             "operation": operation, "record_id": record_id})


@mcp.tool()
def list_data_resources() -> dict[str, Any]:
    """Discover resources and public fields permitted for this session."""
    return invoke("list_data_resources")


@mcp.tool()
def query_data(resource: str, filters: dict | None = None, fields: list[str] | None = None,
               limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """Read a resource by catalog name; the database gateway enforces actor scope."""
    return invoke("query_data", {"resource": resource, "filters": filters or {}, "fields": fields, "limit": limit, "cursor": cursor})


@mcp.tool()
def get_assignments(course_id: str | None = None) -> dict[str, Any]:
    """Read current assignments from the student's LMS database."""
    return invoke("get_assignments", {"course_id": course_id} if course_id else {})


@mcp.tool()
def get_grades(course_id: str, target: float = 50) -> dict[str, Any]:
    """Read current grades and calculate the final score needed, without model arithmetic."""
    return invoke("get_grades", {"course_id": course_id, "target": target})


@mcp.tool()
def get_attendance(course_id: str) -> dict[str, Any]:
    """Read attendance; missing marks are not absences."""
    return invoke("get_attendance", {"course_id": course_id})


@mcp.tool()
def read_materials(course_id: str, query: str) -> dict[str, Any]:
    """Search course materials and return citations."""
    return invoke("read_materials", {"course_id": course_id, "query": query})


@mcp.tool()
def plan_study(course_id: str | None = None, hours_per_day: float = 3, extra_busy: list[dict] | None = None) -> dict[str, Any]:
    """Read LMS assignments and lessons, calculate a preparation plan. No calendar writes."""
    args = {"hours_per_day": hours_per_day, "extra_busy": extra_busy or []}
    if course_id:
        args["course_id"] = course_id
    return invoke("plan_study", args)


if __name__ == "__main__":
    mcp.run(transport="stdio")
