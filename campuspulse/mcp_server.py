"""Real MCP stdio server; stdout belongs exclusively to the protocol."""
import json

from mcp.server.fastmcp import FastMCP

from .domain import validate_context
from .tools import ToolRegistry

mcp = FastMCP("CampusPulse student tools")
registry = ToolRegistry(validate_context({}))


@mcp.tool()
def load_context(context: dict) -> dict:
    """Initialize this isolated session with student-approved data."""
    global registry
    registry = ToolRegistry(validate_context(context))
    return {"loaded": True, "tasks": len(registry.context["tasks"]), "notes": len(registry.context["notes"])}


@mcp.tool()
def list_assignments() -> dict:
    """Read current assignments entered by the student."""
    return registry.call("list_assignments")


@mcp.tool()
def github_assignments() -> dict:
    """Read real open GitHub issues from the repository selected by the student."""
    return registry.call("github_assignments")


@mcp.tool()
def plan_week() -> dict:
    """Plan seven days using confirmed deadlines, daily capacity and busy times."""
    return registry.call("plan_week")


@mcp.tool()
def search_notes(query: str) -> dict:
    """Find source excerpts in materials explicitly uploaded by the student."""
    return registry.call("search_notes", {"query": query})


if __name__ == "__main__":
    mcp.run(transport="stdio")
