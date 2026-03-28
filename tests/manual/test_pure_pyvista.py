import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor
import pyvista as pv

app = QApplication(sys.argv)

class MyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        frame = QWidget()
        self.setCentralWidget(frame)
        layout = QVBoxLayout()
        frame.setLayout(layout)
        
        print("Creating QtInteractor...", flush=True)
        self.plotter = QtInteractor(frame)
        layout.addWidget(self.plotter.interactor)
        print("QtInteractor created.", flush=True)

        sphere = pv.Sphere()
        self.plotter.add_mesh(sphere)
        print("Mesh added.", flush=True)

win = MyWindow()
print("Showing window...", flush=True)
win.show()
print("Window shown.", flush=True)

import PySide6.QtCore as QtCore
QtCore.QTimer.singleShot(2000, lambda: print("SUCCESS!", flush=True) or app.quit())

sys.exit(app.exec())
