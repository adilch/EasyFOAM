@echo off
rem Double-click to start EasyFOAM (uses the project environment in .venv)
start "" "%~dp0.venv\Scripts\easyfoam-gui.exe" %*
