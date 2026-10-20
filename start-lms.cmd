@echo off
setlocal
cd /d "%~dp0"
set CAMPUSPULSE_MODE=local
set CAMPUSPULSE_TRANSPORT=mcp
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Project .venv is missing. Follow README.md setup instructions.
  exit /b 1
)
echo CampusPulse LMS frontend and API. Configuration: .env plus environment overrides.
echo Open http://127.0.0.1:8766/ unless --port overrides it. Stop with Ctrl+C.
".venv\Scripts\python.exe" -X utf8 -m campuspulse.lms_server %*
exit /b %errorlevel%
