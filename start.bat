@echo off
cd /d "%~dp0"
start "QuickTransform" ".tools\python312\python.exe" -m w2md serve --host 127.0.0.1 --port 8000
