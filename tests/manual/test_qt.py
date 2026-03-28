import sys
import os
import PyQt6

print("PyQt6 Location:", PyQt6.__file__)
print("Starting QApplication...")
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
print("SUCCESS: QApplication running!")
