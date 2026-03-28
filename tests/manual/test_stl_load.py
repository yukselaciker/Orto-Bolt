import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ["QSG_RENDER_LOOP"] = "basic"
os.environ["QT_MAC_WANTS_LAYER"] = "1"

print("SCRIPT START", flush=True)
import pyvista as pv
from PySide6.QtWidgets import QApplication, QFileDialog
from ui.main_window import MainWindow

app = QApplication(sys.argv)
window = MainWindow()
window.show()

dummy_path = ROOT / "tests" / "fixtures" / "dummy.stl"
if not os.path.exists(dummy_path):
    sphere = pv.Sphere()
    sphere.save(dummy_path)

def mock_getOpenFileName(*args, **kwargs):
    return str(dummy_path), ""
QFileDialog.getOpenFileName = mock_getOpenFileName

def test_load():
    print("Executing _load_maxilla...", flush=True)
    window._load_maxilla()
    print("FINISHED _load_maxilla call", flush=True)

import PySide6.QtCore as QtCore
QtCore.QTimer.singleShot(500, test_load)
QtCore.QTimer.singleShot(2500, lambda: print("TEST COMPLETED. NO DEADLOCK!", flush=True) or app.quit())

print("STARTING EVENT LOOP", flush=True)
sys.exit(app.exec())
