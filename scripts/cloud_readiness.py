"""Offline cloud configuration report; never reads or prints key contents."""
import json
import os
from pathlib import Path


def main():
    from campuspulse.config import load_config
    from campuspulse.vertex_gemini import VertexConfig
    load_config()
    config=VertexConfig.from_environment()
    required=['GOOGLE_CLOUD_PROJECT','CAMPUSPULSE_VERTEX_MODEL']
    missing=[key for key in required if not os.getenv(key)]
    result={'vertex_configured':config.configured,'model_calls_enabled':config.enabled,
            'agent_engine_resource_configured':bool(os.getenv('CAMPUSPULSE_AGENT_ENGINE_RESOURCE')),
            'shared_session_secret_configured':len(os.getenv('CAMPUSPULSE_LMS_SESSION_SECRET',''))>=32,
            'missing':missing,'network_called':False,'live_verified':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if not missing else 2


if __name__=='__main__':raise SystemExit(main())
