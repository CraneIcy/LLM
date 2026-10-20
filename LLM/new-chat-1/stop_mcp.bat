@echo off
rem Stop AnythingLLM MCP server (kills whatever listens on the MCP port)
cd /d "%~dp0"
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (.env) do set "%%a=%%b"
)
if not defined MCP_PORT set MCP_PORT=8765
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %MCP_PORT% -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Write-Host 'MCP server on port %MCP_PORT% stopped.'"
