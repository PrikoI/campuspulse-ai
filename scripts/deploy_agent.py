"""Agent Engine deployment: dry-run by default, explicit execute for cloud mutation."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    parser.add_argument('--firebase-project',required=True)
    parser.add_argument('--location',default='us-central1')
    parser.add_argument('--model-location',default='global')
    parser.add_argument('--model',required=True,help='Available Vertex Gemini model ID, no guessed fallback')
    parser.add_argument('--bucket',required=True,help='Existing gs:// staging bucket')
    parser.add_argument('--service-account',required=True)
    parser.add_argument('--session-secret',required=True,help='Existing Secret Manager secret ID, NOT its value')
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    if not args.bucket.startswith('gs://') or '@' not in args.service_account or '/' in args.session_secret:
        parser.error('Check bucket, service account email and secret ID')
    print(json.dumps({**vars(args),'agent':'campuspulse.cloud_agent.CampusPulseCloudAgent',
                     'method':'vertexai.agent_engines.create','credentials_in_package':False},indent=2))
    if not args.execute:
        print('DRY RUN: no API requests or resources created. Add --execute after reviewing.')
        return
    import vertexai
    from vertexai import agent_engines
    from google.cloud.aiplatform_v1.types import env_var
    from campuspulse.cloud_agent import CampusPulseCloudAgent
    from campuspulse.config import google_credentials
    vertexai.init(project=args.project,location=args.location,staging_bucket=args.bucket,credentials=google_credentials())
    env = {'CAMPUSPULSE_LMS_REPOSITORY':'firestore','CAMPUSPULSE_FIREBASE_PROJECT':args.firebase_project,
           'CAMPUSPULSE_FIREBASE_CREDENTIALS':'adc','CAMPUSPULSE_ALLOW_CLOUD':'1',
           'GOOGLE_CLOUD_PROJECT':args.project,'GOOGLE_CLOUD_LOCATION':args.model_location,
           'CAMPUSPULSE_VERTEX_MODEL':args.model,
           'CAMPUSPULSE_LMS_SESSION_SECRET':env_var.SecretRef(secret=args.session_secret,version='latest')}
    requirements = [line for line in (ROOT/'requirements.txt').read_text().splitlines() if line and not line.startswith('#')]
    requirements += ['google-cloud-aiplatform[agent_engines]>=1.112,<2','cloudpickle>=3,<4']
    remote = agent_engines.create(CampusPulseCloudAgent(),display_name='CampusPulse AI - LMS',
        requirements=requirements,extra_packages=[str(ROOT/'campuspulse')],
        service_account=args.service_account,env_vars=env,min_instances=0,max_instances=1)
    result = {'resource_name':remote.resource_name,'project':args.project,'location':args.location}
    (ROOT/'deployment.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
