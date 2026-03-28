"""
ui/measurement_table.py — Ölçüm Tablosu + FDI Diş Izgarası
=============================================================
Faz 2: FDI buton ızgarası ile diş seçimi, nokta seçimi, ölçüm tablosu.

Tasarım Kararı:
    Dropdown yerine anatomik FDI buton ızgarası kullanıyoruz çünkü:
    - Ortodontistler diş haritasını görsel olarak okumaya alışıktır
    - Hangi dişlerin ölçüldüğü tek bakışta anlaşılır
    - Auto-advance sayesinde akış kesintisiz devam eder

    Izgara düzeni (hastanın ağzına karşıdan bakış):
        Sağ ←──── ÜST ÇENE ────→ Sol
        18 17 16 15 14 13 12 11 │ 21 22 23 24 25 26 27 28
        ─────────────────────────┼─────────────────────────
        48 47 46 45 44 43 42 41 │ 31 32 33 34 35 36 37 38
        Sağ ←──── ALT ÇENE ────→ Sol

    Bolton analizi yalnızca 1. molar–1. molar arası dişleri kullanır
    (FDI 11-16, 21-26, 31-36, 41-46). 2. ve 3. molarlar (17-18, 27-28,
    37-38, 47-48) gri/devre dışıdır.
"""
# UI STYLE UPDATE — Measurement Table Styling

from typing import Optional, Dict, List
import numpy as np
import pandas as pd

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QGroupBox, QHeaderView,
    QMessageBox, QAbstractItemView, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QBrush

from core.bolton_logic import (
    TOOTH_NAMES, MAXILLARY_ANTERIOR, MANDIBULAR_ANTERIOR,
    MAXILLARY_OVERALL, MANDIBULAR_OVERALL, BOLTON_REF,
    analyze_anterior, analyze_overall, BoltonResult
)
from core.measurements import euclidean_distance_3d, validate_measurement


# ──────────────────────────────────────────────────
# FDI Izgara Düzeni — Anatomik Sıralama
# ──────────────────────────────────────────────────
# Her satır karşıdan bakışta sağdan sola sıralıdır.

# Üst çene sağ çeyrek (Q1): 18→11
UPPER_RIGHT = [18, 17, 16, 15, 14, 13, 12, 11]
# Üst çene sol çeyrek (Q2): 21→28
UPPER_LEFT = [21, 22, 23, 24, 25, 26, 27, 28]
# Alt çene sağ çeyrek (Q4): 48→41
LOWER_RIGHT = [48, 47, 46, 45, 44, 43, 42, 41]
# Alt çene sol çeyrek (Q3): 31→38
LOWER_LEFT = [31, 32, 33, 34, 35, 36, 37, 38]

# Bolton analizinde kullanılan dişler
BOLTON_TEETH = set(MAXILLARY_OVERALL + MANDIBULAR_OVERALL)

# Ölçüm sırası — klinik iş akışına uygun: üst sağdan başla, alt sağda bitir
MEASUREMENT_ORDER = (
    MAXILLARY_OVERALL +   # 16,15,14,13,12,11,21,22,23,24,25,26
    MANDIBULAR_OVERALL    # 46,45,44,43,42,41,31,32,33,34,35,36
)

# Diş adlarını genişlet: 2. ve 3. molarlar da dahil
TOOTH_NAMES_EXTENDED = {
    **TOOTH_NAMES,
    17: "Üst Sağ 2. Molar",
    18: "Üst Sağ 3. Molar",
    27: "Üst Sol 2. Molar",
    28: "Üst Sol 3. Molar",
    37: "Alt Sol 2. Molar",
    38: "Alt Sol 3. Molar",
    47: "Alt Sağ 2. Molar",
    48: "Alt Sağ 3. Molar",
}


# ──────────────────────────────────────────────────
# BUTON RENKLERİ
# ──────────────────────────────────────────────────

# UI STYLE UPDATE — Premium Tooth Button Palette
_BTN_BASE = """
    QPushButton {{
        background-color: {bg};
        color: {fg};
        border: 1px solid {border};
        border-radius: 8px;
        font-size: {fs}px;
        font-weight: 700;
        min-width: {w}px;
        min-height: {h}px;
        padding: 0;
    }}
    QPushButton:hover {{
        background-color: {bg_hover};
        border-color: {border_hover};
    }}
"""

STYLE_DISABLED = _BTN_BASE.format(
    bg="#0F172A", fg="#334155", border="rgba(255,255,255,0.03)",
    bg_hover="#0F172A", border_hover="rgba(255,255,255,0.03)",
    fs="{fs}", w="{w}", h="{h}"
)

STYLE_NORMAL = _BTN_BASE.format(
    bg="#1E293B", fg="#94A3B8", border="rgba(255,255,255,0.08)",
    bg_hover="#334155", border_hover="#3B82F6",
    fs="{fs}", w="{w}", h="{h}"
)

STYLE_ACTIVE = _BTN_BASE.format(
    bg="rgba(59,130,246,0.15)", fg="#3B82F6", border="#3B82F6",
    bg_hover="rgba(59,130,246,0.25)", border_hover="#60A5FA",
    fs="{fs}", w="{w}", h="{h}"
)

STYLE_DONE = _BTN_BASE.format(
    bg="rgba(34,197,94,0.1)", fg="#4ADE80", border="rgba(34,197,94,0.3)",
    bg_hover="rgba(34,197,94,0.2)", border_hover="#22C55E",
    fs="{fs}", w="{w}", h="{h}"
)

STYLE_MISSING = _BTN_BASE.format(
    bg="rgba(239,68,68,0.1)", fg="#F87171", border="rgba(239,68,68,0.3)",
    bg_hover="rgba(239,68,68,0.2)", border_hover="#EF4444",
    fs="{fs}", w="{w}", h="{h}"
)

STYLE_UNMEASURED = STYLE_NORMAL
STYLE_MEASURED = STYLE_DONE


def _style(template: str, fs: int = 11, w: int = 32, h: int = 28) -> str:
    """Stil şablonunu boyut değerleriyle doldurur."""
    return (
        template
        .replace("{fs}", str(fs))
        .replace("{w}", str(w))
        .replace("{h}", str(h))
    )


class MeasurementPanel(QWidget):
    """
    Ölçüm kontrol paneli: FDI buton ızgarası + tablo + Bolton özeti.

    İş Akışı:
        1. Kullanıcı ızgaradan bir diş butonuna tıklar → ölçüm başlar
        2. Mesh üzerinde mezial ve distal noktaları tıklar
        3. Mesafe hesaplanır → tabloya eklenir
        4. Otomatik olarak bir sonraki ölçülmemiş dişe geçer

    Sinyaller:
        picking_requested: Nokta seçim modunu başlat (jaw_type).
        tooth_selected: Diş seçildi bilgisi (fdi, jaw_type).
        measurement_complete: Tüm Bolton dişleri ölçüldü.
    """

    # Sinyaller
    tooth_selected = Signal(int, str)
    picking_requested = Signal(str)
    measurement_complete = Signal()
    
    # 3D çizim komutları: MainWindow üzerinden Viewer'a aktarılır
    draw_marker_requested = Signal(object, str, str, str) # point, color, label, name
    draw_line_requested = Signal(object, object, str, str) # pa, pb, label, color
    picking_finished = Signal(str) # jaw_type

    # Tablo sütunları
    TABLE_COLUMNS = ["FDI", "Diş Adı", "Çene", "Genişlik (mm)", "Durum"]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Veri katmanı
        self.df = pd.DataFrame(columns=[
            "tooth_fdi", "jaw", "mesial_xyz", "distal_xyz", "width_mm"
        ])

        # Aktif ölçüm durumu
        self._active_fdi: Optional[int] = None
        self._active_jaw: Optional[str] = None
        
        self._picking_active: bool = False
        
        # Manuel nokta geçiş durumları
        self._current_step: str = "" # "mesial" veya "distal"
        self._temp_mesial: Optional[np.ndarray] = None
        self._temp_distal: Optional[np.ndarray] = None
        
        # Gerçek kaydedilen noktalar
        self._mesial_point: Optional[np.ndarray] = None
        self._distal_point: Optional[np.ndarray] = None

        # Buton referansları {fdi: QPushButton}
        self._tooth_buttons: Dict[int, QPushButton] = {}

        self._init_ui()

    # ══════════════════════════════════════════════
    # ARAYÜZ OLUŞTURMA
    # ══════════════════════════════════════════════

    def _init_ui(self) -> None:
        self.setMinimumWidth(360)
        self.setMaximumWidth(520)
        # UI STYLE UPDATE — measurement panel global stylesheet
        self.setStyleSheet("""
            QWidget {
                background-color: #0F1219;
                color: #CBD5E1;
                font-size: 13px;
            }
            QGroupBox {
                background-color: #121826;
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 12px;
                margin-top: 20px;
                padding-top: 10px;
                font-size: 11px;
                font-weight: 700;
                color: #64748B;
                letter-spacing: 1px;
                text-transform: uppercase;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 0 8px;
                color: #3B82F6;
            }
            QTableWidget {
                background-color: #0F172A;
                alternate-background-color: #121826;
                color: #E2E8F0;
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 10px;
                gridline-color: rgba(255,255,255,0.04);
                selection-background-color: rgba(59,130,246,0.2);
                selection-color: #F1F5F9;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #94A3B8;
                border: none;
                border-bottom: 1px solid rgba(255,255,255,0.08);
                padding: 8px 12px;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ── BAŞLIK ──
        title = QLabel("📏 Ölçüm Paneli")
        title.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("""
            QLabel {
                color: #EDF2F4;
                background-color: #3A3D5C;
                padding: 8px;
                border-radius: 6px;
            }
        """)
        main_layout.addWidget(title)

        # ── FDI DİŞ IZGARASI ──
        grid_group = QGroupBox("Diş Haritası — Tıklayarak Seçin")
        grid_group.setStyleSheet(self._group_style())
        grid_layout = QVBoxLayout(grid_group)
        grid_layout.setSpacing(2)

        # Üst çene etiketi
        lbl_upper = QLabel("⬆ Üst Çene (Maksilla)")
        lbl_upper.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_upper.setStyleSheet("color: #2A7F8F; font-weight: bold; font-size: 10px; padding: 2px;")
        grid_layout.addWidget(lbl_upper)

        # Üst çene buton satırı: [18..11 | 21..28]
        upper_row = QHBoxLayout()
        upper_row.setSpacing(2)
        for fdi in UPPER_RIGHT:
            btn = self._create_tooth_button(fdi)
            upper_row.addWidget(btn)
        # Orta çizgi ayırıcı
        sep = QLabel("│")
        sep.setStyleSheet("color: #3A3D5C; font-size: 14px; font-weight: bold;")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep.setFixedWidth(12)
        upper_row.addWidget(sep)
        for fdi in UPPER_LEFT:
            btn = self._create_tooth_button(fdi)
            upper_row.addWidget(btn)
        grid_layout.addLayout(upper_row)

        # Yatay ayırıcı çizgi
        line = QLabel("─" * 40)
        line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line.setStyleSheet("color: #3A3D5C; font-size: 8px; padding: 0;")
        grid_layout.addWidget(line)

        # Alt çene buton satırı: [48..41 | 31..38]
        lower_row = QHBoxLayout()
        lower_row.setSpacing(2)
        for fdi in LOWER_RIGHT:
            btn = self._create_tooth_button(fdi)
            lower_row.addWidget(btn)
        sep2 = QLabel("│")
        sep2.setStyleSheet("color: #3A3D5C; font-size: 14px; font-weight: bold;")
        sep2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep2.setFixedWidth(12)
        lower_row.addWidget(sep2)
        for fdi in LOWER_LEFT:
            btn = self._create_tooth_button(fdi)
            lower_row.addWidget(btn)
        grid_layout.addLayout(lower_row)

        # Alt çene etiketi
        lbl_lower = QLabel("⬇ Alt Çene (Mandibula)")
        lbl_lower.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_lower.setStyleSheet("color: #8B5A2B; font-weight: bold; font-size: 10px; padding: 2px;")
        grid_layout.addWidget(lbl_lower)

        # İlerleme göstergesi
        self.lbl_progress = QLabel("0 / 24 diş ölçüldü")
        self.lbl_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_progress.setStyleSheet("""
            QLabel {
                color: #8D99AE;
                font-size: 10px;
                padding: 2px;
            }
        """)
        grid_layout.addWidget(self.lbl_progress)

        main_layout.addWidget(grid_group)

        # ── DURUM + İPTAL ──
        status_row = QHBoxLayout()
        self.status_label = QLabel("Diş haritasından ölçülecek dişe tıklayın.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #FFD166;
                background-color: #2B2D42;
                padding: 8px;
                border-radius: 4px;
                font-size: 11px;
            }
        """)
        status_row.addWidget(self.status_label, 1)

        # Manuel Geçiş Butonu (Mesial -> Distal -> Kaydet)
        self.btn_next_step = QPushButton("Onayla")
        self.btn_next_step.setFixedSize(130, 36)
        self.btn_next_step.setEnabled(False)
        self.btn_next_step.setVisible(False)
        self.btn_next_step.setStyleSheet("""
            QPushButton {
                background-color: #06D6A0;
                color: #1B3A2F;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #08F6B8; }
            QPushButton:disabled {
                background-color: #2A3A3A;
                color: #555;
            }
        """)
        self.btn_next_step.clicked.connect(self._on_next_step_clicked)
        status_row.addWidget(self.btn_next_step)

        self.btn_cancel = QPushButton("✕")
        self.btn_cancel.setFixedSize(36, 36)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Aktif ölçümü iptal et")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #E63946;
                color: #FFF;
                border: none;
                border-radius: 18px;
                font-weight: bold;
                font-size: 14px;
                min-width: 36px;
            }
            QPushButton:hover { background-color: #C5303B; }
            QPushButton:disabled {
                background-color: #3A2A2A;
                color: #555;
            }
        """)
        self.btn_cancel.clicked.connect(self._cancel_measurement)
        status_row.addWidget(self.btn_cancel)
        main_layout.addLayout(status_row)

        # ── ÖLÇÜM TABLOSU ──
        table_group = QGroupBox("Ölçüm Sonuçları")
        table_group.setStyleSheet(self._group_style())
        table_layout = QVBoxLayout(table_group)

        self.table = QTableWidget(0, len(self.TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1B1B2F;
                color: #E8E8E8;
                gridline-color: #3A3D5C;
                border: none;
                font-size: 11px;
            }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background-color: #2A5F8F; }
            QHeaderView::section {
                background-color: #162447;
                color: #8D99AE;
                padding: 4px;
                border: 1px solid #3A3D5C;
                font-weight: bold;
                font-size: 10px;
            }
            QTableWidget::item:alternate { background-color: #22223B; }
        """)
        table_layout.addWidget(self.table)

        self.btn_delete = QPushButton("🗑 Seçili Ölçümü Sil")
        self.btn_delete.setObjectName("btn_delete_measurement")
        self.btn_delete.setStyleSheet("""
            QPushButton#btn_delete_measurement {
                background-color: #4A1942;
                color: #E8E8E8;
                border: 1px solid #6B2D5B;
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
            }
            QPushButton#btn_delete_measurement:hover { background-color: #6B2D5B; }
        """)
        self.btn_delete.clicked.connect(self._delete_selected)
        table_layout.addWidget(self.btn_delete)

        main_layout.addWidget(table_group, 1)

        # ══════════════════════════════════════════════
        # BOLTON KLİNİK ÖZET PANELİ
        # ══════════════════════════════════════════════
        bolton_group = QGroupBox("Bolton Analizi")
        bolton_group.setStyleSheet(self._group_style())
        bolton_layout = QVBoxLayout(bolton_group)
        bolton_layout.setSpacing(6)

        # ── ANTERIOR ANALİZ KARTI (3-3) ──
        self.card_anterior = QGroupBox("Anterior Oran (Kanin–Kanin, 3-3)")
        self.card_anterior.setStyleSheet(self._analysis_card_style("#3A3D5C"))
        ant_layout = QVBoxLayout(self.card_anterior)
        ant_layout.setSpacing(3)
        ant_layout.setContentsMargins(8, 14, 8, 8)

        # Anterior — ark toplamları satırı
        ant_sums = QHBoxLayout()
        self.lbl_ant_max_sum = QLabel("Üst Σ: —")
        self.lbl_ant_max_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
        self.lbl_ant_mand_sum = QLabel("Alt Σ: —")
        self.lbl_ant_mand_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
        ant_sums.addWidget(self.lbl_ant_max_sum)
        ant_sums.addWidget(self.lbl_ant_mand_sum)
        ant_layout.addLayout(ant_sums)

        # Anterior — oran & ideal karşılaştırma
        self.lbl_ant_ratio = QLabel("Oran: — %   (İdeal: 77.2%)")
        # UI STYLE UPDATE — bolton ratio labels
        self.lbl_ant_ratio.setStyleSheet("""
            QLabel {
                color: #F1F5F9;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: -0.5px;
            }
        """)
        ant_layout.addWidget(self.lbl_ant_ratio)

        # Anterior — mm uyumsuzluk
        self.lbl_ant_disc = QLabel("")
        self.lbl_ant_disc.setWordWrap(True)
        self.lbl_ant_disc.setStyleSheet("color: #8D99AE; font-size: 11px;")
        self.lbl_ant_disc.setVisible(False)
        ant_layout.addWidget(self.lbl_ant_disc)

        # Anterior — ilerleme
        self.lbl_ant_progress = QLabel("0/12 diş")
        self.lbl_ant_progress.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_ant_progress.setStyleSheet("color: #6C6F93; font-size: 9px;")
        ant_layout.addWidget(self.lbl_ant_progress)

        bolton_layout.addWidget(self.card_anterior)

        # ── OVERALL ANALİZ KARTI (6-6) ──
        self.card_overall = QGroupBox("Overall Oran (1. Molar–1. Molar, 6-6)")
        self.card_overall.setStyleSheet(self._analysis_card_style("#3A3D5C"))
        ovr_layout = QVBoxLayout(self.card_overall)
        ovr_layout.setSpacing(3)
        ovr_layout.setContentsMargins(8, 14, 8, 8)

        # Overall — ark toplamları satırı
        ovr_sums = QHBoxLayout()
        self.lbl_ovr_max_sum = QLabel("Üst Σ: —")
        self.lbl_ovr_max_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
        self.lbl_ovr_mand_sum = QLabel("Alt Σ: —")
        self.lbl_ovr_mand_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
        ovr_sums.addWidget(self.lbl_ovr_max_sum)
        ovr_sums.addWidget(self.lbl_ovr_mand_sum)
        ovr_layout.addLayout(ovr_sums)

        # Overall — oran & ideal karşılaştırma
        self.lbl_ovr_ratio = QLabel("Oran: — %   (İdeal: 91.3%)")
        self.lbl_ovr_ratio.setStyleSheet("""
            QLabel {
                color: #F1F5F9;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: -0.5px;
            }
        """)
        ovr_layout.addWidget(self.lbl_ovr_ratio)

        # Overall — mm uyumsuzluk
        self.lbl_ovr_disc = QLabel("")
        self.lbl_ovr_disc.setWordWrap(True)
        self.lbl_ovr_disc.setStyleSheet("color: #8D99AE; font-size: 11px;")
        self.lbl_ovr_disc.setVisible(False)
        ovr_layout.addWidget(self.lbl_ovr_disc)

        # Overall — ilerleme
        self.lbl_ovr_progress = QLabel("0/24 diş")
        self.lbl_ovr_progress.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_ovr_progress.setStyleSheet("color: #6C6F93; font-size: 9px;")
        ovr_layout.addWidget(self.lbl_ovr_progress)

        bolton_layout.addWidget(self.card_overall)

        # ── KLİNİK YORUM ──
        self.lbl_interpretation = QLabel("")
        self.lbl_interpretation.setWordWrap(True)
        self.lbl_interpretation.setStyleSheet("""
            QLabel {
                color: #FFD166;
                background-color: #2B2D42;
                padding: 8px;
                border-radius: 4px;
                font-size: 11px;
            }
        """)
        self.lbl_interpretation.setVisible(False)
        bolton_layout.addWidget(self.lbl_interpretation)

        main_layout.addWidget(bolton_group)

    # ──────────────────────────────────────────────
    # DİŞ BUTON FABRİKASI
    # ──────────────────────────────────────────────

    def _create_tooth_button(self, fdi: int) -> QPushButton:
        """
        Tek bir FDI diş butonu oluşturur.

        Args:
            fdi: FDI diş numarası (11–48).

        Returns:
            QPushButton: Konfigüre edilmiş ve sinyal bağlanmış buton.
        """
        btn = QPushButton(str(fdi))
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        is_bolton = fdi in BOLTON_TEETH
        tooth_name = TOOTH_NAMES_EXTENDED.get(fdi, f"Diş {fdi}")
        btn.setToolTip(f"{fdi} — {tooth_name}")

        if is_bolton:
            btn.setStyleSheet(_style(STYLE_UNMEASURED))
            btn.clicked.connect(lambda checked, f=fdi: self._on_tooth_clicked(f))
        else:
            # 2./3. molarlar Bolton analizinde kullanılmaz
            btn.setStyleSheet(_style(STYLE_DISABLED))
            btn.setEnabled(False)
            btn.setToolTip(f"{fdi} — {tooth_name}\n(Bolton analizinde kullanılmaz)")

        self._tooth_buttons[fdi] = btn
        return btn

    def _update_button_states(self) -> None:
        """
        Tüm butonların görsel durumunu günceller:
        - Ölçülmüş → yeşil
        - Ölçülmemiş → mavi
        - Aktif → sarı
        - Bolton dışı → gri (değişmez)
        """
        measured_fdi = set(self.df["tooth_fdi"].values)

        for fdi, btn in self._tooth_buttons.items():
            if fdi not in BOLTON_TEETH:
                continue  # Devre dışı butonlara dokunma

            if fdi == self._active_fdi:
                btn.setStyleSheet(_style(STYLE_ACTIVE))
            elif fdi in measured_fdi:
                # Ölçülmüş: numaranın yanına genişliği göster
                width = float(self.df[self.df["tooth_fdi"] == fdi].iloc[0]["width_mm"])
                btn.setText(f"{fdi}\n{width:.1f}")
                btn.setStyleSheet(_style(STYLE_MEASURED))
            else:
                btn.setText(str(fdi))
                btn.setStyleSheet(_style(STYLE_UNMEASURED))

    # ──────────────────────────────────────────────
    # DİŞ TIKLAMA → ÖLÇÜM BAŞLAT
    # ──────────────────────────────────────────────

    def _on_tooth_clicked(self, fdi: int) -> None:
        """
        Diş butonuna tıklandığında ölçüm modunu başlatır.

        Klinik İş Akışı:
            Ortodontist ızgarada bir dişe tıklar → picking modu açılır →
            mesh üzerinde mezial/distal noktaları seçer → ölçüm kaydedilir →
            otomatik olarak sonraki dişe geçilir.

        Args:
            fdi: Tıklanan dişin FDI numarası.
        """
        # Zaten aktif bir ölçüm varsa iptal et
        if self._picking_active:
            self._cancel_measurement()

        # Çeneyi belirle
        jaw = "maxillary" if fdi < 30 else "mandibular"

        # Daha önce ölçülmüş mü? → üzerine yaz (uyarı göster)
        if fdi in self.df["tooth_fdi"].values:
            reply = QMessageBox.question(
                self,
                "Tekrar Ölçüm",
                f"Diş {fdi} ({TOOTH_NAMES_EXTENDED.get(fdi, '')}) daha önce ölçülmüş.\n"
                "Yeniden ölçmek ister misiniz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.df = self.df[self.df["tooth_fdi"] != fdi].reset_index(drop=True)

        # Aktif ölçüm durumunu ayarla
        self._active_fdi = fdi
        self._active_jaw = jaw
        
        self._picking_active = True
        self._current_step = "mesial"
        self._temp_mesial = None
        self._temp_distal = None
        self._mesial_point = None
        self._distal_point = None

        # UI güncelle
        tooth_name = TOOTH_NAMES_EXTENDED.get(fdi, f"Diş {fdi}")
        self.status_label.setText(
            f"🔵 {fdi} — {tooth_name}\n"
            f"→ 1/2: MEZİAL noktayı tıklayın.\n(Yanlış tıklarsanız tekrar tıklayarak yerini değiştirebilirsiniz)"
        )
        self.status_label.setStyleSheet("""
            QLabel {
                color: #06D6A0;
                background-color: #1B3A2F;
                padding: 8px;
                border-radius: 4px;
                font-size: 11px;
                border: 1px solid #06D6A0;
            }
        """)
        self.btn_cancel.setEnabled(True)
        self.btn_next_step.setVisible(True)
        self.btn_next_step.setEnabled(False)
        self.btn_next_step.setText("Distale Geç ➔")
        
        self._update_button_states()

        # Picking sinyali gönder
        self.picking_requested.emit(jaw)
        self.tooth_selected.emit(fdi, jaw)

    def _cancel_measurement(self) -> None:
        """Aktif ölçümü iptal eder ve normal moda döner."""
        if self._picking_active and self._active_jaw:
            self.picking_finished.emit(self._active_jaw)
            
        self._active_fdi = None
        self._active_jaw = None
        self._picking_active = False
        self._current_step = ""

        self.status_label.setText("Diş haritasından ölçülecek dişe tıklayın.")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #FFD166;
                background-color: #2B2D42;
                padding: 8px;
                border-radius: 4px;
                font-size: 11px;
            }
        """)
        self.btn_cancel.setEnabled(False)
        self.btn_next_step.setVisible(False)
        self._update_button_states()

    # ──────────────────────────────────────────────
    # NOKTA SEÇİM İŞLEME (MESIAL → DISTAL)
    # ──────────────────────────────────────────────

    def receive_picked_point(self, point: np.ndarray) -> None:
        """
        3D görüntüleyiciden seçilen noktayı alır (Geçici olarak).
        Kullanıcı butona basana kadar noktalar sürekli değiştirilebilir.
        """
        if not self._picking_active or self._active_fdi is None:
            return

        pt = np.asarray(point, dtype=np.float64)

        if self._current_step == "mesial":
            self._temp_mesial = pt
            self.draw_marker_requested.emit(pt, "#06D6A0", "M", "temp_mesial")
            self.btn_next_step.setEnabled(True)
            self.btn_next_step.setText("Distale Geç ➔")
            tooth_name = TOOTH_NAMES_EXTENDED.get(self._active_fdi, "")
            self.status_label.setText(
                f"🔵 {self._active_fdi} — {tooth_name}\n"
                f"✓ Nokta yerleştirildi. Düzeltmek için tekrar tıklayın\nya da 'Distale Geç' butonuna basın."
            )

        elif self._current_step == "distal":
            # Mezial noktası ile mesafe hesapla
            dist = euclidean_distance_3d(self._mesial_point, pt)
            
            # Eğer yanlışlıkla mesialin aynısına tıkladıysa (kayma hatası)
            if dist < 0.2:
                print(f"[MeasurementPanel] Ghost click ignored (width: {dist:.3f} mm)", flush=True)
                return
                
            self._temp_distal = pt
            self.draw_marker_requested.emit(pt, "#FFD166", "D", "temp_distal")
            self.draw_line_requested.emit(self._mesial_point, pt, f"{dist:.2f} mm", "#06D6A0")
            
            self.btn_next_step.setEnabled(True)
            self.btn_next_step.setText("Ölçümü Kaydet ✓")
            tooth_name = TOOTH_NAMES_EXTENDED.get(self._active_fdi, "")
            self.status_label.setText(
                f"🔵 {self._active_fdi} — {tooth_name}\n"
                f"✓ Distal nokta yerleştirildi. Mesafe: {dist:.2f} mm\nDüzeltmek için tıklayın ya da 'Ölçümü Kaydet'e basın."
            )

    def _on_next_step_clicked(self) -> None:
        """
        Kullanıcı butona basarak mevcut adımı onaylar.
        Mesial -> Distal'e geçer.
        Distal -> Kayıt işlemini tamamlar.
        """
        if not self._picking_active:
            return

        if self._current_step == "mesial":
            if self._temp_mesial is None:
                return
            # Mesial'ı kalıcılaştır, Distal adımına geç
            self._mesial_point = self._temp_mesial
            self._current_step = "distal"
            self._temp_distal = None
            
            # Mesial butonuna kalıcı işaret (temp ismini point_{idx} yapıtırmak için sinyal de atılabilir ama şimdilik gerek yok)
            
            self.btn_next_step.setEnabled(False)
            self.btn_next_step.setText("Distal Seçiliyor...")
            
            tooth_name = TOOTH_NAMES_EXTENDED.get(self._active_fdi, "")
            self.status_label.setText(
                f"🔵 {self._active_fdi} — {tooth_name}\n"
                f"→ 2/2: DİSTAL noktayı mesh üzerinde tıklayın.\n(Yanlış tıklarsanız yeri değiştirebilirsiniz)"
            )
            
        elif self._current_step == "distal":
            if self._temp_distal is None or self._mesial_point is None:
                return
            
            # Kaydetme işlemi
            self._distal_point = self._temp_distal
            width_mm = euclidean_distance_3d(self._mesial_point, self._distal_point)

            # Klinik doğrulama
            tooth_label = f"{self._active_fdi} ({TOOTH_NAMES_EXTENDED.get(self._active_fdi, '')})"
            valid, warning_msg = validate_measurement(width_mm, tooth_label)

            # DataFrame'e kaydet
            new_row = pd.DataFrame([{
                "tooth_fdi": self._active_fdi,
                "jaw": self._active_jaw,
                "mesial_xyz": self._mesial_point.tolist(),
                "distal_xyz": self._distal_point.tolist(),
                "width_mm": round(width_mm, 2),
            }])
            self.df = pd.concat([self.df, new_row], ignore_index=True)

            # Tablo ve Bolton güncelle
            self._refresh_table()
            self._update_bolton_summary()

            # Durum mesajı
            completed_fdi = self._active_fdi
            status_msg = f"✅ Diş {completed_fdi}: {width_mm:.2f} mm ölçüldü."
            if not valid:
                status_msg += f"\n{warning_msg}"

            # Ölçüm modunu kapat
            jaw_to_disable = self._active_jaw
            self._picking_active = False
            self._active_fdi = None
            self._active_jaw = None
            self._current_step = ""
            self.btn_cancel.setEnabled(False)
            self.btn_next_step.setVisible(False)
            
            # Ekranda pick modunu kapat
            self.picking_finished.emit(jaw_to_disable)

            # Buton durumlarını güncelle
            self._update_button_states()
            self._update_progress()

            # Tamamlanma kontrolü
            if self._check_completion():
                self.status_label.setText(
                    f"{status_msg}\n\n🎉 Tüm 24 diş ölçümü tamamlandı!"
                )
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #06D6A0;
                        background-color: #0A3020;
                        padding: 8px;
                        border-radius: 4px;
                        font-size: 11px;
                        border: 2px solid #06D6A0;
                    }
                """)
                return

            # AUTO-ADVANCE: Bir sonraki ölçülmemiş dişe geç
            next_fdi = self._find_next_unmeasured(completed_fdi)
            if next_fdi is not None:
                next_name = TOOTH_NAMES_EXTENDED.get(next_fdi, "")
                self.status_label.setText(
                    f"{status_msg}\n"
                    f"→ Sonraki: {next_fdi} ({next_name})"
                )
                # Kısa gecikmeyle auto-advance
                QTimer.singleShot(600, lambda: self._auto_advance(next_fdi))
            else:
                self.status_label.setText(status_msg)

    def _find_next_unmeasured(self, current_fdi: int) -> Optional[int]:
        """
        Mevcut dişten sonra ilk ölçülmemiş Bolton dişini bulur.
        Klinik sıralamayı takip eder (MEASUREMENT_ORDER).

        Klinik Not:
            Auto-advance, ortodontistin ölçüm akışını kesmeden
            arklar boyunca ilerlemesini sağlar.

        Args:
            current_fdi: Son ölçülen dişin FDI numarası.

        Returns:
            Optional[int]: Sonraki ölçülmemiş dişin FDI numarası, veya None.
        """
        measured = set(self.df["tooth_fdi"].values)

        # Mevcut dişin sıradaki pozisyonunu bul
        try:
            idx = MEASUREMENT_ORDER.index(current_fdi)
        except ValueError:
            idx = -1

        # Sırada kalan dişlerden ilk ölçülmemiş olanı bul
        order = list(MEASUREMENT_ORDER)
        candidates = order[idx + 1:] + order[:idx + 1]  # Wrap-around

        for fdi in candidates:
            if fdi not in measured:
                return fdi

        return None  # Hepsi ölçülmüş

    def _auto_advance(self, next_fdi: int) -> None:
        """
        Otomatik olarak sonraki dişin ölçümünü başlatır.
        Picking zaten kapalıysa (kullanıcı cancel etmemişse) başlatır.

        Args:
            next_fdi: Otomatik başlatılacak dişin FDI numarası.
        """
        # Eğer bu arada kullanıcı başka bir diş seçtiyse veya cancel ettiyse iptal
        if self._picking_active:
            return
        self._on_tooth_clicked(next_fdi)

    @property
    def is_picking_active(self) -> bool:
        """Nokta seçim modunun aktif olup olmadığını döndürür."""
        return self._picking_active

    # ──────────────────────────────────────────────
    # TABLO GÜNCELLEME
    # ──────────────────────────────────────────────

    def _refresh_table(self) -> None:
        """DataFrame'den QTableWidget'ı yeniden doldurur."""
        self.table.setRowCount(0)
        if self.df.empty:
            return

        sort_order = {fdi: i for i, fdi in enumerate(MEASUREMENT_ORDER)}
        sorted_df = self.df.copy()
        sorted_df["_sort_key"] = sorted_df["tooth_fdi"].map(
            lambda x: sort_order.get(x, 999)
        )
        sorted_df = sorted_df.sort_values("_sort_key").drop(columns=["_sort_key"])

        for _, row in sorted_df.iterrows():
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)

            fdi = int(row["tooth_fdi"])
            jaw = row["jaw"]
            width = row["width_mm"]
            tooth_name = TOOTH_NAMES_EXTENDED.get(fdi, f"Diş {fdi}")
            valid, _ = validate_measurement(width, str(fdi))

            item_fdi = QTableWidgetItem(str(fdi))
            item_fdi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_fdi.setData(Qt.ItemDataRole.UserRole, fdi)

            item_name = QTableWidgetItem(tooth_name)

            jaw_display = "Üst" if jaw == "maxillary" else "Alt"
            item_jaw = QTableWidgetItem(jaw_display)
            item_jaw.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_width = QTableWidgetItem(f"{width:.2f}")
            item_width.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not valid:
                item_width.setForeground(QBrush(QColor("#E63946")))

            item_status = QTableWidgetItem("✅" if valid else "⚠")
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table.setItem(row_idx, 0, item_fdi)
            self.table.setItem(row_idx, 1, item_name)
            self.table.setItem(row_idx, 2, item_jaw)
            self.table.setItem(row_idx, 3, item_width)
            self.table.setItem(row_idx, 4, item_status)

    def _delete_selected(self) -> None:
        """Tabloda seçili satırı siler ve butonları günceller."""
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.information(self, "Sil", "Silmek için bir satır seçin.")
            return

        row = selected[0].row()
        fdi_item = self.table.item(row, 0)
        if fdi_item:
            fdi = fdi_item.data(Qt.ItemDataRole.UserRole)
            self.df = self.df[self.df["tooth_fdi"] != fdi].reset_index(drop=True)
            self._refresh_table()
            self._update_bolton_summary()
            self._update_button_states()
            self._update_progress()

    # ──────────────────────────────────────────────
    # İLERLEME TAKİBİ
    # ──────────────────────────────────────────────

    def _update_progress(self) -> None:
        """İlerleme etiketini günceller."""
        measured = len(set(self.df["tooth_fdi"].values) & BOLTON_TEETH)
        total = len(BOLTON_TEETH)
        self.lbl_progress.setText(f"{measured} / {total} diş ölçüldü")

        if measured == total:
            self.lbl_progress.setStyleSheet("""
                QLabel { color: #06D6A0; font-size: 10px; padding: 2px; font-weight: bold; }
            """)
        else:
            self.lbl_progress.setStyleSheet("""
                QLabel { color: #8D99AE; font-size: 10px; padding: 2px; }
            """)

    def _check_completion(self) -> bool:
        """Tüm Bolton dişleri ölçüldü mü kontrol eder."""
        measurements = self._get_measurements_dict()
        if BOLTON_TEETH.issubset(measurements.keys()):
            self.measurement_complete.emit()
            return True
        return False

    # ──────────────────────────────────────────────
    # BOLTON ORAN ÖZETİ
    # ──────────────────────────────────────────────

    def _get_measurements_dict(self) -> Dict[int, float]:
        result = {}
        for _, row in self.df.iterrows():
            result[int(row["tooth_fdi"])] = float(row["width_mm"])
        return result

    def _update_bolton_summary(self) -> None:
        """
        Bolton özet panelini günceller.

        Klinik Bağlam:
            Her ölçüm sonrası çağrılır. Kısmi ölçümlerde toplamları
            gösterir, tüm dişler ölçüldüğünde oran ve uyumsuzluğu
            renk kodlu olarak sunar.

            Yeşil (#06D6A0): Oran normal aralıkta — diş boyutu uyumu var.
            Kırmızı (#E63946): Oran aralık dışında — diş boyutu uyumsuzluğu var.
        """
        measurements = self._get_measurements_dict()
        interpretations = []  # Birden fazla yorumu birleştirmek için

        # ══════════════════════════════════════════
        # ANTERIOR ANALİZ (3-3: Kanin–Kanin)
        # ══════════════════════════════════════════
        ant_max_teeth = [t for t in MAXILLARY_ANTERIOR if t in measurements]
        ant_mand_teeth = [t for t in MANDIBULAR_ANTERIOR if t in measurements]
        ant_max_count = len(ant_max_teeth)
        ant_mand_count = len(ant_mand_teeth)
        ant_total = len(MAXILLARY_ANTERIOR) + len(MANDIBULAR_ANTERIOR)
        ant_done = ant_max_count + ant_mand_count

        # Kısmi toplamları her zaman göster
        ant_max_sum = sum(measurements[t] for t in ant_max_teeth)
        ant_mand_sum = sum(measurements[t] for t in ant_mand_teeth)

        self.lbl_ant_max_sum.setText(
            f"Üst Σ: {ant_max_sum:.1f} mm" if ant_max_count > 0 else "Üst Σ: —"
        )
        self.lbl_ant_mand_sum.setText(
            f"Alt Σ: {ant_mand_sum:.1f} mm" if ant_mand_count > 0 else "Alt Σ: —"
        )
        self.lbl_ant_progress.setText(
            f"{ant_done}/{ant_total} diş"
        )

        if ant_done == ant_total:
            try:
                result = analyze_anterior(measurements)
                color = "#06D6A0" if result.within_normal else "#E63946"
                status_icon = "✅" if result.within_normal else "⚠️"

                self.lbl_ant_ratio.setText(
                    f"{status_icon} Oran: %{result.ratio:.1f}   (İdeal: %{result.ideal_ratio})"
                )
                self.lbl_ant_ratio.setStyleSheet(
                    "QLabel { color: #F1F5F9; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }"
                )

                # Mm uyumsuzluk detayı
                abs_disc = abs(result.discrepancy_mm)
                if result.discrepancy_arch == "mandibular":
                    disc_text = (
                        f"Mandibüler fazlalık: {abs_disc:.1f} mm\n"
                        f"Alt arkta {abs_disc:.1f} mm diş materyali fazlası var."
                    )
                elif result.discrepancy_arch == "maxillary":
                    disc_text = (
                        f"Maksiller fazlalık: {abs_disc:.1f} mm\n"
                        f"Üst arkta {abs_disc:.1f} mm diş materyali fazlası var."
                    )
                else:
                    disc_text = "Mükemmel uyum — uyumsuzluk yok."

                self.lbl_ant_disc.setText(disc_text)
                ant_status_style = (
                    "color: #4ADE80; font-size: 11px; font-weight: 600;"
                    if result.within_normal
                    else "color: #F87171; font-size: 11px; font-weight: 600;"
                )
                self.lbl_ant_disc.setStyleSheet(ant_status_style)
                self.lbl_ant_disc.setVisible(True)

                self.card_anterior.setStyleSheet(
                    self._analysis_card_style(color)
                )
                self.lbl_ant_max_sum.setStyleSheet(f"color: {color}; font-size: 11px;")
                self.lbl_ant_mand_sum.setStyleSheet(f"color: {color}; font-size: 11px;")
                self.lbl_ant_progress.setStyleSheet(
                    f"color: {color}; font-size: 9px; font-weight: bold;"
                )

                interpretations.append(result.interpretation)
            except ValueError:
                pass
        else:
            # Henüz tamamlanmamış — gri tonlarında
            self.lbl_ant_ratio.setText("Oran: — %   (İdeal: 77.2%)")
            self.lbl_ant_ratio.setStyleSheet(
                "QLabel { color: #F1F5F9; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }"
            )
            self.lbl_ant_disc.setVisible(False)
            self.card_anterior.setStyleSheet(self._analysis_card_style("#3A3D5C"))
            self.lbl_ant_max_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
            self.lbl_ant_mand_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
            self.lbl_ant_progress.setStyleSheet("color: #6C6F93; font-size: 9px;")

        # ══════════════════════════════════════════
        # OVERALL ANALİZ (6-6: 1.Molar–1.Molar)
        # ══════════════════════════════════════════
        ovr_max_teeth = [t for t in MAXILLARY_OVERALL if t in measurements]
        ovr_mand_teeth = [t for t in MANDIBULAR_OVERALL if t in measurements]
        ovr_max_count = len(ovr_max_teeth)
        ovr_mand_count = len(ovr_mand_teeth)
        ovr_total = len(MAXILLARY_OVERALL) + len(MANDIBULAR_OVERALL)
        ovr_done = ovr_max_count + ovr_mand_count

        ovr_max_sum = sum(measurements[t] for t in ovr_max_teeth)
        ovr_mand_sum = sum(measurements[t] for t in ovr_mand_teeth)

        self.lbl_ovr_max_sum.setText(
            f"Üst Σ: {ovr_max_sum:.1f} mm" if ovr_max_count > 0 else "Üst Σ: —"
        )
        self.lbl_ovr_mand_sum.setText(
            f"Alt Σ: {ovr_mand_sum:.1f} mm" if ovr_mand_count > 0 else "Alt Σ: —"
        )
        self.lbl_ovr_progress.setText(
            f"{ovr_done}/{ovr_total} diş"
        )

        if ovr_done == ovr_total:
            try:
                result = analyze_overall(measurements)
                color = "#06D6A0" if result.within_normal else "#E63946"
                status_icon = "✅" if result.within_normal else "⚠️"

                self.lbl_ovr_ratio.setText(
                    f"{status_icon} Oran: %{result.ratio:.1f}   (İdeal: %{result.ideal_ratio})"
                )
                self.lbl_ovr_ratio.setStyleSheet(
                    "QLabel { color: #F1F5F9; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }"
                )

                abs_disc = abs(result.discrepancy_mm)
                if result.discrepancy_arch == "mandibular":
                    disc_text = (
                        f"Mandibüler fazlalık: {abs_disc:.1f} mm\n"
                        f"Alt arkta {abs_disc:.1f} mm diş materyali fazlası var."
                    )
                elif result.discrepancy_arch == "maxillary":
                    disc_text = (
                        f"Maksiller fazlalık: {abs_disc:.1f} mm\n"
                        f"Üst arkta {abs_disc:.1f} mm diş materyali fazlası var."
                    )
                else:
                    disc_text = "Mükemmel uyum — uyumsuzluk yok."

                self.lbl_ovr_disc.setText(disc_text)
                ovr_status_style = (
                    "color: #4ADE80; font-size: 11px; font-weight: 600;"
                    if result.within_normal
                    else "color: #F87171; font-size: 11px; font-weight: 600;"
                )
                self.lbl_ovr_disc.setStyleSheet(ovr_status_style)
                self.lbl_ovr_disc.setVisible(True)

                self.card_overall.setStyleSheet(
                    self._analysis_card_style(color)
                )
                self.lbl_ovr_max_sum.setStyleSheet(f"color: {color}; font-size: 11px;")
                self.lbl_ovr_mand_sum.setStyleSheet(f"color: {color}; font-size: 11px;")
                self.lbl_ovr_progress.setStyleSheet(
                    f"color: {color}; font-size: 9px; font-weight: bold;"
                )

                interpretations.append(result.interpretation)
            except ValueError:
                pass
        else:
            self.lbl_ovr_ratio.setText("Oran: — %   (İdeal: 91.3%)")
            self.lbl_ovr_ratio.setStyleSheet(
                "QLabel { color: #F1F5F9; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }"
            )
            self.lbl_ovr_disc.setVisible(False)
            self.card_overall.setStyleSheet(self._analysis_card_style("#3A3D5C"))
            self.lbl_ovr_max_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
            self.lbl_ovr_mand_sum.setStyleSheet("color: #8D99AE; font-size: 11px;")
            self.lbl_ovr_progress.setStyleSheet("color: #6C6F93; font-size: 9px;")

        # ── Klinik yorum (varsa) ──
        if interpretations:
            self.lbl_interpretation.setText("\n\n".join(interpretations))
            self.lbl_interpretation.setVisible(True)
        else:
            self.lbl_interpretation.setVisible(False)

    # ──────────────────────────────────────────────
    # HARİCİ ERİŞİM
    # ──────────────────────────────────────────────

    def get_dataframe(self) -> pd.DataFrame:
        return self.df.copy()

    def clear_all(self) -> None:
        """Tüm ölçümleri temizler ve ızgarayı sıfırlar."""
        self.df = pd.DataFrame(columns=[
            "tooth_fdi", "jaw", "mesial_xyz", "distal_xyz", "width_mm"
        ])
        self._refresh_table()
        self._update_bolton_summary()
        self._cancel_measurement()
        self._update_button_states()
        self._update_progress()
        self.lbl_interpretation.setVisible(False)

    def auto_fill_measurements(self, rows: list) -> None:
        """
        AI segmentasyon sonuçlarını toplu olarak tabloya yükler.

        Faz 3: Landmark finder'dan gelen ölçümleri DataFrame'e ekler
        ve tüm UI bileşenlerini günceller.

        Args:
            rows: List[dict] — her eleman:
                  {"tooth_fdi", "jaw", "mesial_xyz", "distal_xyz", "width_mm"}
        """
        import pandas as pd

        if not rows:
            return

        # Mevcut verileri temizle ve yeni verileri yükle
        self.df = pd.DataFrame(rows)

        # Tüm UI bileşenlerini güncelle
        self._refresh_table()
        self._update_bolton_summary()
        self._update_button_states()
        self._update_progress()
        self._check_completion()

        # Durum mesajı
        n = len(rows)
        self.status_label.setText(
            f"🤖 AI segmentasyon: {n} diş otomatik ölçüldü.\n"
            f"Manuel düzeltme için dişe tıklayın."
        )
        self.status_label.setStyleSheet("""
            QLabel {
                color: #A78BFA;
                background-color: #2D1B4E;
                padding: 8px;
                border-radius: 4px;
                font-size: 11px;
                border: 1px solid #7B3FB8;
            }
        """)

    # ──────────────────────────────────────────────
    # YARDIMCI STİL FONKSİYONLARI
    # ──────────────────────────────────────────────

    @staticmethod
    def _group_style() -> str:
        return """
            QGroupBox {
                background-color: #10151F;
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 10px;
                margin-top: 14px;
                padding-top: 8px;
                font-size: 11px;
                font-weight: 600;
                color: #475569;
                letter-spacing: 0.8px;
                text-transform: uppercase;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 6px;
                color: #475569;
            }
        """

    @staticmethod
    def _card_style() -> str:
        return """
            QLabel {
                color: #8D99AE;
                background-color: #22223B;
                padding: 8px;
                border-radius: 4px;
                font-size: 12px;
            }
        """

    @staticmethod
    def _analysis_card_style(border_color: str = "#3A3D5C") -> str:
        """
        Analiz kartı stili — sol kenarda renk çizgisi ile sonucu vurgular.
        Yeşil = normal, Kırmızı = uyumsuzluk, Gri = henüz tamamlanmamış.
        """
        return f"""
            QGroupBox {{
                color: #CBD5E1;
                font-weight: bold;
                font-size: 10px;
                border: 1px solid {border_color};
                border-left: 4px solid {border_color};
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 14px;
                background-color: #10151F;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #64748B;
            }}
        """
