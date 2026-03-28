import sys
import pyvista as pv
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton
from PySide6.QtCore import QThread, Signal

class Worker(QThread):
    finished = Signal(object)
    def run(self):
        print("Thread running...")
        mesh = pv.Sphere()
        print("Mesh created. Emitting...")
        try:
            self.finished.emit(mesh)
            print("Emitted successfully.")
        except Exception as e:
            print(f"Emit error: {e}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.btn = QPushButton("Test")
        self.btn.clicked.connect(self.start)
        self.setCentralWidget(self.btn)
    def start(self):
        print("Starting thread...")
        self.w = Worker()
        self.w.finished.connect(self.on_finished)
        self.w.start()
    def on_finished(self, mesh):
        print(f"Received mesh: {mesh}")
        app.quit()

app = QApplication(sys.argv)
w = MainWindow()
w.show()
w.start()
sys.exit(app.exec())
