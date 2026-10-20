# GCP deployment and live verification

The application uses a custom Agent Engine class in `campuspulse/cloud_agent.py`. It runs the same authenticated LMS Gemini/MCP loop as the local server. The old `campuspulse.agent.CampusPulseAgent` is not deployed.

Reference: [Agent Engine Python SDK](https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai.agent_engines.AgentEngine), [Google Gen AI SDK](https://googleapis.github.io/python-genai/). Current SDK `agent_engines.create` supports a runtime service account and Secret Manager environment variables. Its resource is still `projects/.../locations/.../reasoningEngines/...`.

## 1. Required values

Use your team-funded GCP project with billing and the relevant APIs already enabled. Choose an available Gemini model ID. Do not copy obsolete Gemini 1.5 names from the case as a guarantee of availability.

Fill the placeholders below with actual values:

```powershell
$project = 'YOUR_GCP_PROJECT'
$firebaseProject = 'YOUR_FIREBASE_PROJECT'
$region = 'us-central1'
$model = 'YOUR_AVAILABLE_GEMINI_MODEL'
$bucket = 'gs://YOUR_EXISTING_BUCKET'
$runtimeAccount = 'YOUR_RUNTIME_ACCOUNT@YOUR_PROJECT.iam.gserviceaccount.com'
$secretId = 'campuspulse-session-secret'
```

Runtime needs Vertex AI User, Firestore access (`roles/datastore.user`) on the Firebase project, and Secret Manager Secret Accessor on the named secret. Deployment identity needs permission to deploy Agent Engine, access the staging bucket and act as the runtime service account. Cloud Run backend also needs permission to query the Agent Engine. Grant narrowly scoped roles through your project's existing IAM process.

Authenticate locally using ADC (`gcloud auth application-default login`) or the explicitly configured service account key. The key is never uploaded with source. The application accepts a local Firebase service account JSON for Vertex only if that account actually has Vertex IAM permissions.

## 2. Shared session secret

The frontend backend and remote agent must share the same random secret (32+ characters). The local setup creates one in the ignored `.env`; do not publish it.

To transfer that existing value without printing it, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.export_session_secret
gcloud secrets create $secretId --project $project --replication-policy automatic
gcloud secrets versions add $secretId --project $project --data-file .local/session-secret.txt
```

If the secret already exists, skip `secrets create`. Grant the runtime identity access to this secret. Both cloud services reference `latest`; rotate both together. The private exported file stays ignored by Git.

## 3. Agent Engine

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-cloud.txt
.\.venv\Scripts\python.exe -m scripts.deploy_agent --project $project --firebase-project $firebaseProject --location $region --bucket $bucket --service-account $runtimeAccount --session-secret $secretId --model $model
```

Inspect the dry-run. To actually deploy, repeat the same command with `--execute`. This creates a managed cloud resource; it does not activate billing, create a bucket or expand IAM automatically.

On success, read the returned resource name from the ignored `deployment.json`:

```powershell
$agentResource = (Get-Content deployment.json -Raw | ConvertFrom-Json).resource_name
$env:CAMPUSPULSE_AGENT_ENGINE_RESOURCE = $agentResource
.\start-lms.cmd
```

The server signs application sessions; the remote class verifies them and derives the student ID server-side. An IAM caller cannot inject a different student ID into model arguments. Session revocation is stored in Firestore and rechecked by both runtimes. For this MVP, application login remains temporary development login, so the hosted demo stays private.

## 4. Cloud Run UI/API

The Docker build has an explicit source allowlist. JSON credentials, `.env`, `.local`, Git and output files are excluded from upload/build. No service key is needed in the cloud container: use its attached service account.

```powershell
gcloud run deploy campuspulse-ui --project $project --region $region --source . --service-account $runtimeAccount --no-allow-unauthenticated --min-instances 0 --max-instances 1 --concurrency 2 --timeout 300 --set-env-vars "CAMPUSPULSE_LMS_REPOSITORY=firestore,CAMPUSPULSE_FIREBASE_PROJECT=$firebaseProject,CAMPUSPULSE_FIREBASE_CREDENTIALS=adc,CAMPUSPULSE_AGENT_ENGINE_RESOURCE=$agentResource,CAMPUSPULSE_DEMO_STUDENTS=student1" --set-secrets "CAMPUSPULSE_LMS_SESSION_SECRET=${secretId}:latest"
$origin = gcloud run services describe campuspulse-ui --project $project --region $region --format 'value(status.url)'
gcloud run services update campuspulse-ui --project $project --region $region --update-env-vars "CAMPUSPULSE_PUBLIC_ORIGIN=$origin"
gcloud run services proxy campuspulse-ui --project $project --region $region --port 8080
```

Open http://127.0.0.1:8080/ while the authenticated proxy is running. The service is private, not publicly opened with shared demo passwords. For public rollout, replace temporary login with Firebase Authentication/OIDC and complete authorization review first.

## 5. Verify; do not confuse dry-run with deployment

1. `python -m scripts.cloud_readiness` checks configuration strings only.
2. Local Vertex: fill project/model and `CAMPUSPULSE_ALLOW_CLOUD=1`, restart, run `python -m scripts.smoke_lms --url http://127.0.0.1:8766 --gemini`.
3. Remote Agent Engine: set `CAMPUSPULSE_AGENT_ENGINE_RESOURCE`, restart the backend and repeat the Gemini smoke. Expect `deployment=agent-engine` and a trace with model and MCP tool events.
4. Inspect the Agent Engine resource in GCP and Cloud Logging. Show its resource name and a successful authenticated response during the demo.
5. Submit the repository and `output/pdf/CampusPulse_GDG_Astana.pdf`.

The remote query API returns a complete result; its action trace is replayed to the web client after completion, not advertised as live remote token streaming. Local MCP events stream during execution. No model call or cloud deployment is claimed until its live smoke-test succeeds.
