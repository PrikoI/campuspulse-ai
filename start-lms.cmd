@echo off
setlocal
cd /d "%~dp0"
if not defined CAMPUSPULSE_LMS_REPOSITORY set CAMPUSPULSE_LMS_REPOSITORY=pending
set CAMPUSPULSE_ALLOW_CLOUD=0
set CAMPUSPULSE_MODE=local
set CAMPUSPULSE_TRANSPORT=mcp
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Project .venv is missing. Follow README.md setup instructions.
  exit /b 1
)
echo CampusPulse LMS backend. Temporary local auth. Repository: %CAMPUSPULSE_LMS_REPOSITORY%.
echo No frontend is served. Stop the server with Ctrl+C.
".venv\Scripts\python.exe" -X utf8 -m campuspulse.lms_server %*
exit /b %errorlevel%
