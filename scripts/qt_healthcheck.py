#!/usr/bin/env python3
"""Minimal Qt/PySide6 health check for SelçukBolt startup."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_qt_environment() -> None:
    """Ensure Qt plugin and framework paths are visible on macOS."""
    os.environ.setdefault("QT_API", "pyside6")
    os.environ.setdefault("PYVISTA_QT_BACKEND", "PySide6")
    os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

    if sys.platform != "darwin":
        return

    try:
        import PySide6  # noqa: F401
    except Exception:
        return

    qt_root = Path(PySide6.__file__).resolve().parent / "Qt"
    qt_plugins = qt_root / "plugins"
    qt_platforms = qt_plugins / "platforms"
    qt_lib = qt_root / "lib"

    if qt_plugins.exists():
        os.environ["QT_PLUGIN_PATH"] = str(qt_plugins)
    if qt_platforms.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_platforms)
    if qt_lib.exists():
        lib_path = str(qt_lib)
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            current = os.environ.get(key, "")
            pieces = [lib_path]
            if current:
                pieces.extend(part for part in current.split(":") if part and part != lib_path)
            os.environ[key] = ":".join(pieces)


def main() -> int:
    configure_qt_environment()

    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    app.quit()
    print("qt-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
