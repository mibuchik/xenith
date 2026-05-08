"""
term_ui.py — Fullscreen chat TUI (OpenCode-стиль).

Ввод реализован через msvcrt.getwch() — читаем символы по одному,
показываем их в Live-панели. Это единственный надёжный способ
получить интерактивный ввод внутри Rich Live на Windows.
"""

from __future__ import annotations

import msvcrt
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

if TYPE_CHECKING:
    from core import AgentManager
    from orchestrator import TaskResult


@dataclass
class ChatMessage:
    role: str           # "you" | "agent-N" | "system"
    content: str
    model: str = ""
    ts: str = field(default_factory=lambda: time.strftime("%H:%M:%S"))


AGENT_COLORS = ["cyan", "green", "yellow", "magenta", "blue"]

STATUS_ICON = {
    "idle":    ("●", "green"),
    "working": ("⟳", "yellow"),
    "error":   ("✗", "red"),
    "stopped": ("○", "dim"),
}


class XenithUI:
    """Fullscreen chat TUI. Ввод — посимвольный через msvcrt."""

    def __init__(self, manager: "AgentManager") -> None:
        self.manager = manager
        self.console = Console()
        self._messages: list[ChatMessage] = []
        self._input_buf: list[str] = []     # буфер текущего ввода
        self._history: list[str] = []       # история команд
        self._running = False
        self._lock = threading.Lock()
        self._agent_colors: dict[str, str] = {
            ag.id: AGENT_COLORS[i % len(AGENT_COLORS)]
            for i, ag in enumerate(manager.agents)
        }

        manager.on_log(self._on_log)
        manager.on_result(self._on_result)

        self._push(ChatMessage(
            role="system",
            content=f"ready · {manager.agent_count} agents · vault: {manager.vault_path}",
        ))

    # ── Запуск ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        threading.Thread(target=self._input_loop, daemon=True, name="xenith-input").start()

        with Live(
            self._render(),
            console=self.console,
            refresh_per_second=8,
            screen=True,
        ) as live:
            while self._running:
                live.update(self._render())
                time.sleep(0.12)

    # ── Рендер ────────────────────────────────────────────────────────────────

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="chat"),
            Layout(name="sep", size=1),
            Layout(name="input", size=3),
        )
        layout["header"].update(self._render_header())
        layout["chat"].update(self._render_chat())
        layout["sep"].update(Rule(style="bright_black"))
        layout["input"].update(self._render_input())
        return layout

    def _render_header(self) -> Text:
        t = Text()
        t.append(" ◆ XENITH ", style="bold cyan")
        for ag in self.manager.agents:
            s = ag.stats
            icon, color = STATUS_ICON.get(s["status"], ("?", "white"))
            ag_color = self._agent_colors.get(ag.id, "cyan")
            t.append("  ", style="")
            t.append(f"{ag.id} ", style=f"bold {ag_color}")
            t.append(icon, style=color)
            t.append(f" {s['status']}", style="dim")
            if s["current_task"]:
                t.append(f" [{s['current_task']}]", style="dim yellow")
        q = self.manager.status["queue_size"]
        if q:
            t.append(f"  queue:{q}", style="yellow")
        return t

    def _render_chat(self) -> Panel:
        with self._lock:
            msgs = list(self._messages)

        height = max(4, self.console.size.height - 6)
        lines: list[Text] = []

        for msg in msgs:
            lines.append(Text(""))

            if msg.role == "system":
                lines.append(Text(f"  {msg.content}", style="dim italic"))
                continue

            if msg.role == "you":
                hdr = Text()
                hdr.append("  you", style="bold bright_white")
                hdr.append(f"  {msg.ts}", style="dim")
                lines.append(hdr)
                for ln in msg.content.splitlines() or [""]:
                    lines.append(Text(f"  ┃ {ln}", style="bright_white"))
            else:
                ag_color = self._agent_colors.get(msg.role, "cyan")
                hdr = Text()
                hdr.append(f"  {msg.role}", style=f"bold {ag_color}")
                if msg.model:
                    short = msg.model.split("/")[-1][:24]
                    hdr.append(f"  ·  {short}", style="dim")
                hdr.append(f"  {msg.ts}", style="dim")
                lines.append(hdr)
                for ln in msg.content.splitlines() or [""]:
                    lines.append(Text(f"  ┃ {ln}", style=ag_color))

        visible = lines[-height:] if len(lines) > height else lines
        body = Text("\n").join(visible)

        return Panel(body, border_style="bright_black", box=box.SIMPLE, padding=(0, 0))

    def _render_input(self) -> Panel:
        cursor = "█" if int(time.time() * 4) % 2 == 0 else " "
        with self._lock:
            buf = "".join(self._input_buf)
        t = Text()
        t.append("  ❯ ", style="bold cyan")
        t.append(buf, style="bright_white")
        t.append(cursor, style="bold cyan")
        return Panel(t, border_style="bright_black", box=box.SIMPLE, padding=(0, 0))

    # ── Ввод (посимвольный, Windows msvcrt) ──────────────────────────────────

    def _input_loop(self) -> None:
        while self._running:
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue

            ch = msvcrt.getwch()

            # Enter
            if ch in ("\r", "\n"):
                with self._lock:
                    line = "".join(self._input_buf)
                    self._input_buf.clear()
                if line.strip():
                    self._history.append(line)
                    self._handle(line.strip())

            # Backspace
            elif ch == "\x08":
                with self._lock:
                    if self._input_buf:
                        self._input_buf.pop()

            # Ctrl+C
            elif ch == "\x03":
                self._handle("exit")
                break

            # Ctrl+L — очистить чат
            elif ch == "\x0c":
                with self._lock:
                    self._messages.clear()
                self._push(ChatMessage(role="system", content="chat cleared"))

            # специальные клавиши (стрелки и т.д.) — двухбайтный код, пропускаем
            elif ch in ("\x00", "\xe0"):
                msvcrt.getwch()   # читаем второй байт и игнорируем

            # обычный символ
            elif ord(ch) >= 32:
                with self._lock:
                    self._input_buf.append(ch)

    # ── Команды ───────────────────────────────────────────────────────────────

    def _handle(self, cmd: str) -> None:
        low = cmd.lower()

        if low in ("exit", "quit", "q"):
            self._push(ChatMessage(role="system", content="shutting down..."))
            self._running = False
            self.manager.stop()
            return

        if low == "status":
            s = self.manager.status
            working = sum(1 for a in s["agents"] if a["status"] == "working")
            self._push(ChatMessage(
                role="system",
                content=(
                    f"agents: {len(s['agents'])}  working: {working}  "
                    f"queue: {s['queue_size']}  vault files: {s['vault_files']}"
                ),
            ))
            return

        if low == "help":
            self._push(ChatMessage(
                role="system",
                content="exit · status · vault <path> · Ctrl+L clear · or type a task",
            ))
            return

        if low.startswith("vault "):
            fname = cmd[6:].strip()
            content = self.manager.memory.read(fname)
            if content:
                self._push(ChatMessage(role="system", content=f"── {fname} ──\n{content[:1500]}"))
            else:
                self._push(ChatMessage(role="system", content=f"not found: {fname}"))
            return

        self._push(ChatMessage(role="you", content=cmd))
        self.manager.submit_task(cmd)

    # ── Колбэки ───────────────────────────────────────────────────────────────

    def _on_log(self, msg: str) -> None:
        pass   # системные логи не засоряют чат

    def _on_result(self, result: "TaskResult") -> None:
        agent_id = result.agent_id.split(",")[0].strip()
        model = next((ag.model for ag in self.manager.agents if ag.id == agent_id), "")
        self._push(ChatMessage(role=agent_id, content=result.result, model=model))

    def _push(self, msg: ChatMessage) -> None:
        with self._lock:
            self._messages.append(msg)
