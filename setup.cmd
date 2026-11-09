@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt -c requirements-lock.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\setup_asr_models.py --model gigaam-ctc
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\setup_protocol_runtime.py
if errorlevel 1 goto fail
echo Setup completed. Open launch-protocol.cmd to start the application.
pause
exit /b 0
:fail
echo Setup failed. Check the output above. Python 3.12 x64 and internet are needed for initial setup.
pause
exit /b 1
