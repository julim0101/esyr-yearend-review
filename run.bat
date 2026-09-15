@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ESYR . Etners Smart Year-end Review
python run.py
pause
