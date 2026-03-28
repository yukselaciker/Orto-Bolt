import sys, os
os.environ["QT_API"] = "pyside6"
os.environ["PYVISTA_QT_BACKEND"] = "PySide6"

print("STARTING TEST", flush=True)
import pyvista as pv
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

app = QApplication(sys.argv)

class MyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.frame = QWidget()
        self.setCentralWidget(self.frame)
        self.layout = QVBoxLayout()
        self.frame.setLayout(self.layout)
        
    def do_load(self):
        print("Creating QtInteractor... ON DEMAND", flush=True)
        self.plotter = QtInteractor(self.frame, multi_samples=0)

        # DEADLOCK FIX: Override paintEvent to prevent infinite loop on macOS
        def safe_paintEvent(ev):
            pass
        self.plotter.paintEvent = safe_paintEvent

        self.layout.addWidget(self.plotter)
        print("Created QtInteractor.", flush=True)

        sphere = pv.Sphere()
        self.plotter.add_mesh(sphere)
        self.plotter.render() # Manual initial render
        print("Mesh added.", flush=True)

win = MyWindow()
print("Showing window...", flush=True)
win.show()

import PySide6.QtCore as QtCore
QtCore.QTimer.singleShot(1000, win.do_load)
QtCore.QTimer.singleShot(2500, lambda: print("SUCCESS PAINT MOCK!", flush=True) or app.quit())

sys.exit(app.exec())
