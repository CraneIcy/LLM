@echo off
rem ============================================================
rem CAgent 启动脚本（终端界面 TUI 版）
rem 图形界面请双击 start_cagent.bat
rem ============================================================
cd /d "D:\LLM\Agent\CAgent"
python main.py --tui
if errorlevel 1 pause
