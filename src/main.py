"""
main.py — Точка входа XENITH.

Использование:
  python src/main.py --vault ./vault --agents 2
  python src/main.py --vault ./vault --agents 2 --model openai/gpt-4o
  python src/main.py --vault ./vault --agents 3 \
      --model ollama/qwen2.5-coder:14b \
      --model anthropic/claude-sonnet-4-6 \
      --model gemini/gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def load_env() -> None:
    """Загружает .env из корня проекта (папка выше src/)."""
    root = Path(__file__).parent.parent
    env_file = root / ".env"
    if not env_file.exists():
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="XENITH — Оркестратор AI-агентов с памятью в Obsidian Vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python src/main.py --vault ./vault --agents 2
  python src/main.py --vault ./vault --agents 2 --model openai/gpt-4o
  python src/main.py --vault ./vault --agents 3 --model ollama/qwen2.5-coder:14b --model gemini/gemini-2.5-flash
        """,
    )
    p.add_argument("--vault",   default="./vault",  help="Путь к Obsidian Vault")
    p.add_argument("--agents",  type=int, default=2, help="Количество агентов")
    p.add_argument(
        "--model",
        action="append",
        dest="models",
        default=[],
        metavar="PROVIDER/MODEL",
        help="Модель для агента (можно указывать несколько раз)",
    )
    p.add_argument("--no-ui", action="store_true", help="Запустить без Rich UI")
    return p.parse_args()


def _init_vault(vault: Path) -> None:
    """Создаёт шаблонные файлы vault при первом запуске."""
    (vault / "_context").mkdir(parents=True, exist_ok=True)
    (vault / "tasks").mkdir(exist_ok=True)

    readme = vault / "README.md"
    if not readme.exists():
        readme.write_text(
            "# XENITH Vault\n\n"
            "Obsidian Vault — общая долгосрочная память агентов XENITH.\n\n"
            "## Структура\n"
            "- `_context/` — pinned-файлы, всегда в контексте агентов\n"
            "- `tasks/` — результаты выполненных задач\n",
            encoding="utf-8",
        )

    system_ctx = vault / "_context" / "system.md"
    if not system_ctx.exists():
        system_ctx.write_text(
            "# Системный контекст XENITH #pinned\n\n"
            "Ты — агент системы XENITH. Используй этот vault как долгосрочную память.\n"
            "Результаты работы сохраняй в папку `tasks/`.\n"
            "При выполнении задачи сначала поищи в vault релевантные файлы.\n",
            encoding="utf-8",
        )


def main() -> None:
    load_env()
    args = parse_args()

    # Добавляем src/ в sys.path для импортов
    src_dir = Path(__file__).parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    vault_path = Path(args.vault)
    vault_path.mkdir(parents=True, exist_ok=True)
    _init_vault(vault_path)

    default_model = args.models[0] if args.models else "ollama/qwen2.5-coder:14b"
    extra_models  = args.models[1:] if len(args.models) > 1 else []

    from core import AgentManager
    from term_ui import XenithUI

    manager = AgentManager(
        vault_path=str(vault_path),
        agent_count=args.agents,
        default_model=default_model,
        extra_models=extra_models,
    )
    manager.start()

    if args.no_ui:
        manager.on_log(lambda msg: print(f"[LOG] {msg}", flush=True))
        manager.on_result(lambda r: print(f"\n[RESULT:{r.task_id}]\n{r.result}\n", flush=True))
        print("XENITH (без UI). Введи задачу или 'exit':")
        try:
            while True:
                line = input("> ").strip()
                if line.lower() in ("exit", "quit"):
                    break
                if line:
                    manager.submit_task(line)
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            manager.stop()
    else:
        ui = XenithUI(manager)
        try:
            ui.run()
        except KeyboardInterrupt:
            manager.stop()


if __name__ == "__main__":
    main()
