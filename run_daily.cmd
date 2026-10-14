@echo off
rem Execucao manual. A tarefa agendada "daytrade-orb-spy" usa run_daily.pyw (pythonw, sem janela).
cd /d %~dp0
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe live_orb.py SPY >> journal\scheduler.log 2>&1
