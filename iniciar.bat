@echo off
chcp 65001 >nul
set PYTHONUTF8=1
powershell -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1"
