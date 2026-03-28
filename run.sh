#!/bin/bash
set -e

# SelçukBolt — macOS launcher with Qt self-healing

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BOOTSTRAP_PYTHON="python3"
PYSIDE_VERSION="6.10.2"

# The project folder was renamed after the virtualenv was created.
# Repair entry-point scripts before we rely on them.
if [ -d "$SCRIPT_DIR/.venv" ]; then
    "$BOOTSTRAP_PYTHON" "$SCRIPT_DIR/scripts/repair_venv.py" "$SCRIPT_DIR/.venv" >/dev/null || true
fi

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
    export VIRTUAL_ENV="$SCRIPT_DIR/.venv"
    export PATH="$VIRTUAL_ENV/bin:$PATH"
else
    PYTHON="$BOOTSTRAP_PYTHON"
fi

PYSIDE_QT_DIR="$("$PYTHON" -c "import pathlib, PySide6; print((pathlib.Path(PySide6.__file__).resolve().parent / 'Qt').as_posix())" 2>/dev/null || true)"

if [ -n "$PYSIDE_QT_DIR" ]; then
    export QT_PLUGIN_PATH="$PYSIDE_QT_DIR/plugins"
    export QT_QPA_PLATFORM_PLUGIN_PATH="$PYSIDE_QT_DIR/plugins/platforms"
    export DYLD_FRAMEWORK_PATH="$PYSIDE_QT_DIR/lib${DYLD_FRAMEWORK_PATH:+:$DYLD_FRAMEWORK_PATH}"
    export DYLD_LIBRARY_PATH="$PYSIDE_QT_DIR/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

export QT_API="pyside6"
export PYVISTA_QT_BACKEND="PySide6"
export QT_MAC_WANTS_LAYER="1"

qt_healthcheck() {
    "$PYTHON" "$SCRIPT_DIR/scripts/qt_healthcheck.py"
}

repair_pyside() {
    echo "Qt/PySide6 acilis testi basarisiz. Otomatik onarim baslatiliyor..." >&2
    export PIP_DISABLE_PIP_VERSION_CHECK=1
    "$PYTHON" -m pip install --force-reinstall --no-deps \
        "PySide6==$PYSIDE_VERSION" \
        "PySide6_Addons==$PYSIDE_VERSION" \
        "PySide6_Essentials==$PYSIDE_VERSION" \
        "shiboken6==$PYSIDE_VERSION"
}

if [ "$1" = "--child" ]; then
    shift
fi

if ! qt_healthcheck >/dev/null 2>&1; then
    repair_pyside
    if ! qt_healthcheck >/dev/null 2>&1; then
        echo "Qt/PySide6 otomatik onarimi sonrasinda da 'cocoa' platform eklentisi acilamadi." >&2
        echo "Internet baglantisini kontrol edin ve tekrar deneyin." >&2
        exit 1
    fi
fi

if [ "$1" = "--dev" ]; then
    shift
    exec "$PYTHON" "$SCRIPT_DIR/scripts/dev_run.py" "$@"
fi

exec "$PYTHON" main.py "$@"
