"""
Підключення рушія Pikafish (або будь-якого UCI-рушія для сянці)

Рушій - окрема програма. Спілкуємось з нею текстом через stdin/stdout
(протокол UCI). Формат ходів у Pikafish збігається з Move.uci: "h2e2".

Де шукається рушій (по черзі):
  1) аргумент path=...
  2) змінна оточення PIKAFISH_PATH
  3) <корінь репозиторію>/engines/pikafish      (Linux / macOS)
     <корінь репозиторію>/engines/pikafish.exe  (Windows)
Файл pikafish.nnue має лежати в тій самій папці, що й бінарник.
"""
from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
from pathlib import Path
from typing import List, Optional, Sequence, Union

from .board import START_FEN

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINES_DIR = REPO_ROOT / "engines"
IS_WINDOWS = platform.system() == "Windows"
DEFAULT_EXE = "pikafish.exe" if IS_WINDOWS else "pikafish"


class EngineError(RuntimeError):
    """
    Рушій не знайдено, він впав, не відповів вчасно або повідомив про помилку
    """


def find_engine(path: Optional[Union[str, Path]] = None) -> Path:
    candidate = path or os.environ.get("PIKAFISH_PATH") or ENGINES_DIR / DEFAULT_EXE
    candidate = Path(candidate).expanduser().resolve()
    if not candidate.is_file():
        raise EngineError(
            f"Рушій не знайдено: {candidate}\n"
            f"Завантажте Pikafish і покладіть {DEFAULT_EXE} та pikafish.nnue у {ENGINES_DIR}, "
            "або вкажіть шлях у змінній оточення PIKAFISH_PATH. Інструкція в README.md."
        )
    if not IS_WINDOWS and not os.access(candidate, os.X_OK):
        raise EngineError(f"Файл не виконуваний: {candidate}. Виконайте: chmod +x {candidate}")
    return candidate


class UCIEngine:
    """
    Обгортка над UCI-рушієм.

        with UCIEngine() as engine:
            engine.new_game()
            move = engine.best_move(["h2e2"], movetime_ms=1000)   # -> "h9g7"
    """

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        command: Optional[Sequence[str]] = None,
        threads: int = 1,
        hash_mb: int = 64,
        timeout: float = 10.0,
    ):
        """
        command - готова команда запуску замість path (використовується в тестах
        для фейкового рушія: [sys.executable, "fake_engine.py"])
        timeout - скільки секунд чекати відповіді на службові команди
        """
        if command is None:
            exe = find_engine(path)
            command = [str(exe)]
            cwd = str(exe.parent)  # щоб рушій знайшов pikafish.nnue поруч із собою
        else:
            cwd = None

        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        try:
            self._proc = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=cwd,
                creationflags=flags,
            )
        except OSError as err:
            raise EngineError(f"Не вдалося запустити рушій {command}: {err}") from err

        self.timeout = timeout
        self.log: List[str] = []  # останні рядки від рушія, для діагностики
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        # Окремий потік читає stdout, щоб можна було чекати з таймаутом
        # (readline() сам по собі блокується назавжди, якщо рушій завис)
        threading.Thread(target=self._reader, daemon=True).start()

        self.name = "unknown"
        self._send("uci")
        for line in self._read_until("uciok"):
            if line.startswith("id name "):
                self.name = line[len("id name "):]
        self.set_option("Threads", threads)
        self.set_option("Hash", hash_mb)
        self.wait_ready()
        # Pikafish перевіряє nnue лише на першому 'go'. Робимо коротку пробу одразу,
        # щоб помилка з мережею з'явилась при запуску програми, а не посеред партії.
        self.best_move(depth=1)

    # ---------- низький рівень ----------

    def _reader(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._lines.put(line.rstrip("\r\n"))
        self._lines.put(None)  # рушій закрив вивід (завершився)

    def _send(self, cmd: str) -> None:
        if self._proc.poll() is not None:
            raise EngineError(self._death_message())
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write(cmd + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as err:
            raise EngineError(self._death_message()) from err

    def _read_line(self, timeout: Optional[float]) -> str:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise EngineError(f"Рушій не відповів за {timeout} с") from None
        if line is None:
            raise EngineError(self._death_message())
        self.log = (self.log + [line])[-50:]
        # Pikafish повідомляє про проблеми (наприклад, з nnue) рядками "info string ERROR: ..."
        if line.startswith("info string ERROR"):
            raise EngineError(self._death_message())
        return line

    def _read_until(self, prefix: str, timeout: Optional[float] = None) -> List[str]:
        timeout = self.timeout if timeout is None else timeout
        lines = []
        while True:
            line = self._read_line(timeout)
            lines.append(line)
            if line.startswith(prefix):
                return lines

    def _death_message(self) -> str:
        # Дочитати, що рушій встиг написати перед смертю
        try:
            while True:
                line = self._lines.get(timeout=0.2)
                if line is None:
                    break
                self.log.append(line)
        except queue.Empty:
            pass
        errors = [l for l in self.log if "ERROR" in l] or self.log[-5:]
        hint = ""
        if any("nnue" in l.lower() or "network" in l.lower() for l in errors):
            hint = ("\nПідказка: pikafish.nnue має бути поруч із бінарником і з того самого релізу, "
                    "що й бінарник.")
        return "Рушій завершився або повідомив про помилку:\n  " + "\n  ".join(errors) + hint

    # ---------- команди ----------

    def set_option(self, name: str, value) -> None:
        self._send(f"setoption name {name} value {value}")

    def wait_ready(self) -> None:
        self._send("isready")
        self._read_until("readyok")

    def new_game(self) -> None:
        """
        Викликати перед кожною новою партією
        """
        self._send("ucinewgame")
        self.wait_ready()

    def _position(self, moves: Sequence[str], fen: str) -> None:
        cmd = f"position fen {fen}"
        if moves:
            cmd += " moves " + " ".join(moves)
        self._send(cmd)

    def best_move(
        self,
        moves: Sequence[str] = (),
        fen: str = START_FEN,
        movetime_ms: Optional[int] = 1000,
        depth: Optional[int] = None,
    ) -> Optional[str]:
        """
        Найкращий хід у позиції 'fen' після ходів 'moves'.
        Повертає UCI-хід ("h2e2") або None, якщо ходів немає (мат/пат).

        Сила гри: depth=3..6 - слабо/помірно, movetime_ms=1000+ - дуже сильно.
        Якщо задано depth, movetime_ms ігнорується.
        """
        self._position(moves, fen)
        if depth is not None:
            self._send(f"go depth {depth}")
            wait = max(self.timeout, 60.0)
        else:
            self._send(f"go movetime {movetime_ms}")
            wait = movetime_ms / 1000 + self.timeout
        line = self._read_until("bestmove", timeout=wait)[-1]
        parts = line.split()
        if len(parts) < 2 or parts[1] in ("(none)", "0000"):
            return None
        return parts[1]

    def legal_moves(self, moves: Sequence[str] = (), fen: str = START_FEN) -> List[str]:
        """
        Усі ПОВНІСТЮ легальні ходи (з урахуванням шаху, зв'язок, «літаючого генерала»).
        Використовує команду 'go perft 1', яку рушій виконує миттєво.
        Порожній список - сторона, що ходить, програла (у сянці пат теж поразка).
        """
        self._position(moves, fen)
        self._send("go perft 1")
        result = []
        for line in self._read_until("Nodes searched"):
            head, sep, _ = line.partition(":")
            if sep and len(head) == 4 and head[0].isalpha() and head[1].isdigit():
                result.append(head)
        return result

    # ---------- завершення ----------

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._send("quit")
                self._proc.wait(timeout=3)
            except (EngineError, subprocess.TimeoutExpired):
                self._proc.kill()
                self._proc.wait()

    def __enter__(self) -> "UCIEngine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
