@echo off
if not defined AK_PORT set AK_PORT=8010
python "%~dp0manage.py" stop
pause
