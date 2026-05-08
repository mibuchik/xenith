@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [XENITH] Creating virtual environment...
    python -m venv .venv
)

echo [XENITH] Installing dependencies...
.venv\Scripts\pip install -q -r requirements.txt

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [XENITH] Created .env from template.
    )
)

echo [XENITH] Starting...
.venv\Scripts\python src\main.py --vault ".\vault" --agents 2 %*
