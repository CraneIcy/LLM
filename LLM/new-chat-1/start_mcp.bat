@echo off
rem Start AnythingLLM MCP server (loads .env, opens a new console window)
cd /d "%~dp0"
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (.env) do set "%%a=%%b"
)
if not defined ANYTHINGLLM_API_KEY (
    echo [ERROR] ANYTHINGLLM_API_KEY not found. Add it to .env first.
    exit /b 1
)
start "AnythingLLM-MCP" python server.py
echo MCP server starting on http://127.0.0.1:8765/mcp
echo To stop: run stop_mcp.bat or close the "AnythingLLM-MCP" window.
