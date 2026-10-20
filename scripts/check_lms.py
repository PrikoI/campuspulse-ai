"""Offline LMS checks: loopback HTTP and local stdio MCP only.

Firestore tests use an injected in-memory double and mocked SDK transport.
No real API keys, model requests or cloud resource operations.
Legacy demo suites are deliberately excluded.
"""
import os
import sys
import unittest
from pathlib import Path


def deny_external_connections(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
        address = args[1] if event == "socket.connect" else args[0]
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("External networking is disabled in the LMS offline checks.")


def main():
    os.environ.update(CAMPUSPULSE_LMS_REPOSITORY="pending", CAMPUSPULSE_ALLOW_CLOUD="0", CAMPUSPULSE_LLM_PROVIDER="vertex", CAMPUSPULSE_ALEM_ENABLED="0",
                      CAMPUSPULSE_MODE="local", CAMPUSPULSE_TRANSPORT="mcp", CAMPUSPULSE_TEAM_GATEWAY="")
    # Applies to this test process. MCP children only import the pending adapter;
    # no credentials are forwarded to the child by lms_tool_session.
    sys.addaudithook(deny_external_connections)
    root = Path(__file__).resolve().parent.parent
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_lms*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
