"""
memory.py — Подсистема памяти XENITH.

Смешанный режим:
  • Pinned-файлы (_context/*.md и файлы с тегом #pinned) всегда в контексте.
  • Остальные файлы ищутся по ключевым словам запроса.
  • watchdog отслеживает изменения vault в реальном времени.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class VaultMemory:
    """Менеджер памяти на основе Obsidian Vault."""

    PINNED_TAG = "#pinned"

    def __init__(self, vault_path: str | Path) -> None:
        self.vault = Path(vault_path).resolve()
        self._cache: dict[Path, str] = {}
        self._lock = threading.RLock()
        self._change_callbacks: list[Callable[[Path], None]] = []
        self._load_all()
        self._start_watcher()

    # ── Загрузка ──────────────────────────────────────────────────────────────

    def _load_all(self) -> None:
        """Читает все .md файлы vault в кэш."""
        with self._lock:
            for md in self.vault.rglob("*.md"):
                try:
                    self._cache[md] = md.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass

    def _load_file(self, path: Path) -> None:
        with self._lock:
            if path.exists():
                try:
                    self._cache[path] = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
            else:
                self._cache.pop(path, None)

    # ── Pinned-файлы ──────────────────────────────────────────────────────────

    def pinned_context(self) -> str:
        """Возвращает объединённый текст всех pinned-файлов."""
        parts: list[str] = []
        with self._lock:
            for path, content in self._cache.items():
                is_context_dir = "_context" in path.parts
                has_tag = self.PINNED_TAG in content
                if is_context_dir or has_tag:
                    parts.append(f"## [{path.name}]\n{content}")
        return "\n\n".join(parts)

    # ── Поиск ─────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[tuple[Path, str]]:
        """
        Ищет файлы, наиболее релевантные запросу.
        Простой TF-подход: считаем совпадения слов запроса в тексте файла.
        """
        keywords = set(re.findall(r"\w+", query.lower()))
        scores: list[tuple[float, Path, str]] = []
        with self._lock:
            for path, content in self._cache.items():
                text_lower = content.lower()
                score = sum(text_lower.count(kw) for kw in keywords)
                if score > 0:
                    scores.append((score, path, content))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [(p, c) for _, p, c in scores[:top_k]]

    def build_context(self, query: str) -> str:
        """
        Формирует полный контекст для агента:
        pinned-файлы + топ-5 релевантных файлов по запросу.
        """
        pinned = self.pinned_context()
        results = self.search(query)
        found_parts = [
            f"## [{p.name}] (найдено по запросу)\n{c}"
            for p, c in results
        ]
        sections = []
        if pinned:
            sections.append(f"# ПОСТОЯННЫЙ КОНТЕКСТ (Pinned)\n{pinned}")
        if found_parts:
            sections.append("# НАЙДЕНО ПО ЗАПРОСУ\n" + "\n\n".join(found_parts))
        return "\n\n---\n\n".join(sections)

    # ── Запись ────────────────────────────────────────────────────────────────

    def write(self, relative_path: str, content: str, append: bool = False) -> Path:
        """
        Записывает или дополняет .md файл в vault.

        Args:
            relative_path: путь относительно vault (например "tasks/result.md")
            content:        текст для записи
            append:         True — дописать в конец, False — перезаписать
        """
        target = self.vault / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)
        with self._lock:
            self._cache[target] = target.read_text(encoding="utf-8")
        return target

    def read(self, relative_path: str) -> str | None:
        """Читает файл из кэша или с диска."""
        target = self.vault / relative_path
        with self._lock:
            if target in self._cache:
                return self._cache[target]
        if target.exists():
            text = target.read_text(encoding="utf-8")
            with self._lock:
                self._cache[target] = text
            return text
        return None

    # ── Watcher ───────────────────────────────────────────────────────────────

    def on_change(self, callback: Callable[[Path], None]) -> None:
        """Регистрирует callback, вызываемый при изменении любого файла vault."""
        self._change_callbacks.append(callback)

    def _start_watcher(self) -> None:
        handler = _VaultEventHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault), recursive=True)
        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()

    def list_files(self) -> list[Path]:
        with self._lock:
            return list(self._cache.keys())


class _VaultEventHandler(FileSystemEventHandler):
    """Обработчик событий файловой системы для watchdog."""

    def __init__(self, memory: VaultMemory) -> None:
        self._mem = memory

    def _handle(self, event: FileSystemEvent) -> None:
        path = Path(event.src_path)
        if path.suffix != ".md":
            return
        self._mem._load_file(path)
        for cb in self._mem._change_callbacks:
            cb(path)

    on_created = _handle
    on_modified = _handle
    on_deleted = _handle
