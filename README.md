# CampusPulse AI

CampusPulse is a student LMS web app with a teacher interface, Firestore-backed
academic data, a student assistant, and an auditable API/MCP tool layer.

> **Project presentation:** [CampusPulse AI — GDG Astana](presentation/CampusPulse_AI_GDG_Astana.pptx)

## What it does

- Student and teacher workspaces for courses, assignments, materials, grades,
  attendance, schedules, study plans, and personal tasks.
- Firestore repository with session-based identity and role/course-scoped access.
- Student assistant that can read LMS data and prepare study plans. With an
  enabled LLM provider it can interpret requests and select approved LMS tools;
  without an LLM, only the built-in keyword-based routes and calculations run.
- Google Gemini Developer API (Interactions), Alem, or Vertex AI provider,
  selected on the server. API credentials are not sent to the browser.
- Local HTTP API, MCP stdio integration, and an SSE activity trace.

The app needs a configured Firestore project with compatible LMS data for
real student/teacher workflows. Without a connected database, the interface
can start in `pending` mode, but academic reads and LLM requests are unavailable.
This repository does not include sample student records or cloud credentials.

## Run locally (Windows)

Requires Python 3.11 or newer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure the private `.env` with the Firestore project and credentials. For
local service-account authentication, set `CAMPUSPULSE_FIREBASE_CREDENTIALS` to
the path of your own Firebase service-account JSON. That credential file must
stay outside Git. Alternatively, use Google Application Default Credentials;
see [Firestore setup](docs/FIRESTORE.md).

Start the app:

```powershell
.\start-lms.cmd
```

Open <http://127.0.0.1:8766/>. The local demo signs in as `student1`; the
temporary demo accounts are not production authentication. To run without
opening Firestore, set `CAMPUSPULSE_LMS_REPOSITORY=pending` before launch.
The local assistant mode does not call an LLM. For Gemini API setup and
provider configuration, see [Gemini API](docs/GEMINI_API.md); for other
providers, see [Alem](docs/ALEM.md) and [Vertex AI](docs/VERTEX_AI.md).

## Verify

```powershell
.\start-lms.cmd --check
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_lms
```

The LMS check suite uses local test data and mocked cloud SDK calls; it does
not make paid model requests or read/write real Firestore records. Additional
project documentation is in [`docs/`](docs/), including the
[API reference](docs/LMS_API.md), [frontend guide](docs/FRONTEND.md), and
[database contract](docs/LMS_DATABASE_CONTRACT.md).

## Credentials and repository contents

Never commit `.env`, API keys, service-account credentials, Firebase private
keys, or populated database backups. `.gitignore` excludes local secrets and
generated archives. `firebase-key.json` is deliberately excluded because it
can grant privileged access to the Firebase project; use your own credential
outside the repository instead.
