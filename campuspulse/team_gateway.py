"""The DB teammate's implementation entry point. No DB or records are created.

Configure CAMPUSPULSE_LMS_REPOSITORY=team and
CAMPUSPULSE_TEAM_GATEWAY=campuspulse.team_gateway:create_gateway.
Implement this class using the team's chosen database driver/service.
See docs/DATABASE_QUICKSTART.md for the exact request/response contract.
"""
from __future__ import annotations

from .lms_store import LmsError, Principal


class TeamDataGateway:
    source = "team-unconfigured"
    connected = False

    def __init__(self):
        # TODO: Read the agreed connection settings from server environment.
        # Initialize the team's real driver and check readiness. Do not seed
        # records or create a replacement DB. Set connected=True only after
        # successful readiness, and source to an honest source identifier.
        pass

    def describe(self, actor: Principal) -> list[dict]:
        # TODO: Return metadata for ALL resources permitted to actor:
        # [{name: str, label: str, description: str,
        #   fields: {public_field: type_name}, filterable: [public_field]}].
        # Resource names can map to tables, collections, views, or service
        # methods. No predefined LMS names are required for generic queries.
        # Do not advertise credentials, private fields or other users' data.
        raise LmsError("Каталог базы команды ещё не подключён.", 503)

    def query(self, actor: Principal, resource: str, *, filters: dict,
              fields: list[str] | None, limit: int, cursor: str | None) -> dict:
        # TODO: Resolve the public name through your resource registry, enforce
        # actor's scope inside the query, apply equality filters and projection,
        # use bound driver parameters, and fetch at most limit actual records.
        # Return {items: list[dict], next_cursor: str | None}. JSON values only.
        # A cursor must be bound to the same scope/filter/order and revalidated.
        # For an outage, raise LmsError(...,503); do not return an empty dataset.
        raise LmsError("Чтение базы команды ещё не подключено.", 503)

    def mcp_environment(self) -> dict[str, str]:
        # TODO: Explicitly forward the required connection settings so the
        # separate MCP process reaches the same source. Never return unrelated
        # environment secrets. These values are private process configuration.
        return {}


def create_gateway() -> TeamDataGateway:
    return TeamDataGateway()
