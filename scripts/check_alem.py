"""Explicit live smoke: synthetic data only, no Firestore or user records."""
import argparse
import asyncio
import json

from campuspulse.alem_llm import AlemConfig, alem_loop
from campuspulse.lms_store import LmsError


async def check():
    called = []
    async def invoke(name, args):
        if name != "check_connection" or args:
            raise LmsError("Unexpected smoke tool call.", 502)
        called.append(name)
        return {"connected": True, "marker": "campuspulse-smoke"}
    schema = [{"name": "check_connection", "description": "Check the synthetic CampusPulse connection. Call once before answering.",
               "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]
    answer = await alem_loop("Call check_connection once. Then report its marker. This is a synthetic integration check.",
                             schema, invoke, AlemConfig.from_environment(),
                             "Use the provided function to check the connection before answering. Do not invent results.")
    if not called or "campuspulse-smoke" not in answer:
        raise LmsError("Alem ответил, но полный function-calling цикл не подтверждён.", 502)
    return {"provider": "alem", "model": AlemConfig.from_environment().model,
            "function_calling": True, "tool_calls": len(called), "live_verified": True,
            "user_data_sent": False, "firestore_accessed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow up to three actual Alem model requests")
    if not parser.parse_args().live:
        parser.error("Pass --live explicitly to call Alem")
    try:
        print(json.dumps(asyncio.run(check()), ensure_ascii=False))
    except LmsError as error:
        print(json.dumps({"live_verified": False, "status": error.status, "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
