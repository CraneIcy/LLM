@echo off
rem ============================================================
rem CAgent 启动脚本（默认启动图形界面 GUI）
rem 如需使用终端界面，请双击 start_cagent_tui.bat
rem ============================================================
cd /d "D:\LLM\Agent\CAgent"
python main.py
if errorlevel 1 pause
