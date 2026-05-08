"""
agent.py — Класс агента XENITH.

Формат модели: "провайдер/название"
  ollama/qwen2.5-coder:14b
  openai/gpt-4o
  anthropic/claude-sonnet-4-6
  gemini/gemini-2.5-flash
  deepseek/deepseek-chat
  openrouter/meta-llama/llama-3.3-70b-instruct
  mistral/mistral-large-latest
  groq/llama-3.3-70b-versatile
  xai/grok-3
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory import VaultMemory


class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentTask:
    """Задача, которую выполняет агент."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    prompt: str = ""
    parent_id: str | None = None
    result: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class Agent:
    """
    Агент XENITH.

    Каждый агент имеет свою модель и может работать независимо.
    Общается с провайдером через соответствующий адаптер.
    Результаты сохраняет в Vault.
    """

    def __init__(
        self,
        agent_id: str,
        model: str,
        memory: "VaultMemory",
        system_prompt: str = "",
    ) -> None:
        self.id = agent_id
        self.model = model
        self.memory = memory
        self.system_prompt = system_prompt or _default_system_prompt(agent_id)
        self.status = AgentStatus.IDLE
        self.current_task: AgentTask | None = None
        self.completed: list[AgentTask] = []
        self._lock = threading.Lock()
        self._provider, self._model_name = _parse_model(model)

    # ── Выполнение задачи ─────────────────────────────────────────────────────

    def run_task(self, task: AgentTask) -> str:
        """Выполняет задачу синхронно. Вызывается из потока оркестратора."""
        with self._lock:
            self.status = AgentStatus.WORKING
            self.current_task = task

        try:
            context = self.memory.build_context(task.prompt)
            full_prompt = f"{context}\n\n---\n\n{task.prompt}" if context else task.prompt
            response = self._call_provider(full_prompt)
            task.result = response
            task.finished_at = time.time()
            self._save_result(task)
        except Exception as exc:
            task.error = str(exc)
            task.finished_at = time.time()
            response = f"[ОШИБКА] {exc}"
        finally:
            with self._lock:
                self.completed.append(task)
                self.current_task = None
                self.status = AgentStatus.IDLE

        return response

    # ── Сохранение результата ─────────────────────────────────────────────────

    def _save_result(self, task: AgentTask) -> None:
        """Записывает результат в vault/tasks/<task_id>.md"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(task.finished_at))
        content = (
            f"# Задача {task.id}\n"
            f"**Агент:** {self.id} ({self.model})\n"
            f"**Завершено:** {ts}\n\n"
            f"## Запрос\n{task.prompt}\n\n"
            f"## Результат\n{task.result}\n"
        )
        self.memory.write(f"tasks/{task.id}.md", content)

    # ── Провайдеры ────────────────────────────────────────────────────────────

    def _call_provider(self, prompt: str) -> str:
        dispatch = {
            "ollama":     self._call_ollama,
            "openai":     self._call_openai,
            "anthropic":  self._call_anthropic,
            "gemini":     self._call_gemini,
            "deepseek":   self._call_deepseek,
            "openrouter": self._call_openrouter,
            "mistral":    self._call_mistral,
            "groq":       self._call_groq,
            "xai":        self._call_xai,
        }
        fn = dispatch.get(self._provider)
        if fn is None:
            raise ValueError(f"Неизвестный провайдер: {self._provider}")
        return fn(prompt)

    def _call_ollama(self, prompt: str) -> str:
        import requests
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        resp = requests.post(
            f"{base}/api/generate",
            json={"model": self._model_name, "prompt": self._build_full(prompt), "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    def _call_openai(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
        )
        return resp.choices[0].message.content or ""

    def _call_anthropic(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=self._model_name,
            max_tokens=4096,
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    def _call_gemini(self, prompt: str) -> str:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=self.system_prompt,
        )
        resp = model.generate_content(prompt)
        return resp.text

    def _call_deepseek(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
        resp = client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
        )
        return resp.choices[0].message.content or ""

    def _call_openrouter(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
        resp = client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
        )
        return resp.choices[0].message.content or ""

    def _call_mistral(self, prompt: str) -> str:
        from mistralai import Mistral
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        resp = client.chat.complete(
            model=self._model_name,
            messages=self._messages(prompt),
        )
        return resp.choices[0].message.content or ""

    def _call_groq(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )
        resp = client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
        )
        return resp.choices[0].message.content or ""

    def _call_xai(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )
        resp = client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
        )
        return resp.choices[0].message.content or ""

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _messages(self, prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

    def _build_full(self, prompt: str) -> str:
        """Для Ollama: объединяем system и user в один prompt."""
        return f"[SYSTEM]\n{self.system_prompt}\n\n[USER]\n{prompt}"

    @property
    def stats(self) -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "status": self.status.value,
            "completed": len(self.completed),
            "current_task": self.current_task.id if self.current_task else None,
        }


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _parse_model(model: str) -> tuple[str, str]:
    """
    Разбирает "провайдер/модель" на части.
    openrouter/meta-llama/llama-3.3 → ("openrouter", "meta-llama/llama-3.3")
    """
    parts = model.split("/", 1)
    if len(parts) != 2:
        raise ValueError(
            f'Неверный формат модели: "{model}". '
            'Используй "провайдер/модель", например "ollama/qwen2.5-coder:14b".'
        )
    return parts[0].lower(), parts[1]


def _default_system_prompt(agent_id: str) -> str:
    return (
        f"Ты — агент {agent_id} системы XENITH. "
        "Ты имеешь доступ к базе знаний в формате Obsidian Vault. "
        "Используй предоставленный контекст из .md файлов для точных ответов. "
        "Если нужно — записывай результаты в формате Markdown."
    )
