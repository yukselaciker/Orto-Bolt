import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
output_path = Path(__file__).with_name("qt_success.txt")
with output_path.open("w", encoding="utf-8") as f:
    f.write("OK")
