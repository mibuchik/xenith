@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [XENITH] Создаю виртуальное окружение...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [XENITH] Устанавливаю зависимости...
pip install -q -r requirements.txt

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [XENITH] Создан .env из шаблона. Заполни API-ключи при необходимости.
    )
)

python src\main.py --vault ".\vault" --agents 2 %*
