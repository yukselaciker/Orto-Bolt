"""
main.py — SelçukBolt Uygulama Giriş Noktası
============================================
Faz 1: Uygulamayı başlatır, Qt olay döngüsünü çalıştırır.

Kullanım:
    python main.py
"""

import sys
import os
import ctypes
import subprocess
from pathlib import Path

os.environ["QT_API"] = "pyside6"

# PyVista'nın Qt backend'ini kullanmasını sağla
os.environ["PYVISTA_QT_BACKEND"] = "PySide6"
PYSIDE_VERSION = "6.10.2"
QT_REPAIR_ENV = "SELCUKBOLT_QT_REPAIR_ATTEMPTED"


def _qt_healthcheck_path() -> Path:
    return Path(__file__).resolve().parent / "scripts" / "qt_healthcheck.py"


def _run_qt_healthcheck() -> bool:
    """Minimal Qt açılışını ayrı süreçte test eder."""
    healthcheck_path = _qt_healthcheck_path()
    if not healthcheck_path.exists():
        return True

    try:
        result = subprocess.run(
            [sys.executable, str(healthcheck_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _attempt_qt_self_repair() -> bool:
    """PySide6 kurulumunu yeniden yükleyerek Qt cocoa plugin zincirini onarmayı dener."""
    packages = [
        f"PySide6=={PYSIDE_VERSION}",
        f"PySide6_Addons=={PYSIDE_VERSION}",
        f"PySide6_Essentials=={PYSIDE_VERSION}",
        f"shiboken6=={PYSIDE_VERSION}",
    ]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", *packages],
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ensure_qt_runtime() -> None:
    """Qt cocoa platform plugin başlatılamıyorsa bir kez otomatik onarım dener."""
    if _run_qt_healthcheck():
        return

    if os.environ.get(QT_REPAIR_ENV) == "1":
        return

    print(
        "SelçukBolt Qt acilis on-kontrolu basarisiz. PySide6 otomatik onarimi deneniyor...",
        flush=True,
    )
    if not _attempt_qt_self_repair():
        return

    os.environ[QT_REPAIR_ENV] = "1"
    os.execve(sys.executable, [sys.executable, __file__, *sys.argv[1:]], os.environ)


def _configure_qt_environment() -> None:
    """Configure PySide6 plugin paths explicitly for macOS launches."""
    if sys.platform != "darwin":
        return

    try:
        import PySide6
    except Exception:
        return

    qt_root = Path(PySide6.__file__).resolve().parent / "Qt"
    qt_plugins = qt_root / "plugins"
    qt_platforms = qt_plugins / "platforms"
    qt_lib = qt_root / "lib"

    if qt_plugins.exists():
        os.environ.setdefault("QT_PLUGIN_PATH", str(qt_plugins))
    if qt_platforms.exists():
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(qt_platforms))

    # VTK/Qt on macOS is more reliable when Qt frameworks are discoverable.
    if qt_lib.exists():
        lib_path = str(qt_lib)

        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            existing = os.environ.get(key, "")
            paths = [lib_path]

            if existing:
                paths.extend([part for part in existing.split(":") if part and part != lib_path])

            os.environ[key] = ":".join(paths)

    os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")


_configure_qt_environment()
_ensure_qt_runtime()

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from ui.main_window import MainWindow


def _activate_macos_app() -> None:
    """macOS'ta Python ile açılan Qt penceresini foreground app olarak aktive eder."""
    if sys.platform != "darwin":
        return

    try:
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        msg_send = objc.objc_msgSend
        msg_send.restype = ctypes.c_void_p
        msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        ns_application = objc.objc_getClass(b"NSApplication")
        shared_application = objc.sel_registerName(b"sharedApplication")
        app = msg_send(ns_application, shared_application)

        set_activation_policy = objc.sel_registerName(b"setActivationPolicy:")
        activate_ignoring_other_apps = objc.sel_registerName(b"activateIgnoringOtherApps:")

        msg_send.restype = None
        msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        msg_send(app, set_activation_policy, 0)

        msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        msg_send(app, activate_ignoring_other_apps, True)
    except Exception:
        # Cocoa aktivasyonu başarısızsa Qt'nin kendi fokus çağrılarıyla devam et.
        return


def _bring_window_to_front(window: MainWindow) -> None:
    """Pencereyi görünür, seçili ve önde tutar."""
    window.show()
    window.raise_()
    window.activateWindow()
    _activate_macos_app()


def main():
    """Uygulamayı başlatır ve ana pencereyi gösterir."""
    # Qt uygulaması oluştur
    app = QApplication(sys.argv)

    # Mac yerel fontlarına geçiş — sistem performans uyarısını kaldırmak için
    font = QFont(".AppleSystemUIFont", 10)
    app.setFont(font)

    # Uygulama meta verileri
    app.setApplicationName("SelçukBolt")
    app.setApplicationVersion("1.0.0-phase1")
    app.setOrganizationName("Orthodontic Research")

    # Yüksek DPI desteği (Retina ekranlar için)
    app.setStyle("Fusion")  # Platform bağımsız, karanlık temaya uyumlu

    # Ana pencereyi oluştur ve göster
    window = MainWindow()
    _bring_window_to_front(window)
    QTimer.singleShot(300, lambda: _bring_window_to_front(window))

    # Qt olay döngüsünü başlat
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
