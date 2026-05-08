"""
term_ui.py — Терминальный UI на Rich.

Компоновка экрана:
  ┌─────────────────────────────────────────┐
  │        XENITH · Статус агентов           │
  ├──────────┬──────────────────────────────┤
  │  Агенты  │       Лог событий            │
  ├──────────┴──────────────────────────────┤
  │        Последний результат               │
  ├─────────────────────────────────────────┤
  │  > Ввод команды (в нижней части)        │
  └─────────────────────────────────────────┘
"""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from core import AgentManager
    from orchestrator import TaskResult


BANNER = "[bold cyan]X E N I T H[/]  [dim]AI Agent Orchestrator[/]"

STATUS_COLOR = {
    "idle":    "green",
    "working": "yellow",
    "error":   "red",
    "stopped": "dim",
}

STATUS_ICON = {
    "idle":    "●",
    "working": "⟳",
    "error":   "✗",
    "stopped": "○",
}


class XenithUI:
    """
    Терминальный интерфейс XENITH.

    Rich.Live обновляет панели без мигания.
    Ввод команд работает в отдельном потоке через sys.stdin.
    """

    MAX_LOG = 200
    MAX_RESULT_LINES = 30

    def __init__(self, manager: "AgentManager") -> None:
        self.manager = manager
        self.console = Console()
        self._log: deque[str] = deque(maxlen=self.MAX_LOG)
        self._last_result: str = ""
        self._last_result_id: str = ""
        self._running = False
        self._lock = threading.Lock()

        manager.on_log(self._push_log)
        manager.on_result(self._push_result)

    # ── Запуск ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Запускает UI. Блокирует вызывающий поток до команды exit."""
        self._running = True

        input_thread = threading.Thread(
            target=self._input_loop, daemon=True, name="xenith-input"
        )
        input_thread.start()

        with Live(
            self._build_layout(),
            console=self.console,
            refresh_per_second=2,
            screen=True,
        ) as live:
            while self._running:
                live.update(self._build_layout())
                time.sleep(0.5)

    # ── Построение интерфейса ─────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="result", size=12),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="agents", ratio=1),
            Layout(name="log",    ratio=2),
        )
        layout["header"].update(self._render_header())
        layout["agents"].update(self._render_agents())
        layout["log"].update(self._render_log())
        layout["result"].update(self._render_result())
        layout["footer"].update(self._render_footer())
        return layout

    def _render_header(self) -> Panel:
        s = self.manager.status
        info = (
            f"[dim]Очередь:[/] [yellow]{s['queue_size']}[/]  "
            f"[dim]Файлов в vault:[/] [cyan]{s['vault_files']}[/]  "
            f"[dim]{time.strftime('%H:%M:%S')}[/]"
        )
        return Panel(
            Text.from_markup(f"{BANNER}   {info}"),
            box=box.DOUBLE_EDGE,
            style="bold",
        )

    def _render_agents(self) -> Panel:
        table = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="bold dim")
        table.add_column("Агент",   style="bold", no_wrap=True)
        table.add_column("Модель",  style="dim",  no_wrap=True)
        table.add_column("Статус",  no_wrap=True)
        table.add_column("Done",    justify="right", style="dim")

        for ag in self.manager.agents:
            s = ag.stats
            color = STATUS_COLOR.get(s["status"], "white")
            icon  = STATUS_ICON.get(s["status"], "?")
            model_short = s["model"].split("/")[-1][:16]
            task_hint = f" [dim]{s['current_task']}[/]" if s["current_task"] else ""
            status_cell = Text.from_markup(f"[{color}]{icon} {s['status']}[/]{task_hint}")
            table.add_row(s["id"], model_short, status_cell, str(s["completed"]))

        return Panel(table, title="[bold]Агенты[/]", border_style="blue")

    def _render_log(self) -> Panel:
        with self._lock:
            lines = list(self._log)[-22:]
        text = Text()
        for line in lines:
            text.append(f"{line}\n", style="dim")
        return Panel(text, title="[bold]Лог[/]", border_style="green")

    def _render_result(self) -> Panel:
        with self._lock:
            content = self._last_result
            rid = self._last_result_id
        title = "[bold]Последний результат[/]" + (f" [dim]({rid})[/]" if rid else "")
        lines = content.splitlines()[-self.MAX_RESULT_LINES:]
        body = "\n".join(lines) if lines else "[dim]Нет результатов[/]"
        return Panel(body, title=title, border_style="magenta")

    def _render_footer(self) -> Panel:
        return Panel(
            "[bold cyan]>[/] Введи задачу и нажми Enter  "
            "[dim]| exit — выход  | status — статус  | vault <файл> — показать файл[/]",
            style="dim",
            box=box.SIMPLE,
        )

    # ── Ввод команд ───────────────────────────────────────────────────────────

    def _input_loop(self) -> None:
        """
        Работает в отдельном потоке.
        Live захватывает alternate screen, поэтому читаем stdin напрямую.
        """
        while self._running:
            try:
                line = sys.stdin.readline()
                if line == "":          # EOF
                    self._handle_command("exit")
                    break
                line = line.strip()
            except (KeyboardInterrupt, EOFError):
                self._handle_command("exit")
                break
            if line:
                self._handle_command(line)

    def _handle_command(self, cmd: str) -> None:
        low = cmd.lower().strip()

        if low in ("exit", "quit", "q"):
            self._push_log("Завершение по команде пользователя")
            self._running = False
            self.manager.stop()
            return

        if low == "status":
            s = self.manager.status
            working = sum(1 for a in s["agents"] if a["status"] == "working")
            self._push_log(f"Агентов: {len(s['agents'])}, работают: {working}, очередь: {s['queue_size']}")
            return

        if low == "help":
            self._push_log("Команды: exit | status | vault <путь> | <任意задача>")
            return

        if low.startswith("vault "):
            fname = cmd[6:].strip()
            content = self.manager.memory.read(fname)
            if content:
                with self._lock:
                    self._last_result = content
                    self._last_result_id = fname
            else:
                self._push_log(f"Файл не найден: {fname}")
            return

        task_id = self.manager.submit_task(cmd)
        self._push_log(f"[cyan]Задача отправлена:[/] {task_id}")

    # ── Колбэки ───────────────────────────────────────────────────────────────

    def _push_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self._log.append(f"[{ts}] {msg}")

    def _push_result(self, result: "TaskResult") -> None:
        with self._lock:
            self._last_result = result.result[:4000]
            self._last_result_id = result.task_id
        elapsed = f"{result.elapsed:.1f}с" if result.elapsed else ""
        self._push_log(f"[green]Готово[/] {result.task_id} ({result.agent_id}{', ' + elapsed if elapsed else ''})")
