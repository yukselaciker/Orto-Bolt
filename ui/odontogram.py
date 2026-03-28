from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton, QVBoxLayout, QLabel


class OdontogramWidget(QFrame):
    """Aktif çene için tıklanabilir diş haritası."""

    tooth_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jaw = "maxillary"
        self._buttons: dict[int, QPushButton] = {}
        self._active_tooth: int | None = None
        self._completed_teeth: set[int] = set()

        self.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.92);
                border: 1px solid #D7E8EE;
                border-radius: 16px;
            }
            QLabel {
                color: #16303A;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title_label = QLabel("Odontogram")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Aktif dişi seçin")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet("font-size: 11px; color: #5F7480;")
        layout.addWidget(self.subtitle_label)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 6, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        layout.addLayout(self.grid)

    def set_arch(self, jaw: str, teeth: Iterable[int]) -> None:
        """Çeneye göre diş butonlarını yeniden kur."""
        self._jaw = jaw
        self._active_tooth = None
        self._buttons.clear()
        self._clear_grid()

        teeth = list(teeth)
        self.title_label.setText("Maksilla Odontogramı" if jaw == "maxillary" else "Mandibula Odontogramı")

        for tooth_fdi, (row, col) in zip(teeth, self._positions_for(jaw, len(teeth))):
            button = QPushButton(str(tooth_fdi))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(42, 36)
            button.clicked.connect(lambda _checked=False, fdi=tooth_fdi: self.tooth_clicked.emit(fdi))
            self.grid.addWidget(button, row, col)
            self._buttons[tooth_fdi] = button
            self._apply_button_style(tooth_fdi)

    def set_completed_teeth(self, completed_teeth: Iterable[int]) -> None:
        self._completed_teeth = set(int(tooth) for tooth in completed_teeth)
        for tooth_fdi in self._buttons:
            self._apply_button_style(tooth_fdi)

    def set_active_tooth(self, tooth_fdi: int | None) -> None:
        self._active_tooth = tooth_fdi
        for existing_fdi in self._buttons:
            self._apply_button_style(existing_fdi)

    def _apply_button_style(self, tooth_fdi: int) -> None:
        button = self._buttons.get(tooth_fdi)
        if button is None:
            return

        if tooth_fdi == self._active_tooth:
            bg = "#0EA5A4"
            fg = "#FFFFFF"
            border = "#0B7C7B"
        elif tooth_fdi in self._completed_teeth:
            bg = "#DDF4E7"
            fg = "#1E7A44"
            border = "#8ED0A8"
        else:
            bg = "#F7FBFD"
            fg = "#23404B"
            border = "#D3E2E8"

        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                border-color: #63BBD3;
            }}
        """)

    def _positions_for(self, jaw: str, count: int) -> list[tuple[int, int]]:
        cols = list(range(count))
        if jaw == "maxillary":
            rows = [0, 1, 2, 3, 4, 5, 5, 4, 3, 2, 1, 0]
        else:
            rows = [5, 4, 3, 2, 1, 0, 0, 1, 2, 3, 4, 5]
        return list(zip(rows[:count], cols))

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
