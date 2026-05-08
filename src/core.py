"""
core.py — Ядро XENITH: управление жизненным циклом агентов.

AgentManager:
  • Создаёт и запускает агентов по заданным параметрам
  • Следит за состоянием агентов
  • Координирует остановку всей системы
"""

from __future__ import annotations

import threading
from pathlib import Path

from agent import Agent
from memory import VaultMemory
from orchestrator import Orchestrator, TaskResult


class AgentManager:
    """
    Центральный менеджер системы XENITH.

    Создаёт VaultMemory, агентов и оркестратор,
    запускает фоновые потоки и обрабатывает сигналы завершения.
    """

    def __init__(
        self,
        vault_path: str,
        agent_count: int,
        default_model: str,
        extra_models: list[str] | None = None,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.agent_count = agent_count
        self.default_model = default_model
        self._shutdown_event = threading.Event()
        self._result_callbacks: list = []
        self._log_callbacks: list = []

        self.memory = VaultMemory(vault_path)
        self.memory.on_change(self._on_vault_change)

        models = self._build_model_list(agent_count, default_model, extra_models or [])
        self.agents: list[Agent] = [
            Agent(
                agent_id=f"agent-{i + 1}",
                model=models[i],
                memory=self.memory,
            )
            for i in range(agent_count)
        ]

        self.orchestrator = Orchestrator(
            agents=self.agents,
            on_result=self._handle_result,
            on_log=self._handle_log,
        )

    # ── Запуск и остановка ────────────────────────────────────────────────────

    def start(self) -> None:
        self.orchestrator.start()
        self._log("XENITH запущен")
        self._log(f"Vault: {self.vault_path}")
        self._log(f"Агентов: {self.agent_count}")
        for ag in self.agents:
            self._log(f"  {ag.id} -> {ag.model}")

    def stop(self) -> None:
        self._log("Завершение работы XENITH...")
        self.orchestrator.stop()
        self.memory.stop()
        self._shutdown_event.set()

    def wait_for_shutdown(self) -> None:
        self._shutdown_event.wait()

    # ── Отправка задач ────────────────────────────────────────────────────────

    def submit_task(self, prompt: str) -> str:
        return self.orchestrator.submit(prompt)

    # ── Колбэки ───────────────────────────────────────────────────────────────

    def on_result(self, fn) -> None:
        self._result_callbacks.append(fn)

    def on_log(self, fn) -> None:
        self._log_callbacks.append(fn)

    def _handle_result(self, result: TaskResult) -> None:
        for fn in self._result_callbacks:
            fn(result)

    def _handle_log(self, msg: str) -> None:
        for fn in self._log_callbacks:
            fn(msg)

    def _log(self, msg: str) -> None:
        self._handle_log(msg)

    def _on_vault_change(self, path) -> None:
        self._log(f"Vault изменился: {path.name}")

    # ── Статус ────────────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        return {
            "agents": [a.stats for a in self.agents],
            "queue_size": self.orchestrator.queue_size,
            "vault_files": len(self.memory.list_files()),
        }

    # ── Вспомогательные ───────────────────────────────────────────────────────

    @staticmethod
    def _build_model_list(count: int, default: str, extras: list[str]) -> list[str]:
        """extras перезаписывают default для первых len(extras) агентов."""
        models = [default] * count
        for i, m in enumerate(extras[:count]):
            models[i] = m
        return models
