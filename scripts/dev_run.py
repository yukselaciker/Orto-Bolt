"""
dev_run.py — PySide6 geliştirme modunda otomatik yeniden başlatıcı
==================================================================
Dosya değişikliklerini izler ve ana uygulamayı yeniden başlatır.

Kullanım:
    python scripts/dev_run.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WATCH_DIRS = ["ui", "core", "reports", "ai"]
WATCH_FILES = ["main.py"]
WATCH_SUFFIXES = {".py", ".qss", ".json"}
POLL_INTERVAL = 0.6
RESTART_LIMIT = 3
RESTART_WINDOW_SECONDS = 20.0


def _iter_watch_paths() -> list[Path]:
    paths: list[Path] = []
    for name in WATCH_FILES:
        candidate = ROOT / name
        if candidate.exists():
            paths.append(candidate)

    for directory in WATCH_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in WATCH_SUFFIXES:
                paths.append(path)
    return paths


def _snapshot_mtimes() -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for path in _iter_watch_paths():
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def _terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return

    try:
        proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def main() -> int:
    env = os.environ.copy()
    command = [str(ROOT / "run.sh"), "--child"]

    print("Gelistirme modu aktif. Dosya degisikliklerinde uygulama yeniden baslatilacak.", flush=True)
    print("Cikis icin Ctrl+C kullanin.", flush=True)

    snapshot = _snapshot_mtimes()
    proc = subprocess.Popen(command, cwd=ROOT, env=env)
    restart_times: list[float] = []

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            if proc.poll() is not None:
                now = time.time()
                restart_times = [ts for ts in restart_times if now - ts <= RESTART_WINDOW_SECONDS]
                restart_times.append(now)
                if len(restart_times) >= RESTART_LIMIT:
                    print(
                        "Uygulama art arda birkac kez acilamadi. Sonsuz yeniden baslatma durduruldu.",
                        flush=True,
                    )
                    print(
                        "Qt/PySide6 otomatik onarimi tamamlanamamis olabilir. ./run.sh komutunu tek basina calistirip ciktiyi kontrol edin.",
                        flush=True,
                    )
                    return 1
                print("Uygulama kapandi. Yeniden baslatiliyor...", flush=True)
                proc = subprocess.Popen(command, cwd=ROOT, env=env)
                snapshot = _snapshot_mtimes()
                continue

            current = _snapshot_mtimes()
            if current != snapshot:
                print("Degisiklik algilandi. Uygulama yeniden baslatiliyor...", flush=True)
                _terminate_process(proc)
                proc = subprocess.Popen(command, cwd=ROOT, env=env)
                restart_times.clear()
                snapshot = current
    except KeyboardInterrupt:
        print("\nGelistirme modu kapatiliyor...", flush=True)
        _terminate_process(proc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
