"""
orchestrator.py — Оркестратор задач XENITH.

Отвечает за:
  • Приём задач в очередь
  • Разбивку задачи на подзадачи (если агентов > 1 и задача сложная)
  • Назначение задач свободным агентам
  • Гарантию отсутствия конфликтов при записи в vault
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from agent import Agent, AgentTask


@dataclass
class TaskResult:
    """Финальный результат выполнения задачи (возможно, собранный из подзадач)."""
    task_id: str
    prompt: str
    result: str
    subtask_results: list[str] = field(default_factory=list)
    agent_id: str = ""
    elapsed: float = 0.0


class Orchestrator:
    """
    Оркестратор распределяет задачи между агентами и собирает результаты.

    Алгоритм:
      1. Задача поступает в _task_queue.
      2. _dispatcher_loop берёт задачу и ищет свободного агента.
      3. Если агентов >= 2 и prompt длинный → разбивает на подзадачи.
      4. Каждая подзадача выполняется в отдельном потоке.
      5. Результаты собираются и возвращаются через on_result callback.
    """

    SPLIT_THRESHOLD = 300

    def __init__(
        self,
        agents: list[Agent],
        on_result: Callable[[TaskResult], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.agents = agents
        self._on_result = on_result or (lambda r: None)
        self._on_log = on_log or (lambda msg: None)
        self._task_queue: queue.Queue[AgentTask] = queue.Queue()
        self._write_lock = threading.Lock()
        self._running = False
        self._dispatcher_thread: threading.Thread | None = None

    # ── Управление ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop, daemon=True, name="xenith-dispatcher"
        )
        self._dispatcher_thread.start()

    def stop(self) -> None:
        self._running = False

    # ── Добавление задач ──────────────────────────────────────────────────────

    def submit(self, prompt: str) -> str:
        """Добавляет задачу в очередь. Возвращает id задачи."""
        task = AgentTask(prompt=prompt)
        self._task_queue.put(task)
        self._log(f"Задача {task.id} добавлена в очередь")
        return task.id

    # ── Основной цикл ─────────────────────────────────────────────────────────

    def _dispatcher_loop(self) -> None:
        while self._running:
            try:
                task = self._task_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            free = self._free_agents()
            if not free:
                self._task_queue.put(task)
                time.sleep(0.5)
                continue

            can_split = len(free) >= 2 and len(task.prompt) > self.SPLIT_THRESHOLD
            if can_split:
                self._run_parallel(task, free)
            else:
                self._run_single(task, free[0])

    def _run_single(self, task: AgentTask, agent: Agent) -> None:
        """Запускает задачу на одном агенте в отдельном потоке."""
        def worker() -> None:
            start = time.time()
            self._log(f"Агент {agent.id} → задача {task.id}")
            result_text = agent.run_task(task)
            result = TaskResult(
                task_id=task.id,
                prompt=task.prompt,
                result=result_text,
                agent_id=agent.id,
                elapsed=time.time() - start,
            )
            self._on_result(result)

        threading.Thread(target=worker, daemon=True, name=f"task-{task.id}").start()

    def _run_parallel(self, task: AgentTask, agents: list[Agent]) -> None:
        """Разбивает задачу на подзадачи и запускает их параллельно."""
        parts = self._split_prompt(task.prompt, len(agents))
        self._log(
            f"Задача {task.id} разбита на {len(parts)} подзадач, "
            f"агенты: {[a.id for a in agents[:len(parts)]]}"
        )
        subtasks = [AgentTask(prompt=part, parent_id=task.id) for part in parts]
        results_lock = threading.Lock()
        subtask_results: list[tuple[int, str]] = []

        def worker(idx: int, sub: AgentTask, agent: Agent) -> None:
            text = agent.run_task(sub)
            with results_lock:
                subtask_results.append((idx, text))

        threads = [
            threading.Thread(target=worker, args=(i, sub, ag), daemon=True)
            for i, (sub, ag) in enumerate(zip(subtasks, agents))
        ]
        for t in threads:
            t.start()

        def collect() -> None:
            for t in threads:
                t.join()
            subtask_results.sort(key=lambda x: x[0])
            combined = "\n\n---\n\n".join(text for _, text in subtask_results)
            with self._write_lock:
                task.result = combined
                task.finished_at = time.time()
                agents[0].memory.write(
                    f"tasks/{task.id}_combined.md",
                    f"# Задача {task.id} (параллельное выполнение)\n\n{combined}\n",
                )
            self._on_result(TaskResult(
                task_id=task.id,
                prompt=task.prompt,
                result=combined,
                subtask_results=[t for _, t in subtask_results],
                agent_id=", ".join(a.id for a in agents[:len(parts)]),
            ))

        threading.Thread(target=collect, daemon=True, name=f"collect-{task.id}").start()

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _free_agents(self) -> list[Agent]:
        from agent import AgentStatus
        return [a for a in self.agents if a.status == AgentStatus.IDLE]

    def _split_prompt(self, prompt: str, n: int) -> list[str]:
        """Делит prompt на n частей по абзацам или по ролям."""
        paragraphs = [p.strip() for p in prompt.split("\n\n") if p.strip()]
        if len(paragraphs) >= n:
            chunk = max(1, len(paragraphs) // n)
            return ["\n\n".join(paragraphs[i * chunk:(i + 1) * chunk]) for i in range(n)]
        roles = [
            "Проанализируй задачу и опиши подход к решению",
            "Напиши код или техническую реализацию для задачи",
            "Напиши документацию и примеры для задачи",
            "Найди потенциальные проблемы и улучшения для задачи",
        ]
        return [f"{roles[i % len(roles)]}:\n\n{prompt}" for i in range(n)]

    def _log(self, msg: str) -> None:
        self._on_log(msg)

    @property
    def queue_size(self) -> int:
        return self._task_queue.qsize()
