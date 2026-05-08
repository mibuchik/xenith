<div align="center">

```
██╗  ██╗███████╗███╗   ██╗██╗████████╗██╗  ██╗
╚██╗██╔╝██╔════╝████╗  ██║██║╚══██╔══╝██║  ██║
 ╚███╔╝ █████╗  ██╔██╗ ██║██║   ██║   ███████║
 ██╔██╗ ██╔══╝  ██║╚██╗██║██║   ██║   ██╔══██║
██╔╝ ██╗███████╗██║ ╚████║██║   ██║   ██║  ██║
╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═╝   ╚═╝   ╚═╝  ╚═╝
```

**Терминальный оркестратор AI-агентов с общей памятью в Obsidian Vault**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Rich](https://img.shields.io/badge/UI-Rich-ff69b4?style=flat-square)](https://github.com/Textualize/rich)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Providers](https://img.shields.io/badge/AI_Providers-9-blueviolet?style=flat-square)](#поддерживаемые-провайдеры)

</div>

---

## Что это

XENITH превращает папку Obsidian Vault в **единый мозг** для нескольких AI-агентов. Агенты видят `.md` файлы как свою долгосрочную память, пишут результаты обратно в vault и работают параллельно — всё в одном терминале.

```
 ◆ XENITH   agent-1 ● idle  ·  agent-2 ⟳ working [a3f2b1]
╭─────────────────────────────────────────────────────────────╮
│                                                             │
│  you  09:41                                                 │
│  ┃ напиши функцию быстрой сортировки на python              │
│                                                             │
│  agent-1  ·  qwen2.5-coder:14b  09:42                       │
│  ┃ def quicksort(arr):                                      │
│  ┃     if len(arr) <= 1:                                    │
│  ┃         return arr                                       │
│  ┃     pivot = arr[len(arr) // 2]                           │
│  ┃     left = [x for x in arr if x < pivot]                │
│  ┃     ...                                                  │
│                                                             │
╰─────────────────────────────────────────────────────────────╯
──────────────────────────────────────────────────────────────
  ❯ █
```

## Возможности

- **Общая память** — все агенты читают и пишут в один Obsidian Vault
- **Реальное время** — watchdog отслеживает изменения `.md` файлов мгновенно
- **Параллельность** — сложные задачи автоматически делятся на подзадачи между агентами
- **9 провайдеров** — Ollama, OpenAI, Claude, Gemini, DeepSeek, OpenRouter, Mistral, Groq, xAI
- **Смешанный режим** — один агент на Ollama локально, другой через Claude API одновременно
- **Гибридный режим** — task-based + автономный мониторинг vault

## Быстрый старт

```bat
git clone https://github.com/mibuchik/xenith
cd xenith
run.bat
```

`run.bat` сам создаёт виртуальное окружение, ставит зависимости и запускает с 2 агентами на Ollama.

## Установка вручную

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
:: заполни нужные API-ключи в .env

python src\main.py --vault ".\vault" --agents 2
```

## Использование

```bat
:: 2 агента, Ollama по умолчанию
python src\main.py --vault ".\vault" --agents 2

:: конкретная модель
python src\main.py --vault ".\vault" --agents 2 --model ollama/qwen2.5-coder:14b

:: разные модели для каждого агента
python src\main.py --vault ".\vault" --agents 2 ^
    --model ollama/qwen2.5-coder:14b ^
    --model anthropic/claude-sonnet-4-6

:: без Rich UI (чистый stdout)
python src\main.py --vault ".\vault" --agents 2 --no-ui
```

### Команды в терминале

| Команда | Действие |
|---|---|
| любой текст + Enter | задача для агентов |
| `exit` | завершить XENITH |
| `status` | статус агентов и очереди |
| `vault tasks/abc.md` | показать файл из vault |
| `Ctrl+L` | очистить чат |
| `Ctrl+C` | выход |

## Поддерживаемые провайдеры

| Провайдер | Формат модели | Ключ | Примечание |
|---|---|---|---|
| **Ollama** | `ollama/qwen2.5-coder:14b` | не нужен | локально, офлайн |
| **OpenAI** | `openai/gpt-4o` | `OPENAI_API_KEY` | |
| **Anthropic** | `anthropic/claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | |
| **Gemini** | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` | есть бесплатный тир |
| **DeepSeek** | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | дёшево, работает из РФ |
| **OpenRouter** | `openrouter/meta-llama/llama-3.3-70b-instruct` | `OPENROUTER_API_KEY` | 200+ моделей |
| **Mistral** | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` | |
| **Groq** | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` | быстрый инференс |
| **xAI** | `xai/grok-3` | `XAI_API_KEY` | |

## Архитектура памяти

```
vault/
├── _context/          ← pinned-файлы, ВСЕГДА в контексте агентов
│   └── system.md      ← системные инструкции
├── tasks/             ← результаты задач (создаются автоматически)
│   └── a3f2b1.md
└── ваши-заметки.md    ← ищутся по ключевым словам запроса
```

**Pinned-файлы** — папка `_context/` или тег `#pinned` в любом `.md` файле.  
**Поиск** — топ-5 релевантных файлов автоматически добавляются в контекст задачи.  
**Запись** — каждый результат сохраняется в `vault/tasks/<id>.md`.

## Структура проекта

```
xenith/
├── src/
│   ├── main.py          # точка входа, CLI
│   ├── core.py          # AgentManager — жизненный цикл
│   ├── agent.py         # Agent — адаптеры провайдеров
│   ├── memory.py        # VaultMemory — кэш + watchdog
│   ├── orchestrator.py  # очередь, параллельность
│   └── term_ui.py       # fullscreen chat TUI (msvcrt input)
├── vault/               # Obsidian Vault (память агентов)
├── .env.example         # шаблон ключей
├── requirements.txt
└── run.bat
```

## Лицензия

MIT
