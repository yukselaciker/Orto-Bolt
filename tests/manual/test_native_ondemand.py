import sys, os
os.environ["QT_API"] = "pyside6"
os.environ["PYVISTA_QT_BACKEND"] = "PySide6"

print("STARTING TEST", flush=True)
import pyvista as pv
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

app = QApplication(sys.argv)

class MyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.frame = QWidget()
        self.setCentralWidget(self.frame)
        self.layout = QVBoxLayout()
        self.frame.setLayout(self.layout)
        
    def do_load(self):
        print("Creating QVTKRenderWindowInteractor... ON DEMAND", flush=True)
        self.vtkWidget = QVTKRenderWindowInteractor(self.frame)
        self.layout.addWidget(self.vtkWidget)
        print("Created QVTK.", flush=True)

        self.plotter = pv.Plotter(render_window=self.vtkWidget.GetRenderWindow(), off_screen=False)
        self.vtkWidget.Initialize()
        self.vtkWidget.Start()
        
        sphere = pv.Sphere()
        self.plotter.add_mesh(sphere)
        print("Mesh added.", flush=True)

win = MyWindow()
print("Showing window...", flush=True)
win.show()

import PySide6.QtCore as QtCore
QtCore.QTimer.singleShot(1000, win.do_load)
QtCore.QTimer.singleShot(2500, lambda: print("SUCCESS NATIVE VTK ON DEMAND!", flush=True) or app.quit())

sys.exit(app.exec())
