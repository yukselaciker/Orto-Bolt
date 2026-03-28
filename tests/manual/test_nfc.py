import sys
import os

os.environ["QT_API"] = "pyside6"

from PySide6.QtWidgets import QApplication
try:
    app = QApplication(sys.argv)
    print("SUCCESS WITH PRE-INIT INJECTION")
except Exception as e:
    print("EXCEPTION:", e)
