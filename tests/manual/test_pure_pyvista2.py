import sys
import os

print("STARTING NATIVE VTK TEST", flush=True)

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
import pyvista as pv
import vtk

print("IMPORTS DONE", flush=True)

app = QApplication(sys.argv)

class MyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        frame = QWidget()
        self.setCentralWidget(frame)
        layout = QVBoxLayout()
        frame.setLayout(layout)
        
        print("Creating QVTKRenderWindowInteractor...", flush=True)
        self.vtkWidget = QVTKRenderWindowInteractor(frame)
        layout.addWidget(self.vtkWidget)
        print("QVTKRenderWindowInteractor created.", flush=True)

        print("Creating PyVista Plotter...", flush=True)
        self.plotter = pv.Plotter(render_window=self.vtkWidget.GetRenderWindow(), off_screen=False)
        
        sphere = pv.Sphere()
        self.plotter.add_mesh(sphere)
        print("Mesh added.", flush=True)

win = MyWindow()
print("Showing window...", flush=True)
win.show()
self_iren = win.vtkWidget.GetRenderWindow().GetInteractor()
self_iren.Initialize()
self_iren.Start()
print("Window shown.", flush=True)

import PySide6.QtCore as QtCore
QtCore.QTimer.singleShot(2000, lambda: print("SUCCESS NATIVE VTK!", flush=True) or app.quit())

sys.exit(app.exec())
