# CampusPulse AI: demo and submission checklist

## Four-minute demonstration

1. **Problem (30 seconds).** A student needs the week's deadlines and preparation time, not another static calendar.
2. **Real source (30 seconds).** Log in as student1. Show enrolled courses, actual Firestore deadlines and the seven-day timetable. Explain that the preparation effort is editable, not measured automatically.
3. **Autonomous tools (90 seconds).** Select Gemini. Ask: «Составь и сохрани план подготовки на неделю с учётом занятий и дедлайнов». Show model-step events, MCP connection, selected tools, sources and returned plan. Do not call the local rule router Gemini. A shortened action explanation is shown; private chain-of-thought is not exposed.
4. **Confirmed action (30 seconds).** Inspect the proposed personal tasks, confirm and open «Личные задачи». Repeat confirmation in tests to demonstrate idempotency; no duplicates are created.
5. **Teacher flow (30 seconds).** Show timetable editing. Moving a card is a draft; Save rejects overlaps/stale data and adjusts its linked deadline. Student cannot perform this operation.
6. **Cloud evidence (30 seconds).** Show the actual Agent Engine resource and successful authenticated query. Until deployed and tested, say «deployment prepared», not «running in Agent Engine».

## Criteria mapped to evidence

| Criterion | Implementation / evidence |
|---|---|
| MCP / Tools | `lms_mcp_server.py`, schemas in `lms_tools.py`; genuine stdio subprocess, authenticated bootstrap and structured JSON |
| Agent Engine | `cloud_agent.py`, `scripts/deploy_agent.py`; IAM runtime identity and Secret Manager env; live endpoint required |
| AI autonomy | `vertex_gemini.py`: bounded multi-turn Function Calling with native response IDs/signatures retained |
| UX | Weekly timeline, month selection, drafts for drag-and-drop, loading states, tool activity and plan review |
| Architecture | One repository and authorization layer shared across API and MCP; enrollment scope; explicit failures |
| Presentation | `output/pdf/CampusPulse_GDG_Astana.pdf` |

## Data prepared for this project

- Six active subjects; archived subjects remain archived.
- 120 classes across ten weeks, beginning 7 September 2026.
- 60 coursework assignments linked to grade definitions and the last lesson of each subject/week.
- Due date equals assessment lesson end. Ordinary assignment effort defaults to 90 minutes, Midterm/Endterm to 120 minutes; editable teacher estimates.
- Existing profiles and enrollments retained. No fake grades, attendance or lecture notes inserted.
- Migration backup remains private in `.local/academic-backup-*.json`.

The standalone MCP configuration points to the LMS server. The application supplies repository settings and the signing secret through the child environment and authenticates `load_session` itself; never expose that bootstrap tool or a session token as a model-selected action.

## Before submitting

- Run Python and JavaScript tests and the live student smoke.
- Fill cloud slots and verify Gemini + Agent Engine; capture a real resource and successful response.
- Never commit `.env`, `firebase-key.json`, `.local` or exported session secrets.
- Repository URL: use your actual pushed branch. Commits/pushes are not automatically performed by this work.
- Rebuild the PDF after a successful deployment if you want its status slide to reflect that deployment.
