"""Dry-run by default. No personal billing activation or paid fallback.

The execute path is supplied for a FUTURE organizer-funded project only.
It is not run by start.cmd, the app, tests, or the presentation builder.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="CampusPulse Agent Engine deployment plan; dry-run by default")
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--bucket", required=True, help="An EXISTING organizer-provided gs:// staging bucket")
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--model-location", default="global")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.bucket.startswith("gs://"):
        parser.error("bucket must start with gs://")
    plan = {"project": args.project, "location": args.location, "staging_bucket": args.bucket,
            "model": args.model, "model_location": args.model_location, "method": "reasoning_engines.ReasoningEngine.create", "dry_run": not args.execute,
            "cloud_calls_in_local_app": False}
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.execute:
        print("Dry-run only. No network request, resource creation or billing change was made.")
        return
    if os.getenv("CAMPUSPULSE_ALLOW_CLOUD") != "1" or os.getenv("CAMPUSPULSE_ORGANIZER_PROJECT") != args.project:
        raise SystemExit("DEPLOYMENT BLOCKED: an explicitly authorized organizer-funded project is required. No cloud call was made.")
    # Imports are deliberately below the guard: even default credential discovery
    # is unnecessary in the free local workflow.
    import vertexai
    from vertexai.preview import reasoning_engines
    from campuspulse.agent import CampusPulseAgent
    vertexai.init(project=args.project, location=args.location, staging_bucket=args.bucket)
    app = CampusPulseAgent(args.project, args.location, args.model, allow_cloud=True, model_location=args.model_location)
    remote = reasoning_engines.ReasoningEngine.create(
        app, display_name="CampusPulse AI", sys_version="3.12",
        requirements=[line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
                     + ["google-cloud-aiplatform[agent_engines]>=1.112,<2", "cloudpickle>=3,<4"],
        extra_packages=[str(ROOT / "campuspulse")],
    )
    output = {"resource_name": remote.resource_name, "project": args.project, "location": args.location}
    (ROOT / "deployment.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
