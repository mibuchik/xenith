"""
term_ui.py — Fullscreen chat-style TUI (OpenCode-стиль).

Компоновка:
  ┌─ XENITH ── agent-1 ● idle ── agent-2 ⟳ working ─────────────────────────┐
  │                                                                          │
  │  you                                                                     │
  │  ┃ напиши функцию сортировки                                             │
  │                                                                          │
  │  agent-1 · qwen2.5-coder                                                 │
  │  ┃ def quicksort(arr): ...                                               │
  │                                                                          │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ ❯ _                                                                      │
  └──────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text
from rich import box

if TYPE_CHECKING:
    from core import AgentManager
    from orchestrator import TaskResult


# ── Типы сообщений ────────────────────────────────────────────────────────────

@dataclass
class ChatMessage:
    role: str           # "you" | "agent-1" | "system"
    content: str
    model: str = ""
    ts: str = field(default_factory=lambda: time.strftime("%H:%M:%S"))


# ── Цвета и стили ─────────────────────────────────────────────────────────────

ROLE_STYLE = {
    "you":    ("bright_white", "bold"),
    "system": ("dim",          ""),
}

AGENT_COLORS = ["cyan", "green", "yellow", "magenta", "blue"]

STATUS_ICON = {
    "idle":    ("●", "green"),
    "working": ("⟳", "yellow"),
    "error":   ("✗", "red"),
    "stopped": ("○", "dim"),
}


class XenithUI:
    """Fullscreen chat TUI. Вся история — в _messages, Live её рендерит."""

    def __init__(self, manager: "AgentManager") -> None:
        self.manager = manager
        self.console = Console()
        self._messages: list[ChatMessage] = []
        self._input_line: str = ""
        self._running = False
        self._lock = threading.Lock()
        self._agent_colors: dict[str, str] = {}

        # назначаем каждому агенту свой цвет
        for i, ag in enumerate(manager.agents):
            self._agent_colors[ag.id] = AGENT_COLORS[i % len(AGENT_COLORS)]

        manager.on_log(self._on_log)
        manager.on_result(self._on_result)

        # стартовое сообщение
        self._push(ChatMessage(
            role="system",
            content=f"XENITH ready · {manager.agent_count} agents · vault: {manager.vault_path}",
        ))

    # ── Запуск ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        threading.Thread(target=self._input_loop, daemon=True, name="xenith-input").start()

        with Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            while self._running:
                live.update(self._render())
                time.sleep(0.25)

    # ── Рендер ────────────────────────────────────────────────────────────────

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="chat"),
            Layout(name="divider", size=1),
            Layout(name="input", size=3),
        )
        layout["header"].update(self._render_header())
        layout["chat"].update(self._render_chat())
        layout["divider"].update(Rule(style="bright_black"))
        layout["input"].update(self._render_input())
        return layout

    def _render_header(self) -> Text:
        t = Text()
        t.append(" ◆ XENITH ", style="bold cyan")
        t.append("  ", style="")
        for ag in self.manager.agents:
            s = ag.stats
            icon, color = STATUS_ICON.get(s["status"], ("?", "white"))
            ag_color = self._agent_colors.get(ag.id, "white")
            model_short = s["model"].split("/")[-1][:18]
            t.append(f"{ag.id} ", style=f"bold {ag_color}")
            t.append(f"{icon} {s['status']}", style=color)
            if s["current_task"]:
                t.append(f" [{s['current_task']}]", style="dim")
            t.append("  ·  ", style="bright_black")
        # убираем последний разделитель
        q = self.manager.status["queue_size"]
        if q:
            t.append(f"queue: {q}", style="yellow")
        return t

    def _render_chat(self) -> Panel:
        with self._lock:
            msgs = list(self._messages)

        # сколько строк помещается в панели (грубая оценка)
        height = self.console.size.height - 6
        lines: list[Text] = []

        for msg in msgs:
            lines.append(Text(""))   # пустая строка-разделитель

            if msg.role == "system":
                lines.append(Text(f"  {msg.content}", style="dim italic"))
                continue

            if msg.role == "you":
                # заголовок
                hdr = Text()
                hdr.append("  you", style="bold bright_white")
                hdr.append(f"  {msg.ts}", style="dim")
                lines.append(hdr)
                for ln in msg.content.splitlines():
                    lines.append(Text(f"  ┃ {ln}", style="bright_white"))
            else:
                # агент
                ag_color = self._agent_colors.get(msg.role, "cyan")
                hdr = Text()
                hdr.append(f"  {msg.role}", style=f"bold {ag_color}")
                if msg.model:
                    hdr.append(f"  ·  {msg.model.split('/')[-1]}", style="dim")
                hdr.append(f"  {msg.ts}", style="dim")
                lines.append(hdr)
                for ln in msg.content.splitlines():
                    lines.append(Text(f"  ┃ {ln}", style=ag_color))

        # показываем только то, что влезает снизу
        visible = lines[-height:] if len(lines) > height else lines
        body = Text("\n").join(visible)

        return Panel(
            body,
            border_style="bright_black",
            box=box.SIMPLE,
            padding=(0, 0),
        )

    def _render_input(self) -> Panel:
        cursor = "█" if int(time.time() * 2) % 2 == 0 else " "
        t = Text()
        t.append("  ❯ ", style="bold cyan")
        t.append(self._input_line, style="bright_white")
        t.append(cursor, style="bold cyan")
        return Panel(t, border_style="bright_black", box=box.SIMPLE, padding=(0, 0))

    # ── Ввод ──────────────────────────────────────────────────────────────────

    def _input_loop(self) -> None:
        while self._running:
            try:
                line = sys.stdin.readline()
                if line == "":
                    self._handle("exit")
                    break
                line = line.strip()
            except (KeyboardInterrupt, EOFError):
                self._handle("exit")
                break
            if line:
                with self._lock:
                    self._input_line = ""
                self._handle(line)

    def _handle(self, cmd: str) -> None:
        low = cmd.lower().strip()

        if low in ("exit", "quit", "q"):
            self._push(ChatMessage(role="system", content="Shutting down..."))
            self._running = False
            self.manager.stop()
            return

        if low == "status":
            s = self.manager.status
            working = sum(1 for a in s["agents"] if a["status"] == "working")
            self._push(ChatMessage(
                role="system",
                content=f"agents: {len(s['agents'])}  working: {working}  queue: {s['queue_size']}  vault files: {s['vault_files']}",
            ))
            return

        if low == "help":
            self._push(ChatMessage(
                role="system",
                content="commands: exit · status · vault <path> · or just type a task",
            ))
            return

        if low.startswith("vault "):
            fname = cmd[6:].strip()
            content = self.manager.memory.read(fname)
            if content:
                self._push(ChatMessage(role="system", content=f"── {fname} ──\n{content[:1000]}"))
            else:
                self._push(ChatMessage(role="system", content=f"file not found: {fname}"))
            return

        # задача для агентов
        self._push(ChatMessage(role="you", content=cmd))
        task_id = self.manager.submit_task(cmd)

    # ── Колбэки ───────────────────────────────────────────────────────────────

    def _on_log(self, msg: str) -> None:
        # системные логи — тихо, не мусорим чат
        pass

    def _on_result(self, result: "TaskResult") -> None:
        # первый агент из строки "agent-1, agent-2"
        agent_id = result.agent_id.split(",")[0].strip()
        model = ""
        for ag in self.manager.agents:
            if ag.id == agent_id:
                model = ag.model
                break
        self._push(ChatMessage(role=agent_id, content=result.result, model=model))

    def _push(self, msg: ChatMessage) -> None:
        with self._lock:
            self._messages.append(msg)
