"""
ui/main_window.py — Ana Uygulama Penceresi
============================================
Faz 1–3: Pencere düzeni, STL yükleme, çift 3D görüntüleyici,
         nokta seçimi, ölçüm paneli, AI segmentasyon entegrasyonu.

Tasarım Kararı:
    Ana pencere üç panele bölünmüştür:
    - Sol: Maksilla (üst çene) 3D görüntüleyici
    - Orta: Mandibula (alt çene) 3D görüntüleyici
    - Sağ: Ölçüm paneli (diş seçici, tablo, Bolton özeti)

    Faz 3 eklentisi:
    - Araç çubuğunda "🤖 Otomatik Segmentasyon" butonu
    - Tıklayınca: preprocess → segment → landmark → auto-fill tablo
    - 3D sahnede her diş farklı renkte gösterilir
"""
# SELÇUKBOLT UI REDESIGN — Main Window

import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pyvista as pv

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QToolBar, QPushButton, QFileDialog, QStatusBar,
    QMessageBox, QLabel, QGroupBox, QSplitter, QFrame,
    QSizePolicy, QApplication, QLineEdit, QTextEdit,
    QDialog, QDialogButtonBox, QFormLayout, QStackedWidget,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QInputDialog,
    QAbstractItemView, QToolButton, QMenu, QButtonGroup, QStyle,
)
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QPoint
from PySide6.QtGui import (
    QFont, QAction, QIcon, QColor, QPalette, QDesktopServices,
    QShortcut, QKeySequence, QActionGroup,
)
from PySide6.QtCore import QUrl

from ui.viewer import MeshViewer
from ui.measurement_table import MeasurementPanel
from core.measurements import euclidean_distance_3d
from core.stl_loader import STLLoader, STLLoadError
from core.bolton_logic import (
    TOOTH_NAMES,
    MAXILLARY_OVERALL,
    MANDIBULAR_OVERALL,
    analyze_anterior,
    analyze_overall,
)
from ai.preprocessor import mesh_to_feature_tensor
from ai.segmentor import ToothSegmentor
from ai.landmark_finder import find_landmarks, landmarks_to_dataframe_rows
from reports.pdf_generator import generate_bolton_report
from reports.excel_template_export import (
    export_bolton_excel_template,
    BoltonExcelExportError,
)
from reports.export_manager import export_measurements_csv, export_analysis_json


class PdfGenerationThread(QThread):
    """PDF raporunu UI thread'i bloklamadan üretir."""

    success = Signal(str)
    failure = Signal(str)

    def __init__(self, report_kwargs: dict, parent=None):
        super().__init__(parent)
        self.report_kwargs = report_kwargs

    def run(self) -> None:
        try:
            output_path = generate_bolton_report(**self.report_kwargs)
            self.success.emit(output_path)
        except Exception as exc:
            self.failure.emit(str(exc))


class MainWindow(QMainWindow):
    """
    Bolton Analyzer ana penceresi.

    Bileşenler:
        - Araç çubuğu: STL yükleme, temizleme, hakkında
        - Sol panel: Maksilla 3D görüntüleyici
        - Orta panel: Mandibula 3D görüntüleyici
        - Sağ panel: Ölçüm kontrol & sonuç paneli
        - Durum çubuğu: Anlık mesajlar
    """

    def __init__(self):
        super().__init__()

        # Pencere ayarları
        self.setWindowTitle("SelçukBolt")
        self.setMinimumSize(1400, 750)
        self.resize(1700, 900)

        # Durum değişkenleri
        self.maxilla_mesh = None
        self.mandible_mesh = None

        # Faz 3: AI segmentor (lazy init)
        self._segmentor = None

        # Faz 4: STL dosya adları (rapor için)
        self._maxilla_filename = ""
        self._mandible_filename = ""
        self._maxilla_path = ""
        self._mandible_path = ""
        self._session_path = Path(__file__).resolve().parent.parent / "session_data" / "autosave_session.json"
        self._restoring_session = False

        # Rehberli ölçüm ve odaklı iş akışı durumları
        self.guided_sequences = {
            "maxillary": list(MAXILLARY_OVERALL),
            "mandibular": list(MANDIBULAR_OVERALL),
        }
        self.guided_sequence: list[int] = []
        self.guided_index = -1
        self.guided_step = ""
        self.guided_active = False
        self.guided_jaw: Optional[str] = None
        self.guided_mesial_point: Optional[np.ndarray] = None
        self.guided_distal_point: Optional[np.ndarray] = None
        self.guided_pending_point: Optional[np.ndarray] = None
        self.completed_teeth = {"maxillary": set(), "mandibular": set()}
        self.missing_teeth = {"maxillary": set(), "mandibular": set()}
        self.arch_lengths = {"maxillary": None, "mandibular": None}
        self.arch_paths = {"maxillary": [], "mandibular": []}
        self.arch_mode_active = False
        self.arch_mode_jaw: Optional[str] = None
        self.arch_points: list[np.ndarray] = []
        self.report_thread: Optional[PdfGenerationThread] = None
        self.model_focus_mode = False
        self.window_fullscreen_mode = False
        self.current_view_mode = "maxillary"
        self.active_navigation_tool = "rotate"

        # Arayüzü oluştur
        self._apply_global_style()
        self._init_toolbar()
        self._init_central_widget()
        self._init_status_bar()
        self._connect_signals()
        self._init_shortcuts()
        self._show_home_page()
        self._refresh_toolbar_availability()
        QTimer.singleShot(0, self._restore_autosave_session)

        # Başlangıç mesajı
        self.statusBar().showMessage(
            "STL dosyalarini yukleyin. Sol tik ile secin, Space ile ilerleyin.",
            8000
        )

    def _init_shortcuts(self) -> None:
        """Rehberli ölçüm için hızlı klavye kısayollarını tanımlar."""
        self.shortcut_guided_return = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.shortcut_guided_return.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_guided_return.activated.connect(self._on_guided_shortcut_triggered)

        self.shortcut_guided_enter = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.shortcut_guided_enter.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_guided_enter.activated.connect(self._on_guided_shortcut_triggered)

        self.shortcut_guided_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.shortcut_guided_space.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_guided_space.activated.connect(self._on_guided_shortcut_triggered)

        self.shortcut_guided_backspace = QShortcut(QKeySequence(Qt.Key_Backspace), self)
        self.shortcut_guided_backspace.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_guided_backspace.activated.connect(self.undo_current_tooth_measurement)

        self.shortcut_guided_delete = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self.shortcut_guided_delete.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_guided_delete.activated.connect(self.undo_current_tooth_measurement)

        self.shortcut_mark_missing = QShortcut(QKeySequence(Qt.Key_N), self)
        self.shortcut_mark_missing.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_mark_missing.activated.connect(self.mark_current_tooth_missing)

        self.shortcut_toggle_fullscreen = QShortcut(QKeySequence(Qt.Key_F11), self)
        self.shortcut_toggle_fullscreen.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_toggle_fullscreen.activated.connect(self._toggle_window_fullscreen)

        self.shortcut_exit_focus = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_exit_focus.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_exit_focus.activated.connect(self._exit_fullscreen_views)

    # ──────────────────────────────────────────────
    # GLOBAL STİL
    # ──────────────────────────────────────────────

    def _apply_global_style(self) -> None:
        """Uygulamaya klinik koyu tema ve modern kontrol yüzeyi uygular."""
        # UI STYLE UPDATE — Premium "Clinical-Tech" Aesthetic
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0F1219;
                color: #E2E8F0;
            }

            QToolBar {
                background-color: #121826;
                border: none;
                border-bottom: 1px solid rgba(255,255,255,0.06);
                padding: 6px 12px;
                spacing: 4px;
            }

            QPushButton {
                background-color: #1A2234;
                color: #F8FAFC;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #242E46;
                border-color: #3B82F6;
            }
            QPushButton:pressed {
                background-color: #1E293B;
                padding-top: 11px;
                padding-bottom: 9px;
            }
            QPushButton:disabled {
                background-color: #0F172A;
                color: #475569;
                border-color: rgba(255,255,255,0.03);
            }

            QPushButton#secondaryButton {
                background-color: #121826;
                color: #94A3B8;
                border: 1px solid rgba(255,255,255,0.08);
            }
            QPushButton#secondaryButton:hover {
                background-color: #1E293B;
                color: #F8FAFC;
            }

            QPushButton#accentButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:1 #2563EB);
                color: #FFFFFF;
                border: none;
                font-weight: 700;
            }
            QPushButton#accentButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #60A5FA, stop:1 #3B82F6);
            }
            QPushButton#accentButton:pressed {
                background-color: #1D4ED8;
            }

            QPushButton#btn_clear {
                background-color: rgba(239, 68, 68, 0.1);
                color: #F87171;
                border: 1px solid rgba(239, 68, 68, 0.2);
            }
            QPushButton#btn_clear:hover {
                background-color: rgba(239, 68, 68, 0.2);
                border-color: #EF4444;
            }

            QStatusBar {
                background-color: #0A0F1D;
                color: #64748B;
                font-size: 11px;
                padding: 6px 16px;
                border-top: 1px solid rgba(255,255,255,0.04);
            }

            QLabel#app_title {
                color: #3B82F6;
                font-family: "Syne", "Inter", sans-serif;
                font-size: 15px;
                font-weight: 800;
                letter-spacing: 2px;
                text-transform: uppercase;
                margin-left: 4px;
            }

            QToolBar QToolButton {
                background-color: transparent;
                color: #94A3B8;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 6px;
                margin: 0 1px;
            }
            QToolBar QToolButton:hover {
                background-color: rgba(59, 130, 246, 0.1);
                color: #F8FAFC;
                border-color: rgba(59, 130, 246, 0.2);
            }
            QToolBar QToolButton:checked {
                background-color: rgba(59, 130, 246, 0.15);
                color: #3B82F6;
                border-color: rgba(59, 130, 246, 0.3);
            }

            QMenu {
                background-color: #1E293B;
                color: #CBD5E1;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 24px 8px 12px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background-color: #3B82F6;
                color: #FFFFFF;
            }

            QProgressBar {
                background-color: #1E293B;
                border: none;
                border-radius: 5px;
                height: 10px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #60A5FA);
                border-radius: 5px;
            }

            QLineEdit, QTextEdit {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px;
                padding: 8px 12px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #3B82F6;
                background-color: #1E293B;
            }
        """)

    # ──────────────────────────────────────────────
    # ARAÇ ÇUBUĞU
    # ──────────────────────────────────────────────

    def _init_toolbar(self) -> None:
        """Üst toolbar'ı ikon odaklı görünüm ve araç aksiyonlarıyla kurar."""
        toolbar = QToolBar("SelçukBolt Toolbar")
        toolbar.setMovable(False)
        # UI STYLE UPDATE — toolbar sizing
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(toolbar)
        self.main_toolbar = toolbar

        logo = QLabel("🦷")
        logo.setStyleSheet("font-size: 18px; color: #3B82F6; padding-right: 2px;")
        toolbar.addWidget(logo)

        title = QLabel("SelçukBolt")
        title.setObjectName("app_title")
        toolbar.addWidget(title)
        toolbar.addWidget(self._make_toolbar_divider())

        self.action_load_maxilla = self._create_toolbar_action(
            "Maksilla",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            self._load_maxilla,
            "Maksilla STL dosyasını yükle",
        )
        self.action_load_mandible = self._create_toolbar_action(
            "Mandibula",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            self._load_mandible,
            "Mandibula STL dosyasını yükle",
        )
        toolbar.addAction(self.action_load_maxilla)
        toolbar.addAction(self.action_load_mandible)
        toolbar.addWidget(self._make_toolbar_divider())

        # FAZ 3: OTOMATİK SEGMENTASYON AKSIYONU
        self.action_auto_segment = self._create_toolbar_action(
            "Otomatik Segmentasyon",
            QStyle.StandardPixmap.SP_ComputerIcon,
            self._run_segmentation,
            "🤖 AI Segmentasyon: Dişleri otomatik tespit et ve ölç",
        )
        self.action_auto_segment.setObjectName("autoSegmentAction")
        toolbar.addAction(self.action_auto_segment)
        toolbar.addWidget(self._make_toolbar_divider())

        self.view_action_group = QActionGroup(self)
        self.view_action_group.setExclusive(True)
        self.action_view_maxilla = self._create_toolbar_action(
            "Maksilla seç",
            QStyle.StandardPixmap.SP_ArrowUp,
            lambda: self._set_view_mode("maxillary"),
            "Sadece maksillayı göster",
            checkable=True,
        )
        self.action_view_mandible = self._create_toolbar_action(
            "Mandibula seç",
            QStyle.StandardPixmap.SP_ArrowDown,
            lambda: self._set_view_mode("mandibular"),
            "Sadece mandibulayı göster",
            checkable=True,
        )
        self.action_view_occlusion = self._create_toolbar_action(
            "Kapanış görünümü",
            QStyle.StandardPixmap.SP_DesktopIcon,
            lambda: self._set_view_mode("occlusion"),
            "İki çeneyi birlikte göster",
            checkable=True,
        )
        for action in (self.action_view_maxilla, self.action_view_mandible, self.action_view_occlusion):
            self.view_action_group.addAction(action)
            toolbar.addAction(action)

        toolbar.addWidget(self._make_toolbar_divider())

        self.navigation_action_group = QActionGroup(self)
        self.navigation_action_group.setExclusive(True)
        self.action_tool_rotate = self._create_toolbar_action(
            "Döndür",
            QStyle.StandardPixmap.SP_BrowserReload,
            lambda: self._set_navigation_tool("rotate"),
            "Modeli döndürme odaklı görünüm",
            checkable=True,
        )
        self.action_tool_pan = self._create_toolbar_action(
            "Taşı",
            QStyle.StandardPixmap.SP_ArrowForward,
            lambda: self._set_navigation_tool("pan"),
            "Pan / taşıma odaklı görünüm",
            checkable=True,
        )
        self.action_tool_zoom = self._create_toolbar_action(
            "Yakınlaştır",
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            lambda: self._set_navigation_tool("zoom"),
            "Yakınlaştırma odaklı görünüm",
            checkable=True,
        )
        for action in (self.action_tool_rotate, self.action_tool_pan, self.action_tool_zoom):
            self.navigation_action_group.addAction(action)
            toolbar.addAction(action)

        toolbar.addWidget(self._make_toolbar_divider())

        self.action_save_session = self._create_toolbar_action(
            "Oturum Kaydet",
            QStyle.StandardPixmap.SP_DialogSaveButton,
            self._save_session_as,
            "Mevcut oturumu kaydet",
        )
        self.action_load_session = self._create_toolbar_action(
            "Oturum Yükle",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            self._load_session_from_file,
            "Kaydedilmiş oturumu yükle",
        )
        toolbar.addAction(self.action_save_session)
        toolbar.addAction(self.action_load_session)
        toolbar.addWidget(self._make_toolbar_divider())

        self.export_menu = QMenu(self)
        self.export_menu.addAction("Excel (.xlsx)", self._export_excel_template)
        self.export_menu.addAction("CSV (.csv)", self._export_csv)
        self.export_menu.addAction("PDF (.pdf)", self._export_pdf)
        self.export_menu.addAction("JSON (.json)", self._export_json)

        self.export_tool_button = QToolButton()
        self.export_tool_button.setObjectName("exportMenuButton")
        self.export_tool_button.setText("Dışa Aktar")
        self.export_tool_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon))
        self.export_tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.export_tool_button.setMenu(self.export_menu)
        self.export_tool_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        # UI STYLE UPDATE — export menu button
        self.export_tool_button.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                color: #94A3B8;
                border: 1px solid transparent;
                border-radius: 7px;
                padding: 5px 10px;
                font-size: 12px;
                min-height: 30px;
            }
            QToolButton:hover {
                background-color: rgba(255,255,255,0.06);
                color: #E2E8F0;
                border-color: rgba(255,255,255,0.08);
            }
            QToolButton::menu-indicator {
                image: none;
                width: 0;
            }
        """)
        toolbar.addWidget(self.export_tool_button)

        toolbar.addWidget(self._make_toolbar_divider())

        self.action_clear_all = self._create_toolbar_action(
            "Temizle",
            QStyle.StandardPixmap.SP_TrashIcon,
            self._clear_all,
            "Tüm modelleri ve ölçümleri temizle",
        )
        toolbar.addAction(self.action_clear_all)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.action_settings = self._create_toolbar_action(
            "Ayarlar",
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            self._show_about,
            "SelçukBolt ayarları ve uygulama bilgileri",
        )
        toolbar.addAction(self.action_settings)

        self.profile_chip = QLabel("Dr. Selçuk")
        # UI STYLE UPDATE — profile chip
        self.profile_chip.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                background-color: transparent;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 14px;
                padding: 4px 12px 4px 8px;
                margin-left: 6px;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.3px;
            }
            QLabel:hover {
                background-color: rgba(255,255,255,0.05);
                color: #E2E8F0;
            }
        """)
        toolbar.addWidget(self.profile_chip)

        self.action_tool_rotate.setChecked(True)
        self.action_view_maxilla.setChecked(True)

    def _make_toolbar_divider(self) -> QWidget:
        """Toolbar grupları arasında ince bir ayırıcı üretir."""
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFixedWidth(1)
        divider.setFixedHeight(24)
        divider.setStyleSheet("background-color: rgba(255,255,255,0.08); border: none;")
        return divider

    def _refresh_toolbar_availability(self) -> None:
        """Toolbar aksiyonlarını mevcut çalışma durumuna göre etkinleştirir."""
        has_maxilla = self.maxilla_mesh is not None
        has_mandible = self.mandible_mesh is not None
        has_any_mesh = has_maxilla or has_mandible
        has_any_data = has_any_mesh or not self.measurement_panel.df.empty

        for attr, enabled in (
            ("action_view_maxilla", has_maxilla),
            ("action_view_mandible", has_mandible),
            ("action_view_occlusion", has_maxilla and has_mandible),
            ("action_tool_rotate", has_any_mesh),
            ("action_tool_pan", has_any_mesh),
            ("action_tool_zoom", has_any_mesh),
            ("action_save_session", has_any_data),
            ("action_clear_all", has_any_data),
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(enabled)

        if hasattr(self, "export_tool_button"):
            self.export_tool_button.setEnabled(has_any_data)

    def _open_footer_export_menu(self) -> None:
        """Alt bardaki dışa aktar butonundan aynı export menüsünü açar."""
        if not hasattr(self, "export_menu"):
            return
        self.export_menu.exec(self.btn_report_overlay.mapToGlobal(QPoint(0, self.btn_report_overlay.height())))

    def _create_toolbar_action(
        self,
        text: str,
        icon_kind: QStyle.StandardPixmap,
        handler,
        tooltip: str,
        *,
        checkable: bool = False,
    ) -> QAction:
        """Standart ikonlu toolbar aksiyonu oluşturur."""
        action = QAction(self.style().standardIcon(icon_kind), text, self)
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        action.setCheckable(checkable)
        # Toolbar QAction::triggered(bool) sinyalinin bool parametresi,
        # özellikle lambda tabanlı handler'larda sessiz uyumsuzluk yaratmasın.
        action.triggered.connect(lambda _checked=False, cb=handler: cb())
        return action

    # ──────────────────────────────────────────────
    # MERKEZ WIDGET (3 PANEL)
    # ──────────────────────────────────────────────

    def _init_central_widget(self) -> None:
        """Sidebar + viewport + alt analiz panelinden oluşan ana düzeni kur."""
        self.viewer_maxilla = MeshViewer(
            title="⬆ Maksilla",
            is_mandible=False
        )
        self.viewer_mandible = MeshViewer(
            title="⬇ Mandibula",
            is_mandible=True
        )
        self.viewer_occlusion = MeshViewer(
            title="◎ Kapanış Görünümü",
            is_mandible=False,
        )

        self.measurement_panel = MeasurementPanel()
        self.measurement_panel.hide()

        self.central_root = QWidget()
        root_layout = QHBoxLayout(self.central_root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.left_panel = self._build_left_panel()
        self.center_panel = self._build_center_panel()

        root_layout.addWidget(self.left_panel, 0)
        root_layout.addWidget(self.center_panel, 1)
        self.setCentralWidget(self.central_root)

        self._build_report_overlay()
        self._sync_dashboard_from_measurements()

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sideNav")
        panel.setFixedWidth(72)
        # UI STYLE UPDATE — side navigation shell
        panel.setStyleSheet("""
            QFrame#sideNav {
                background-color: #0A0F1D;
                border: none;
                border-right: 1px solid rgba(255,255,255,0.05);
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(10)

        brand = QLabel("🦷")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet("font-size: 24px; color: #3B82F6;")
        layout.addWidget(brand)

        self.nav_button_group = QButtonGroup(panel)
        self.nav_button_group.setExclusive(True)
        self.nav_buttons: dict[str, QToolButton] = {}
        nav_specs = (
            ("profile", "👤", "Profil"),
            ("patients", "🦷", "Hastalar"),
            ("records", "🗂", "Kayıtlar"),
            ("settings", "⚙", "Ayarlar"),
        )
        for key, icon_text, tooltip in nav_specs:
            btn = QToolButton()
            btn.setText(icon_text)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedSize(52, 52)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            # UI STYLE UPDATE — side navigation item
            btn.setStyleSheet("""
                QToolButton {
                    background-color: transparent;
                    color: #475569;
                    border: none;
                    border-radius: 12px;
                    font-size: 20px;
                    margin: 4px 0;
                }
                QToolButton:hover {
                    background-color: rgba(59, 130, 246, 0.1);
                    color: #3B82F6;
                }
                QToolButton:checked {
                    background-color: rgba(59, 130, 246, 0.15);
                    color: #3B82F6;
                    border-left: 3px solid #3B82F6;
                    border-radius: 0 12px 12px 0;
                }
            """)
            self.nav_button_group.addButton(btn)
            self.nav_buttons[key] = btn
            layout.addWidget(btn)
        self.nav_buttons["records"].setChecked(True)

        layout.addStretch(1)

        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        toolbar_card = QFrame()
        self.workspace_header = toolbar_card
        toolbar_card.setObjectName("workspaceHeader")
        # UI STYLE UPDATE — workspace header shell
        toolbar_card.setStyleSheet("""
            QFrame#workspaceHeader {
                background-color: #121826;
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 16px;
            }
            QLabel {
                color: #E2E8F0;
            }
        """)
        toolbar_layout = QHBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(14, 12, 14, 12)
        toolbar_layout.setSpacing(14)

        info_column = QVBoxLayout()
        info_column.setSpacing(6)

        file_row = QHBoxLayout()
        file_row.setSpacing(10)
        self.lbl_maxilla_file = QLabel("MAKSILLA • Yüklenmedi")
        # UI STYLE UPDATE — workspace file labels
        self.lbl_maxilla_file.setStyleSheet("""
            color: #475569;
            font-size: 10px;
            letter-spacing: 0.8px;
            text-transform: uppercase;
        """)
        self.lbl_mandible_file = QLabel("MANDIBULA • Yüklenmedi")
        self.lbl_mandible_file.setStyleSheet("""
            color: #475569;
            font-size: 10px;
            letter-spacing: 0.8px;
            text-transform: uppercase;
        """)
        file_row.addWidget(self.lbl_maxilla_file)
        file_row.addWidget(self.lbl_mandible_file)
        file_row.addStretch(1)
        info_column.addLayout(file_row)

        self.lbl_active_mode = QLabel("MAKSILLA • Landmark Hazır")
        # UI STYLE UPDATE — active mode heading
        self.lbl_active_mode.setStyleSheet("""
            color: #F1F5F9;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.6px;
        """)
        info_column.addWidget(self.lbl_active_mode)

        self.lbl_active_step = QLabel("STL dosyalarını yükleyin ve ölçüme başlayın.")
        self.lbl_active_step.setWordWrap(True)
        # UI STYLE UPDATE — active step status
        self.lbl_active_step.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                background-color: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.05);
                border-radius: 10px;
                padding: 7px 11px;
                font-size: 11px;
                line-height: 1.5;
            }
        """)
        info_column.addWidget(self.lbl_active_step)
        toolbar_layout.addLayout(info_column, 1)

        utility_column = QVBoxLayout()
        utility_column.setSpacing(6)

        self.lbl_viewer_hint = QLabel(
            "Araç: Döndür • Sol tık: seçim • Sağ tık: döndür • Trackpad/tekerlek: zoom"
        )
        self.lbl_viewer_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_viewer_hint.setStyleSheet("color: #64748B; font-size: 11px;")
        utility_column.addWidget(self.lbl_viewer_hint)

        self.lbl_arch_stage = QLabel("Ark boyu son aşamada ölçülür • N = eksik diş • F11 = tam ekran")
        self.lbl_arch_stage.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_arch_stage.setStyleSheet("""
            QLabel {
                color: #93C5FD;
                font-size: 11px;
                font-family: 'Menlo';
                background-color: rgba(59, 130, 246, 0.08);
                border: 1px solid rgba(59, 130, 246, 0.16);
                border-radius: 10px;
                padding: 6px 10px;
            }
        """)
        utility_column.addWidget(self.lbl_arch_stage)

        self.btn_model_focus = QPushButton("Odak Modu")
        self.btn_model_focus.setObjectName("accentButton")
        self.btn_model_focus.clicked.connect(self._toggle_model_focus_mode)
        utility_column.addWidget(self.btn_model_focus, 0, Qt.AlignmentFlag.AlignRight)
        toolbar_layout.addLayout(utility_column)

        layout.addWidget(toolbar_card)

        self.viewer_stack = QStackedWidget()
        self.viewer_stack.addWidget(self.viewer_maxilla)
        self.viewer_stack.addWidget(self.viewer_mandible)
        self.viewer_stack.addWidget(self.viewer_occlusion)

        self.right_panel = self._build_right_panel()

        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.viewer_stack)
        self.workspace_splitter.addWidget(self.right_panel)
        self.workspace_splitter.setStretchFactor(0, 6)
        self.workspace_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.workspace_splitter, 1)

        self._set_analysis_panel_collapsed(True, adjust_splitter=False)
        QTimer.singleShot(0, self._apply_workspace_splitter_sizes)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("analysisPanel")
        panel.setStyleSheet("""
            QFrame#analysisPanel {
                background-color: #121826;
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 16px;
                margin-top: 4px;
            }
            QLabel {
                color: #E2E8F0;
            }
            QGroupBox {
                background-color: #0F1219;
                border: 1px solid rgba(255,255,255,0.04);
                border-radius: 12px;
                margin-top: 16px;
                padding-top: 12px;
                font-size: 10px;
                font-weight: 800;
                color: #3B82F6;
                letter-spacing: 0.5px;
            }
        """)
        panel.setMinimumHeight(160)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        title = QLabel("BOLTON ANALİZ PANELİ")
        title.setStyleSheet("font-size: 13px; font-weight: 800; font-family: 'Syne'; letter-spacing: 0.8px;")
        header_layout.addWidget(title)

        self.lbl_footer_progress = QLabel("0 / 24 DIŞ")
        self.lbl_footer_progress.setStyleSheet("color: #94A3B8; font-size: 11px; font-family: 'Menlo';")

        self.progress_measurements = QProgressBar()
        self.progress_measurements.setRange(0, 24)
        self.progress_measurements.setValue(0)
        self.progress_measurements.setTextVisible(False)
        self.progress_measurements.setFixedHeight(8)
        self.progress_measurements.setStyleSheet("""
            QProgressBar {
                background-color: #0F1219;
                border: 1px solid rgba(255,255,255,0.04);
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #60A5FA);
                border-radius: 6px;
            }
        """)
        header_layout.addStretch(1)

        self.btn_measure_arch = QPushButton("Ark Boyunu Ölç")
        self.btn_measure_arch.setObjectName("secondaryButton")
        self.btn_measure_arch.clicked.connect(self._start_next_arch_measurement)
        self.btn_measure_arch.setVisible(False)
        header_layout.addWidget(self.btn_measure_arch)

        self.btn_edit_max_arch = QPushButton("Üst Arkı Düzenle")
        self.btn_edit_max_arch.setObjectName("secondaryButton")
        self.btn_edit_max_arch.clicked.connect(lambda: self._edit_arch_measurement("maxillary"))
        self.btn_edit_max_arch.setVisible(False)
        header_layout.addWidget(self.btn_edit_max_arch)

        self.btn_edit_mand_arch = QPushButton("Alt Arkı Düzenle")
        self.btn_edit_mand_arch.setObjectName("secondaryButton")
        self.btn_edit_mand_arch.clicked.connect(lambda: self._edit_arch_measurement("mandibular"))
        self.btn_edit_mand_arch.setVisible(False)
        header_layout.addWidget(self.btn_edit_mand_arch)

        self.btn_report_overlay = QPushButton("Dışa Aktar")
        self.btn_report_overlay.setObjectName("accentButton")
        self.btn_report_overlay.clicked.connect(self._open_footer_export_menu)
        header_layout.addWidget(self.btn_report_overlay)

        self.btn_toggle_analysis = QPushButton("Detaylar")
        self.btn_toggle_analysis.setObjectName("secondaryButton")
        self.btn_toggle_analysis.setToolTip("Detay tablo görünümünü aç veya gizle")
        self.btn_toggle_analysis.clicked.connect(self._toggle_analysis_panel)
        header_layout.addWidget(self.btn_toggle_analysis)

        layout.addWidget(header)

        self.analysis_content = QWidget()
        content_layout = QVBoxLayout(self.analysis_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)

        self.card_progress = QFrame()
        self.card_progress.setStyleSheet("""
            QFrame {
                background-color: #0F1219;
                border: 1px solid rgba(255,255,255,0.05);
                border-radius: 14px;
            }
            QLabel {
                color: #E2E8F0;
            }
        """)
        progress_layout = QVBoxLayout(self.card_progress)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        progress_layout.setSpacing(8)
        lbl_progress_title = QLabel("İLERLEME")
        lbl_progress_title.setStyleSheet("color: #64748B; font-size: 10px; font-weight: 800;")
        progress_layout.addWidget(lbl_progress_title)
        progress_layout.addWidget(self.lbl_footer_progress)
        progress_layout.addWidget(self.progress_measurements)
        summary_row.addWidget(self.card_progress, 1)

        self.card_ant = QFrame()
        self.card_ant.setStyleSheet("""
            QFrame {
                background-color: #0F1219;
                border: 1px solid rgba(59,130,246,0.16);
                border-radius: 14px;
            }
            QLabel {
                color: #CBD5E1;
            }
        """)
        ant_layout = QVBoxLayout(self.card_ant)
        ant_layout.setContentsMargins(14, 12, 14, 12)
        ant_layout.setSpacing(4)
        lbl_ant_title = QLabel("ANTERIOR")
        lbl_ant_title.setStyleSheet("color: #60A5FA; font-size: 10px; font-weight: 800;")
        self.lbl_ant_ratio_value = QLabel("Oran: —")
        self.lbl_ant_ratio_value.setStyleSheet("font-size: 22px; font-weight: 800; color: #F8FAFC;")
        self.lbl_ant_ref = QLabel("Referans: 77.2% ± 1.65%")
        self.lbl_ant_diff = QLabel("Fark: —")
        self.lbl_ant_status = QLabel("Bekleniyor")
        for label in (self.lbl_ant_ref, self.lbl_ant_diff, self.lbl_ant_status):
            label.setStyleSheet("font-size: 11px; color: #94A3B8; font-family: 'Menlo';")
        ant_layout.addWidget(lbl_ant_title)
        ant_layout.addWidget(self.lbl_ant_ratio_value)
        ant_layout.addWidget(self.lbl_ant_ref)
        ant_layout.addWidget(self.lbl_ant_diff)
        ant_layout.addWidget(self.lbl_ant_status)
        summary_row.addWidget(self.card_ant, 1)

        self.card_ovr = QFrame()
        self.card_ovr.setStyleSheet("""
            QFrame {
                background-color: #0F1219;
                border: 1px solid rgba(14,165,164,0.16);
                border-radius: 14px;
            }
            QLabel {
                color: #CBD5E1;
            }
        """)
        ovr_layout = QVBoxLayout(self.card_ovr)
        ovr_layout.setContentsMargins(14, 12, 14, 12)
        ovr_layout.setSpacing(4)
        lbl_ovr_title = QLabel("OVERALL")
        lbl_ovr_title.setStyleSheet("color: #2DD4BF; font-size: 10px; font-weight: 800;")
        self.lbl_ovr_ratio_value = QLabel("Oran: —")
        self.lbl_ovr_ratio_value.setStyleSheet("font-size: 22px; font-weight: 800; color: #F8FAFC;")
        self.lbl_ovr_ref = QLabel("Referans: 91.3% ± 1.91%")
        self.lbl_ovr_diff = QLabel("Fark: —")
        self.lbl_ovr_status = QLabel("Bekleniyor")
        for label in (self.lbl_ovr_ref, self.lbl_ovr_diff, self.lbl_ovr_status):
            label.setStyleSheet("font-size: 11px; color: #94A3B8; font-family: 'Menlo';")
        ovr_layout.addWidget(lbl_ovr_title)
        ovr_layout.addWidget(self.lbl_ovr_ratio_value)
        ovr_layout.addWidget(self.lbl_ovr_ref)
        ovr_layout.addWidget(self.lbl_ovr_diff)
        ovr_layout.addWidget(self.lbl_ovr_status)
        summary_row.addWidget(self.card_ovr, 1)

        content_layout.addLayout(summary_row)

        self.lbl_arch_summary = QLabel("Ark Boyu: Henüz ölçülmedi")
        self.lbl_arch_summary.setWordWrap(True)
        self.lbl_arch_summary.setStyleSheet("""
            QLabel {
                background-color: #111722;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 10px;
                color: #CBD5E1;
                font-size: 11px;
                font-family: 'Menlo';
            }
        """)
        content_layout.addWidget(self.lbl_arch_summary)

        self.analysis_details = QWidget()
        details_layout = QVBoxLayout(self.analysis_details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)

        table_title = QLabel("DİŞ BOYUTLARI (mm)")
        table_title.setStyleSheet("font-size: 13px; font-weight: 700; font-family: 'Syne';")

        self.table_results = QTableWidget(0, 2)
        self.table_results.setHorizontalHeaderLabels(["Diş", "MDWidth"])
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_results.setAlternatingRowColors(True)
        self.table_results.cellDoubleClicked.connect(self._edit_selected_tooth_from_table)
        self.table_results.itemSelectionChanged.connect(self._update_tooth_edit_button_state)
        self.table_results.setStyleSheet("""
            QTableWidget {
                background-color: #0F1219;
                color: #E2E8F0;
                border: 1px solid rgba(255,255,255,0.04);
                border-radius: 12px;
                gridline-color: rgba(255,255,255,0.02);
                font-size: 11px;
                font-family: 'JetBrains Mono', 'Menlo', monospace;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #64748B;
                border: none;
                border-bottom: 1px solid rgba(255,255,255,0.04);
                padding: 6px;
                font-size: 10px;
                font-weight: 800;
                text-transform: uppercase;
            }
        """)
        self.btn_edit_selected_tooth = QPushButton("Seçili Dişi Düzenle")
        self.btn_edit_selected_tooth.setObjectName("secondaryButton")
        self.btn_edit_selected_tooth.setEnabled(False)
        self.btn_edit_selected_tooth.clicked.connect(self._edit_selected_result_tooth)

        details_layout.addWidget(table_title)
        details_layout.addWidget(self.table_results, 1)
        details_layout.addWidget(self.btn_edit_selected_tooth)
        content_layout.addWidget(self.analysis_details, 1)

        layout.addWidget(self.analysis_content, 1)
        self.analysis_collapsed = False
        return panel

    def _toggle_analysis_panel(self) -> None:
        """Alt analiz panelindeki detay tablo görünümünü açıp kapatır."""
        self._set_analysis_panel_collapsed(not getattr(self, "analysis_collapsed", False))

    def _set_analysis_panel_collapsed(self, collapsed: bool, *, adjust_splitter: bool = True) -> None:
        """Analiz panelini özet görünümüyle sınırlar veya detay tabloyu açar."""
        self.analysis_collapsed = collapsed
        self.analysis_details.setVisible(not collapsed)
        self.btn_toggle_analysis.setText("Detayı Aç" if collapsed else "Detayı Gizle")
        self.right_panel.setMinimumHeight(160 if collapsed else 280)
        self.right_panel.updateGeometry()
        if adjust_splitter:
            self._apply_workspace_splitter_sizes()

    def _apply_workspace_splitter_sizes(self) -> None:
        """Model alanını baskın tutacak başlangıç oranlarını uygular."""
        if not hasattr(self, "workspace_splitter"):
            return
        total_height = sum(size for size in self.workspace_splitter.sizes() if size > 0)
        if total_height <= 0:
            total_height = max(self.height() - 220, 520)
        analysis_height = 160 if getattr(self, "analysis_collapsed", False) else 300
        viewer_height = max(total_height - analysis_height, 360)
        self.workspace_splitter.setSizes([viewer_height, analysis_height])

    def _refresh_arch_button_state(self) -> None:
        """Ark boyu butonunun aşamasını günceller."""
        all_teeth_complete = (
            len(self.completed_teeth["maxillary"]) + len(self.missing_teeth["maxillary"]) == len(self.guided_sequences["maxillary"])
        ) and (
            len(self.completed_teeth["mandibular"]) + len(self.missing_teeth["mandibular"]) == len(self.guided_sequences["mandibular"])
        )
        if not all_teeth_complete:
            self.btn_measure_arch.setVisible(False)
            self.btn_measure_arch.setEnabled(True)
            self.btn_edit_max_arch.setVisible(False)
            self.btn_edit_max_arch.setEnabled(True)
            self.btn_edit_mand_arch.setVisible(False)
            self.btn_edit_mand_arch.setEnabled(True)
            return

        self.btn_measure_arch.setVisible(True)
        self.btn_measure_arch.setEnabled(True)
        if self.arch_lengths["maxillary"] is None:
            self.btn_measure_arch.setText("Üst Ark Boyunu Ölç")
        elif self.arch_lengths["mandibular"] is None:
            self.btn_measure_arch.setText("Alt Ark Boyunu Seç")
        else:
            self.btn_measure_arch.setText("Ark Boyları Tamamlandı")
            self.btn_measure_arch.setEnabled(False)

        self.btn_edit_max_arch.setVisible(self.arch_lengths["maxillary"] is not None)
        self.btn_edit_max_arch.setEnabled(self.arch_lengths["maxillary"] is not None)
        self.btn_edit_mand_arch.setVisible(self.arch_lengths["mandibular"] is not None)
        self.btn_edit_mand_arch.setEnabled(self.arch_lengths["mandibular"] is not None)

    def _sync_dashboard_from_measurements(self) -> None:
        """Sağ/sol panelleri MeasurementPanel verisinden günceller."""
        if self._refresh_missing_tooth_estimates():
            self.measurement_panel._refresh_table()
            self.measurement_panel._update_bolton_summary()
            self.measurement_panel._update_button_states()
            self.measurement_panel._update_progress()
            self.measurement_panel._check_completion()

        df = self.measurement_panel.get_dataframe()
        missing_all = self.missing_teeth["maxillary"] | self.missing_teeth["mandibular"]
        measured = sum(1 for tooth in df["tooth_fdi"].tolist() if int(tooth) not in missing_all)
        estimated = sum(1 for tooth in df["tooth_fdi"].tolist() if int(tooth) in missing_all)
        missing = len(self.missing_teeth["maxillary"]) + len(self.missing_teeth["mandibular"])
        processed = measured + missing
        percent = int(round((processed / 24) * 100)) if processed else 0
        self.lbl_footer_progress.setText(
            f"{processed}/24 tamamlandı  •  %{percent}  •  Ölçüm {measured}  •  Tahmini {estimated}  •  Eksik {missing}"
        )
        self.progress_measurements.setValue(processed)

        self.lbl_ant_ratio_value.setText(self.measurement_panel.lbl_ant_ratio.text())
        self.lbl_ant_diff.setText(self.measurement_panel.lbl_ant_disc.text() or "Fark: —")
        ant_progress = self.measurement_panel.lbl_ant_progress.text()
        self.lbl_ant_status.setText("Hazır" if ant_progress == "12/12 diş" else ant_progress)
        ant_ready = ant_progress == "12/12 diş"
        self.lbl_ant_status.setStyleSheet(
            "font-size: 11px; font-family: 'Menlo'; color: %s;" % ("#22C55E" if ant_ready else "#CBD5E1")
        )
        self.lbl_ant_ratio_value.setStyleSheet(
            "font-size: 22px; font-weight: 800; color: %s;" % ("#22C55E" if ant_ready else "#F8FAFC")
        )

        self.lbl_ovr_ratio_value.setText(self.measurement_panel.lbl_ovr_ratio.text())
        self.lbl_ovr_diff.setText(self.measurement_panel.lbl_ovr_disc.text() or "Fark: —")
        ovr_progress = self.measurement_panel.lbl_ovr_progress.text()
        self.lbl_ovr_status.setText("Hazır" if ovr_progress == "24/24 diş" else ovr_progress)
        ovr_ready = ovr_progress == "24/24 diş"
        self.lbl_ovr_status.setStyleSheet(
            "font-size: 11px; font-family: 'Menlo'; color: %s;" % ("#22C55E" if ovr_ready else "#CBD5E1")
        )
        self.lbl_ovr_ratio_value.setStyleSheet(
            "font-size: 22px; font-weight: 800; color: %s;" % ("#22C55E" if ovr_ready else "#F8FAFC")
        )

        self.table_results.setRowCount(0)
        order = list(MAXILLARY_OVERALL) + list(MANDIBULAR_OVERALL)
        sort_map = {fdi: idx for idx, fdi in enumerate(order)}
        if not df.empty:
            sorted_df = df.copy()
            sorted_df["_sort"] = sorted_df["tooth_fdi"].map(lambda x: sort_map.get(int(x), 999))
            sorted_df = sorted_df.sort_values("_sort")
            for _, row in sorted_df.iterrows():
                tooth_fdi = int(row["tooth_fdi"])
                row_idx = self.table_results.rowCount()
                self.table_results.insertRow(row_idx)
                self.table_results.setItem(row_idx, 0, QTableWidgetItem(str(tooth_fdi)))
                if tooth_fdi in missing_all:
                    value_text = f'Tahmini {float(row["width_mm"]):.2f}'
                else:
                    value_text = f'{float(row["width_mm"]):.2f}'
                self.table_results.setItem(row_idx, 1, QTableWidgetItem(value_text))

        for jaw in ("maxillary", "mandibular"):
            for tooth in sorted(self.missing_teeth[jaw], key=lambda fdi: sort_map.get(int(fdi), 999)):
                estimated_row = df[df["tooth_fdi"] == tooth]
                if not estimated_row.empty:
                    continue
                row_idx = self.table_results.rowCount()
                self.table_results.insertRow(row_idx)
                self.table_results.setItem(row_idx, 0, QTableWidgetItem(str(int(tooth))))
                self.table_results.setItem(row_idx, 1, QTableWidgetItem("Eksik"))

        arch_parts = []
        if self.arch_lengths["maxillary"] is not None:
            arch_parts.append(f"Üst Ark: {self.arch_lengths['maxillary']:.2f} mm")
        if self.arch_lengths["mandibular"] is not None:
            arch_parts.append(f"Alt Ark: {self.arch_lengths['mandibular']:.2f} mm")
        self.lbl_arch_summary.setText("  •  ".join(arch_parts) if arch_parts else "Ark Boyu: Henüz ölçülmedi")
        self._refresh_arch_button_state()
        self._update_tooth_edit_button_state()
        self._autosave_session()

    def _serialize_point(self, point: Optional[np.ndarray]) -> Optional[list[float]]:
        """Numpy noktayı JSON uyumlu listeye çevirir."""
        if point is None:
            return None
        arr = np.asarray(point, dtype=np.float64)
        if arr.shape != (3,):
            return None
        return arr.tolist()

    def _build_session_payload(self) -> dict:
        """Mevcut çalışma durumunu dışa aktarılabilir sözlüğe çevirir."""
        rows = []
        if not self.measurement_panel.df.empty:
            rows = self.measurement_panel.df.to_dict(orient="records")

        return {
            "session_version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "maxilla_path": self._maxilla_path,
            "mandible_path": self._mandible_path,
            "maxilla_filename": self._maxilla_filename,
            "mandible_filename": self._mandible_filename,
            "measurement_rows": rows,
            "completed_teeth": {
                jaw: sorted(int(tooth) for tooth in teeth)
                for jaw, teeth in self.completed_teeth.items()
            },
            "missing_teeth": {
                jaw: sorted(int(tooth) for tooth in teeth)
                for jaw, teeth in self.missing_teeth.items()
            },
            "arch_lengths": {
                jaw: (None if value is None else float(value))
                for jaw, value in self.arch_lengths.items()
            },
            "arch_paths": {
                jaw: [self._serialize_point(point) for point in points]
                for jaw, points in self.arch_paths.items()
            },
            "guided_active": self.guided_active,
            "guided_jaw": self.guided_jaw,
            "guided_sequence": [int(tooth) for tooth in self.guided_sequence],
            "guided_index": int(self.guided_index),
            "guided_step": self.guided_step,
            "guided_mesial_point": self._serialize_point(self.guided_mesial_point),
            "guided_distal_point": self._serialize_point(self.guided_distal_point),
            "guided_pending_point": self._serialize_point(self.guided_pending_point),
            "arch_mode_active": self.arch_mode_active,
            "arch_mode_jaw": self.arch_mode_jaw,
            "arch_points": [self._serialize_point(point) for point in self.arch_points],
            "view_mode": self.current_view_mode,
            "active_navigation_tool": self.active_navigation_tool,
        }

    def _autosave_session(self) -> None:
        """Mevcut çalışma oturumunu disk üzerinde otomatik saklar."""
        if self._restoring_session:
            return

        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._build_session_payload()
            with self._session_path.open("w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[MainWindow] Autosave yazılamadı: {exc}", flush=True)

    def _clear_autosave_session(self) -> None:
        """Otomatik kaydedilmiş oturum dosyasını temizler."""
        try:
            if self._session_path.exists():
                self._session_path.unlink()
        except Exception as exc:
            print(f"[MainWindow] Autosave temizlenemedi: {exc}", flush=True)

    def _get_bolton_measurements_dict(self) -> dict[int, float]:
        """Mevcut tabloyu Bolton hesapları için sade bir sözlüğe çevirir."""
        df = self.measurement_panel.get_dataframe()
        measurements: dict[int, float] = {}
        for _, row in df.iterrows():
            measurements[int(row["tooth_fdi"])] = float(row["width_mm"])
        return measurements

    def _get_contralateral_tooth(self, tooth_fdi: int) -> Optional[int]:
        """Aynı dişin karşı taraftaki kontralateral eşini döndürür."""
        quadrant = tooth_fdi // 10
        tooth_no = tooth_fdi % 10
        contralateral_map = {1: 2, 2: 1, 3: 4, 4: 3}
        other_quadrant = contralateral_map.get(quadrant)
        if other_quadrant is None:
            return None
        return other_quadrant * 10 + tooth_no

    def _remove_tooth_row(self, tooth_fdi: int) -> None:
        """Bir dişe ait mevcut dataframe satırını kaldırır."""
        self.measurement_panel.df = self.measurement_panel.df[
            self.measurement_panel.df["tooth_fdi"] != tooth_fdi
        ].reset_index(drop=True)

    def _refresh_missing_tooth_estimates(self) -> bool:
        """Kontralaterali sonradan ölçülen eksik dişler için tahmini değeri otomatik tamamlar."""
        measurements = self._get_bolton_measurements_dict()
        existing_teeth = set(int(tooth) for tooth in self.measurement_panel.df["tooth_fdi"].tolist())
        changed = False

        for jaw in ("maxillary", "mandibular"):
            for tooth_fdi in self.missing_teeth[jaw]:
                if tooth_fdi in existing_teeth:
                    continue
                contralateral_tooth = self._get_contralateral_tooth(tooth_fdi)
                if contralateral_tooth is None or contralateral_tooth not in measurements:
                    continue
                self._upsert_missing_tooth_estimate(
                    tooth_fdi,
                    jaw,
                    float(measurements[contralateral_tooth]),
                )
                existing_teeth.add(tooth_fdi)
                changed = True

        return changed

    def _upsert_missing_tooth_estimate(self, tooth_fdi: int, jaw: str, width_mm: float) -> None:
        """Eksik diş için tahmini genişlik satırı ekler veya günceller."""
        self._remove_tooth_row(tooth_fdi)
        estimate_row = pd.DataFrame([{
            "tooth_fdi": tooth_fdi,
            "jaw": jaw,
            "mesial_xyz": None,
            "distal_xyz": None,
            "width_mm": round(float(width_mm), 2),
        }])
        self.measurement_panel.df = pd.concat(
            [self.measurement_panel.df, estimate_row],
            ignore_index=True
        )

    def _resolve_missing_tooth_width(self, tooth_fdi: int) -> Optional[float]:
        """
        Eksik diş için Bolton hesabında kullanılacak genişliği bulur.

        Öncelik:
        1. Kontralateral diş ölçüsü varsa onu kullan.
        2. Yoksa kullanıcıdan mm değeri iste.
        """
        measurements = self._get_bolton_measurements_dict()
        contralateral_tooth = self._get_contralateral_tooth(tooth_fdi)
        if contralateral_tooth is not None and contralateral_tooth in measurements:
            return float(measurements[contralateral_tooth])

        value, accepted = QInputDialog.getDouble(
            self,
            "Eksik Diş Tahmini",
            (
                f"Diş {tooth_fdi} arkta mevcut değil.\n"
                "Kontralateral diş ölçüsü de bulunamadı.\n\n"
                "Bolton hesabı için tahmini meziodistal genişliği girin (mm):"
            ),
            7.00,
            0.10,
            20.00,
            2,
        )
        if not accepted:
            return None
        return float(value)

    def _validate_bolton_calculation_ready(self) -> bool:
        """Anterior ve overall Bolton oranlarının gerçekten hesaplanabildiğini doğrular."""
        if self._refresh_missing_tooth_estimates():
            self.measurement_panel._refresh_table()
            self.measurement_panel._update_bolton_summary()
            self.measurement_panel._update_button_states()
            self.measurement_panel._update_progress()
            self.measurement_panel._check_completion()
        measurements = self._get_bolton_measurements_dict()
        if not measurements:
            QMessageBox.warning(
                self,
                "Ölçüm Yok",
                "Bolton hesabı için önce diş ölçümlerini tamamlayın."
            )
            return False

        try:
            analyze_anterior(measurements)
            analyze_overall(measurements)
            return True
        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Bolton Hesabı Eksik",
                "Bolton oranı şu formüllerle hesaplanır:\n"
                "Anterior = (Alt 6 anterior toplamı / Üst 6 anterior toplamı) × 100\n"
                "Overall = (Alt 12 diş toplamı / Üst 12 diş toplamı) × 100\n\n"
                f"Şu anda hesap tamamlanamadı:\n{exc}"
            )
            return False

    def _default_bolton_template_path(self) -> Path:
        """Klinikte kullanılan varsayılan Excel şablon yolunu döndürür."""
        return Path.home() / "Downloads" / "BOŞ BOLTON.xlsx"

    def _resolve_bolton_template_path(self) -> Optional[Path]:
        """Excel şablonunu varsayılandan veya kullanıcı seçimiyle bulur."""
        default_path = self._default_bolton_template_path()
        if default_path.exists():
            return default_path

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "SelçukBolt Excel Şablonu Seçin",
            str(Path.home() / "Downloads"),
            "Excel Dosyaları (*.xlsx)"
        )
        if not file_path:
            return None
        return Path(file_path)

    def _start_next_arch_measurement(self) -> None:
        """Ark boyunu her zaman en sonda ve sırayla ölçer."""
        if self.arch_lengths["maxillary"] is None:
            self.lbl_active_mode.setText("Aktif: Üst Ark Boyu")
            self.start_arch_perimeter_measurement("maxillary")
        elif self.arch_lengths["mandibular"] is None:
            self.lbl_active_mode.setText("Aktif: Alt Ark Boyu")
            self.start_arch_perimeter_measurement("mandibular")

    def _edit_current_arch_measurement(self) -> None:
        """Tamamlanmış ark boyunu yeniden düzenleme modunda açar."""
        editable_arches = [jaw for jaw, value in self.arch_lengths.items() if value is not None]
        if not editable_arches:
            QMessageBox.information(
                self,
                "Ark Boyu Yok",
                "Düzenlemek için önce en az bir ark boyu ölçümü tamamlayın."
            )
            return

        active_jaw = self._current_active_jaw()
        jaw = active_jaw if active_jaw in editable_arches else editable_arches[0]
        self._edit_arch_measurement(jaw)

    def _edit_arch_measurement(self, jaw: str) -> None:
        """Kaydedilmiş ark noktalarını tekrar açar; yoksa yeniden ölçüm başlatır."""
        if jaw == "maxillary" and self.maxilla_mesh is None:
            QMessageBox.warning(self, "STL Eksik", "Üst arkı düzenlemek için önce üst çene STL dosyasını yükleyin.")
            return
        if jaw == "mandibular" and self.mandible_mesh is None:
            QMessageBox.warning(self, "STL Eksik", "Alt arkı düzenlemek için önce alt çene STL dosyasını yükleyin.")
            return

        if self.guided_active:
            self._reset_guided_measurement_state()
        if self.arch_mode_active:
            self._cancel_arch_perimeter_mode()

        saved_points = self.arch_paths.get(jaw) or []
        if not saved_points:
            self.start_arch_perimeter_measurement(jaw)
            self.lbl_active_step.setText(
                f"{'Üst' if jaw == 'maxillary' else 'Alt'} ark için kayıtlı nokta bulunamadı. Ark boyunu yeniden seçin."
            )
            return

        self.arch_mode_active = True
        self.arch_mode_jaw = jaw
        self.arch_points = [np.asarray(point, dtype=np.float64) for point in saved_points]
        viewer = self._activate_guided_viewer(jaw)
        self._show_arch_page(jaw)
        self._restore_arch_preview_visuals()
        viewer.set_overlay_hint(
            "Ark boyu düzenleme modu aktif. Noktaları sürükleyin, Backspace ile silin, Space ile yeniden kaydedin."
        )
        self.lbl_active_mode.setText(f"Aktif: {'Üst' if jaw == 'maxillary' else 'Alt'} Ark Boyu Düzenleme")
        self.lbl_active_step.setText(
            f"{'Üst' if jaw == 'maxillary' else 'Alt'} ark boyu düzenleniyor. Noktaları sürükleyip Space ile kaydedin."
        )
        self._set_guided_status(
            "📐 Ark düzenleme modu aktif. Noktaları taşıyın; bitince Enter/Space ile yeniden kaydedin."
        )

    def _edit_selected_tooth_from_table(self, row: int, _column: int) -> None:
        """Sonuç tablosundaki dişi çift tıklayınca yeniden ölçüme döndürür."""
        item = self.table_results.item(row, 0)
        if item is None:
            return
        try:
            tooth_fdi = int(item.text())
        except (TypeError, ValueError):
            return
        self._edit_tooth_measurement(tooth_fdi)

    def _selected_result_tooth(self) -> Optional[int]:
        """Sonuç tablosunda seçili diş numarasını döndürür."""
        selected_ranges = self.table_results.selectedRanges()
        if not selected_ranges:
            return None
        row = selected_ranges[0].topRow()
        item = self.table_results.item(row, 0)
        if item is None:
            return None
        try:
            return int(item.text())
        except (TypeError, ValueError):
            return None

    def _update_tooth_edit_button_state(self) -> None:
        """Seçili sonuç satırına göre diş düzenleme butonunu günceller."""
        tooth_fdi = self._selected_result_tooth()
        self.btn_edit_selected_tooth.setEnabled(tooth_fdi is not None)
        if tooth_fdi is None:
            self.btn_edit_selected_tooth.setText("Seçili Dişi Düzenle")
        else:
            self.btn_edit_selected_tooth.setText(f"Diş {tooth_fdi} Düzenle")

    def _edit_selected_result_tooth(self) -> None:
        """Sağ panelde seçili dişi yeniden düzenlemeye açar."""
        tooth_fdi = self._selected_result_tooth()
        if tooth_fdi is None:
            QMessageBox.information(
                self,
                "Diş Seçilmedi",
                "Düzenlemek için sağdaki sonuç tablosundan bir diş seçin."
            )
            return
        self._edit_tooth_measurement(tooth_fdi)

    def _edit_tooth_measurement(self, tooth_fdi: int) -> None:
        """Tamamlanmış veya eksik işaretlenmiş dişi yeniden düzenlemeye açar."""
        jaw = self._get_guided_tooth_jaw(int(tooth_fdi))
        if jaw == "maxillary" and self.maxilla_mesh is None:
            QMessageBox.warning(self, "STL Eksik", "Bu dişi düzenlemek için önce üst çene STL dosyasını yükleyin.")
            return
        if jaw == "mandibular" and self.mandible_mesh is None:
            QMessageBox.warning(self, "STL Eksik", "Bu dişi düzenlemek için önce alt çene STL dosyasını yükleyin.")
            return

        if self.arch_mode_active:
            self._cancel_arch_perimeter_mode()
        if self.guided_active:
            self._reset_guided_measurement_state()

        self.completed_teeth[jaw].discard(int(tooth_fdi))
        self.missing_teeth[jaw].discard(int(tooth_fdi))
        self._remove_tooth_row(int(tooth_fdi))
        self.measurement_panel._refresh_table()
        self.measurement_panel._update_bolton_summary()
        self.measurement_panel._update_button_states()
        self.measurement_panel._update_progress()
        self.measurement_panel._check_completion()
        self._sync_dashboard_from_measurements()
        self.start_guided_measurement(int(tooth_fdi))

    def _resume_guided_after_loading(self) -> None:
        """STL yükleme sonrası uygun çenede rehberli seçimi yeniden başlatır."""
        if self.arch_mode_active or self.guided_active:
            return

        max_remaining = [
            tooth for tooth in self.guided_sequences["maxillary"]
            if tooth not in self.completed_teeth["maxillary"] and tooth not in self.missing_teeth["maxillary"]
        ]
        mand_remaining = [
            tooth for tooth in self.guided_sequences["mandibular"]
            if tooth not in self.completed_teeth["mandibular"] and tooth not in self.missing_teeth["mandibular"]
        ]

        if self.maxilla_mesh is not None and max_remaining:
            self.start_guided_measurement(max_remaining[0])
            return

        if self.mandible_mesh is not None and mand_remaining:
            self.start_guided_measurement(mand_remaining[0])

    def _redraw_saved_measurements(self) -> None:
        """Kaydedilmiş diş ölçümlerini sahnede yeniden çizer."""
        if self.measurement_panel.df.empty:
            return

        for _, row in self.measurement_panel.df.iterrows():
            jaw = str(row["jaw"])
            tooth_fdi = int(row["tooth_fdi"])
            viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
            if row["mesial_xyz"] is None or row["distal_xyz"] is None:
                continue
            mesial_pt = np.asarray(row["mesial_xyz"], dtype=np.float64)
            distal_pt = np.asarray(row["distal_xyz"], dtype=np.float64)
            width_mm = float(row["width_mm"])
            viewer.add_point_marker(
                mesial_pt,
                color="#06D6A0",
                label="M",
                radius=0.25,
                name=f"guided_mesial_{tooth_fdi}",
            )
            viewer.add_point_marker(
                distal_pt,
                color="#FFD166",
                label="D",
                radius=0.25,
                name=f"guided_distal_{tooth_fdi}",
            )
            viewer.add_measurement_line(
                mesial_pt,
                distal_pt,
                label=f"{width_mm:.2f} mm",
                color="#06D6A0",
                name=f"guided_line_{tooth_fdi}",
            )

    def _restore_partial_guided_visuals(self) -> None:
        """Yarım kalmış guided seçimleri sahnede yeniden gösterir."""
        if not self.guided_active or self.guided_jaw is None:
            return

        tooth_fdi = self._guided_current_tooth()
        if tooth_fdi is None:
            return

        viewer = self._activate_guided_viewer(self.guided_jaw)
        self._clear_guided_actors(viewer, tooth_fdi, render=False)

        if self.guided_mesial_point is not None:
            viewer.add_point_marker(
                self.guided_mesial_point,
                color="#06D6A0",
                label="M",
                radius=0.25,
                name=f"guided_mesial_{tooth_fdi}",
                render=False,
            )

        if self.guided_step == "mesial" and self.guided_pending_point is not None:
            viewer.add_point_marker(
                self.guided_pending_point,
                color="#06D6A0",
                label="M?",
                radius=0.25,
                name=f"guided_mesial_{tooth_fdi}",
                render=False,
            )

        if self.guided_step == "distal" and self.guided_pending_point is not None and self.guided_mesial_point is not None:
            viewer.add_point_marker(
                self.guided_pending_point,
                color="#FFD166",
                label="D?",
                radius=0.25,
                name=f"guided_distal_{tooth_fdi}",
                render=False,
            )
            viewer.add_measurement_line(
                self.guided_mesial_point,
                self.guided_pending_point,
                label=f"{euclidean_distance_3d(self.guided_mesial_point, self.guided_pending_point):.2f} mm",
                color="#06D6A0",
                name=f"guided_line_{tooth_fdi}",
                render=False,
            )
        self._update_guided_draggable_markers(self.guided_jaw, tooth_fdi)
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass

    def _restore_arch_preview_visuals(self) -> None:
        """Yarım kalmış ark boyu seçim önizlemesini yeniden çizer."""
        if not self.arch_mode_active or self.arch_mode_jaw is None:
            return

        viewer = self._activate_guided_viewer(self.arch_mode_jaw)
        self._clear_arch_preview(self.arch_mode_jaw)
        viewer.set_overlay_hint(
            "Ark boyunca sırasıyla noktalar yerleştirin. Son noktayı silmek için Backspace, bitirmek için Space basın."
        )
        for idx, pt in enumerate(self.arch_points):
            viewer.add_point_marker(
                pt,
                color="#0EA5A4",
                radius=0.22,
                label=str(idx + 1),
                name=f"arch_point_{self.arch_mode_jaw}_{idx}",
                render=False,
            )
            if idx > 0:
                segment_length = euclidean_distance_3d(self.arch_points[idx - 1], pt)
                viewer.add_measurement_line(
                    self.arch_points[idx - 1],
                    pt,
                    label=f"{segment_length:.2f} mm",
                    color="#38BDF8",
                    name=f"arch_seg_{self.arch_mode_jaw}_{idx}",
                    render=False,
                )
        self._update_arch_draggable_markers()
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass

    def _load_stl_from_path(self, target: str, file_path: str, *, allow_resume: bool = True) -> bool:
        """Verilen STL yolunu yükler ve ilgili viewer'a yerleştirir."""
        if not file_path:
            return False

        viewer = self.viewer_maxilla if target == "maxilla" else self.viewer_mandible
        ark_label = "Üst Çene (Maksilla)" if target == "maxilla" else "Alt Çene (Mandibula)"
        filename = os.path.basename(file_path)

        self.statusBar().showMessage(f"⏳ {ark_label} yükleniyor... Lütfen bekleyin.", 0)
        viewer.show_loading_state(f"{ark_label} yükleniyor...\nSTL dosyası okunuyor ve 3D sahne hazırlanıyor.")
        QApplication.processEvents()

        mesh = STLLoader.load(file_path)
        info = STLLoader.get_mesh_info(mesh)
        viewer.display_mesh(mesh)

        if target == "maxilla":
            self.maxilla_mesh = mesh
            self._maxilla_filename = filename
            self._maxilla_path = file_path
            self.lbl_maxilla_file.setText(f"MAKSILLA • {filename}")
            self.viewer_maxilla.configure_odontogram("maxillary", self.guided_sequences["maxillary"])
            self.viewer_maxilla.set_overlay_hint("Maksilla yuklendi. Sol tik ile secin, Space ile ilerleyin.")
            self._set_view_mode("maxillary")
        else:
            self.mandible_mesh = mesh
            self._mandible_filename = filename
            self._mandible_path = file_path
            self.lbl_mandible_file.setText(f"MANDIBULA • {filename}")
            self.viewer_mandible.configure_odontogram("mandibular", self.guided_sequences["mandibular"])
            self.viewer_mandible.set_overlay_hint("Mandibula yuklendi. Sol tik ile secin, Space ile ilerleyin.")
            self._set_view_mode("mandibular")

        if self.maxilla_mesh is not None and self.mandible_mesh is not None:
            self._refresh_occlusion_view()

        self._refresh_toolbar_availability()
        self._sync_dashboard_from_measurements()
        if allow_resume:
            self._resume_guided_after_loading()
        viewer.clear_state_message()
        self.statusBar().showMessage(
            f"✅ {ark_label} yüklendi: {filename} "
            f"({info['yuzey_sayisi']:,} yüzey, "
            f"{info['genislik_mm']:.1f}×{info['yukseklik_mm']:.1f}×{info['derinlik_mm']:.1f} mm)",
            8000
        )
        return True

    def _apply_session_payload(
        self,
        payload: dict,
        *,
        source_label: str = "Oturum",
        persist_as_autosave: bool = True,
    ) -> None:
        """Kaydedilmiş oturumu uygulamaya anında uygular."""
        self._restoring_session = True
        restored_mesh = False
        try:
            self._reset_guided_measurement_state()
            self._cancel_arch_perimeter_mode()
            self.viewer_maxilla.clear()
            self.viewer_mandible.clear()
            self.viewer_occlusion.clear()
            self.measurement_panel.clear_all()

            self.maxilla_mesh = None
            self.mandible_mesh = None
            self._maxilla_filename = ""
            self._mandible_filename = ""
            self._maxilla_path = ""
            self._mandible_path = ""
            self.lbl_maxilla_file.setText("MAKSILLA • Yüklenmedi")
            self.lbl_mandible_file.setText("MANDIBULA • Yüklenmedi")
            self.completed_teeth = {"maxillary": set(), "mandibular": set()}
            self.missing_teeth = {"maxillary": set(), "mandibular": set()}
            self.arch_lengths = {"maxillary": None, "mandibular": None}
            self.arch_paths = {"maxillary": [], "mandibular": []}
            self._show_home_page()

            maxilla_path = payload.get("maxilla_path") or ""
            mandible_path = payload.get("mandible_path") or ""
            self._maxilla_filename = payload.get("maxilla_filename") or ""
            self._mandible_filename = payload.get("mandible_filename") or ""
            self._maxilla_path = maxilla_path
            self._mandible_path = mandible_path

            if self._maxilla_filename:
                self.lbl_maxilla_file.setText(f"MAKSILLA • {self._maxilla_filename}")
            if self._mandible_filename:
                self.lbl_mandible_file.setText(f"MANDIBULA • {self._mandible_filename}")

            if maxilla_path and os.path.exists(maxilla_path):
                restored_mesh = self._load_stl_from_path("maxilla", maxilla_path, allow_resume=False) or restored_mesh
            if mandible_path and os.path.exists(mandible_path):
                restored_mesh = self._load_stl_from_path("mandible", mandible_path, allow_resume=False) or restored_mesh

            rows = payload.get("measurement_rows") or []
            if rows:
                self.measurement_panel.df = pd.DataFrame(rows)
                self.measurement_panel._refresh_table()
                self.measurement_panel._update_bolton_summary()
                self.measurement_panel._update_button_states()
                self.measurement_panel._update_progress()
                self.measurement_panel._check_completion()

            self.completed_teeth = {
                "maxillary": set(int(tooth) for tooth in (payload.get("completed_teeth", {}).get("maxillary") or [])),
                "mandibular": set(int(tooth) for tooth in (payload.get("completed_teeth", {}).get("mandibular") or [])),
            }
            self.missing_teeth = {
                "maxillary": set(int(tooth) for tooth in (payload.get("missing_teeth", {}).get("maxillary") or [])),
                "mandibular": set(int(tooth) for tooth in (payload.get("missing_teeth", {}).get("mandibular") or [])),
            }
            self.arch_lengths = {
                "maxillary": payload.get("arch_lengths", {}).get("maxillary"),
                "mandibular": payload.get("arch_lengths", {}).get("mandibular"),
            }
            self.arch_paths = {
                "maxillary": [
                    np.asarray(point, dtype=np.float64)
                    for point in (payload.get("arch_paths", {}).get("maxillary") or [])
                    if point is not None
                ],
                "mandibular": [
                    np.asarray(point, dtype=np.float64)
                    for point in (payload.get("arch_paths", {}).get("mandibular") or [])
                    if point is not None
                ],
            }

            self.guided_active = bool(payload.get("guided_active"))
            self.guided_jaw = payload.get("guided_jaw")
            self.guided_sequence = [int(tooth) for tooth in (payload.get("guided_sequence") or [])]
            self.guided_index = int(payload.get("guided_index", -1))
            self.guided_step = payload.get("guided_step") or ""

            guided_mesial = payload.get("guided_mesial_point")
            guided_distal = payload.get("guided_distal_point")
            guided_pending = payload.get("guided_pending_point")
            self.guided_mesial_point = None if guided_mesial is None else np.asarray(guided_mesial, dtype=np.float64)
            self.guided_distal_point = None if guided_distal is None else np.asarray(guided_distal, dtype=np.float64)
            self.guided_pending_point = None if guided_pending is None else np.asarray(guided_pending, dtype=np.float64)

            self.arch_mode_active = bool(payload.get("arch_mode_active"))
            self.arch_mode_jaw = payload.get("arch_mode_jaw")
            self.arch_points = [
                np.asarray(point, dtype=np.float64)
                for point in (payload.get("arch_points") or [])
                if point is not None
            ]
            self.current_view_mode = payload.get("view_mode") or "maxillary"
            self.active_navigation_tool = payload.get("active_navigation_tool") or "rotate"

            self._sync_dashboard_from_measurements()
            self._refresh_toolbar_availability()

            if restored_mesh:
                self._set_navigation_tool(self.active_navigation_tool)
                if self.current_view_mode == "occlusion" and (
                    self.maxilla_mesh is None or self.mandible_mesh is None
                ):
                    self.current_view_mode = "maxillary" if self.maxilla_mesh is not None else "mandibular"
                self._set_view_mode(self.current_view_mode)
                self._redraw_saved_measurements()
                if self.guided_active:
                    self._restore_partial_guided_visuals()
                    tooth_fdi = self._guided_current_tooth()
                    if tooth_fdi is not None and self.guided_jaw is not None:
                        prompt = (
                            f"📍 DİŞ {tooth_fdi} | Lütfen dişin MEZİAL noktasını seçin."
                            if self.guided_step != "distal"
                            else f"📍 DİŞ {tooth_fdi} | Lütfen dişin DİSTAL noktasını seçin."
                        )
                        self._prompt_next_guided_step(tooth_fdi, self.guided_jaw, prompt)
                elif self.arch_mode_active and self.arch_mode_jaw is not None:
                    self._restore_arch_preview_visuals()
                    self._show_arch_page(self.arch_mode_jaw)
                    self.lbl_active_mode.setText(
                        f"Aktif: {'Üst' if self.arch_mode_jaw == 'maxillary' else 'Alt'} Ark Boyu"
                    )
                    self.lbl_active_step.setText(
                        "Oturum geri yüklendi. Ark boyu ölçümüne kaldığınız yerden devam edebilirsiniz."
                    )
                    self._set_guided_status(
                        "⏳ Oturum geri yüklendi. Son noktayı silmek için Backspace, tamamlamak için Space basın."
                    )
            else:
                self._show_home_page()

            if persist_as_autosave:
                with self._session_path.open("w", encoding="utf-8") as fp:
                    json.dump(payload, fp, ensure_ascii=False, indent=2)
        finally:
            self._restoring_session = False

        if restored_mesh:
            self.statusBar().showMessage(f"{source_label} geri yüklendi.", 6000)
        elif payload.get("measurement_rows"):
            self.statusBar().showMessage(
                f"{source_label} geri yüklendi. Ölçüler geldi; 3D sahne için STL dosyalarını tekrar seçebilirsiniz.",
                8000
            )
        else:
            self.statusBar().showMessage(f"{source_label} yüklendi.", 5000)

    def _restore_autosave_session(self) -> None:
        """Varsa son otomatik kaydı geri yükler."""
        if not self._session_path.exists():
            return

        try:
            with self._session_path.open("r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except Exception as exc:
            print(f"[MainWindow] Autosave okunamadı: {exc}", flush=True)
            return
        try:
            self._apply_session_payload(
                payload,
                source_label="Son çalışma oturumu",
                persist_as_autosave=False,
            )
        except Exception as exc:
            print(f"[MainWindow] Autosave geri yüklenemedi: {exc}", flush=True)

    def _build_report_overlay(self) -> None:
        """Rapor oluşturma sırasında gösterilen yarı saydam yükleme katmanı."""
        self.report_overlay = QFrame(self.central_root)
        self.report_overlay.setStyleSheet("""
            QFrame {
                background-color: rgba(7, 10, 17, 0.72);
                border-radius: 0;
            }
            QLabel {
                color: #FFFFFF;
            }
        """)
        self.report_overlay.hide()

        card = QFrame(self.report_overlay)
        card.setObjectName("report_overlay_card")
        card.setStyleSheet("""
            QFrame#report_overlay_card {
                background-color: #161B27;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 24px;
            }
            QLabel {
                color: #E2E8F0;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(14)

        self.report_overlay_title = QLabel("⏳ SelçukBolt raporu hazırlanıyor...")
        self.report_overlay_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.report_overlay_title.setStyleSheet("font-size: 22px; font-weight: 700;")
        card_layout.addWidget(self.report_overlay_title)

        self.report_overlay_subtitle = QLabel("Lütfen bekleyin. Ölçümler analiz edilip rapor oluşturuluyor.")
        self.report_overlay_subtitle.setWordWrap(True)
        self.report_overlay_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.report_overlay_subtitle.setStyleSheet("font-size: 13px; color: #94A3B8;")
        card_layout.addWidget(self.report_overlay_subtitle)

        self.report_overlay_bar = QProgressBar()
        self.report_overlay_bar.setRange(0, 0)
        self.report_overlay_bar.setTextVisible(False)
        self.report_overlay_bar.setFixedHeight(10)
        self.report_overlay_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0F1520;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 5px;
            }
        """)
        card_layout.addWidget(self.report_overlay_bar)

        card.resize(520, 180)
        self.report_overlay_card = card

    def _show_home_page(self) -> None:
        """Varsayılan görünüm olarak maksillayı açar."""
        self._set_view_mode("maxillary")

    def _show_arch_page(self, jaw: str) -> None:
        """Normal çalışma modunda ilgili çeneyi tek başına gösterir."""
        self._set_view_mode(jaw)

    def _set_view_mode(self, mode: str) -> None:
        """Görünüm modunu maksilla / mandibula / kapanış olarak değiştirir."""
        if mode == "occlusion":
            if self.maxilla_mesh is None or self.mandible_mesh is None:
                QMessageBox.information(
                    self,
                    "Kapanış Görünümü Hazır Değil",
                    "Kapanış görünümü için hem maksilla hem mandibula STL dosyalarını yükleyin."
                )
                return
            self._refresh_occlusion_view()
            self.viewer_stack.setCurrentWidget(self.viewer_occlusion)
            self.current_view_mode = "occlusion"
            self.lbl_active_mode.setText("KAPANIŞ • Oklüzyon Görünümü")
            self.statusBar().showMessage("Kapanış görünümü aktif.", 2500)
        elif mode == "mandibular":
            self.viewer_stack.setCurrentWidget(self.viewer_mandible)
            self.current_view_mode = "mandibular"
            self.lbl_active_mode.setText("MANDIBULA • Landmark Çalışma Alanı")
            self.statusBar().showMessage("Mandibula görünümü aktif.", 2500)
        else:
            self.viewer_stack.setCurrentWidget(self.viewer_maxilla)
            self.current_view_mode = "maxillary"
            self.lbl_active_mode.setText("MAKSILLA • Landmark Çalışma Alanı")
            self.statusBar().showMessage("Maksilla görünümü aktif.", 2500)

        if hasattr(self, "action_view_maxilla"):
            self.action_view_maxilla.setChecked(self.current_view_mode == "maxillary")
            self.action_view_mandible.setChecked(self.current_view_mode == "mandibular")
            self.action_view_occlusion.setChecked(self.current_view_mode == "occlusion")

        if self.model_focus_mode:
            self._apply_model_focus_layout(self.current_view_mode)
        self._refresh_arch_button_state()
        self._refresh_toolbar_availability()
        self._autosave_session()

    def _refresh_occlusion_view(self) -> None:
        """İki çeneyi tek sahnede kapanış görünümüyle yeniden çizer."""
        if self.maxilla_mesh is None or self.mandible_mesh is None:
            return

        self.viewer_occlusion.display_occlusion_meshes(
            self.maxilla_mesh,
            self.mandible_mesh,
        )
        self.viewer_occlusion.set_overlay_hint(
            "Kapanış görünümü aktif. İki çenenin ilişkisini birlikte inceleyebilirsiniz."
        )

    def _set_navigation_tool(self, tool_name: str) -> None:
        """Toolbar'daki aktif navigasyon aracını günceller."""
        self.active_navigation_tool = tool_name
        if hasattr(self, "action_tool_rotate"):
            self.action_tool_rotate.setChecked(tool_name == "rotate")
            self.action_tool_pan.setChecked(tool_name == "pan")
            self.action_tool_zoom.setChecked(tool_name == "zoom")
        tool_label = {
            "rotate": "Döndür",
            "pan": "Taşı / Pan",
            "zoom": "Yakınlaştır / Uzaklaştır",
        }.get(tool_name, "Döndür")
        self.lbl_viewer_hint.setText(
            f"Araç: {tool_label} • Sol tık: seçim • Sağ tık: döndür • Trackpad/tekerlek: zoom"
        )
        for viewer in (self.viewer_maxilla, self.viewer_mandible, self.viewer_occlusion):
            viewer.set_navigation_mode(tool_name)
        self.statusBar().showMessage(f"Araç değişti: {tool_label}", 2000)
        self._autosave_session()

    def _apply_model_focus_layout(self, jaw: str) -> None:
        """Aktif görünümü büyütmek için yan panelleri gizler."""
        self.left_panel.setVisible(False)
        self.right_panel.setVisible(False)
        self.btn_model_focus.setText("Normal Görünüm")
        if jaw == "occlusion":
            self.viewer_stack.setCurrentWidget(self.viewer_occlusion)
        elif jaw == "mandibular":
            self.viewer_stack.setCurrentWidget(self.viewer_mandible)
        else:
            self.viewer_stack.setCurrentWidget(self.viewer_maxilla)

    def _restore_standard_layout(self) -> None:
        """Standart düzeni geri getirir."""
        self.left_panel.setVisible(True)
        self.right_panel.setVisible(True)
        self.btn_model_focus.setText("Odak Modu")
        self._apply_workspace_splitter_sizes()
        self._set_view_mode(self.current_view_mode)

    def _current_active_jaw(self) -> str:
        """Şu anda odakta olan çeneyi döndürür."""
        if self.current_view_mode in {"maxillary", "mandibular"}:
            return self.current_view_mode
        return self.guided_jaw or self.arch_mode_jaw or "maxillary"

    def _toggle_model_focus_mode(self) -> None:
        """Yan panelleri gizleyip aktif modeli büyük gösterir."""
        self.model_focus_mode = not self.model_focus_mode
        if self.model_focus_mode:
            self._apply_model_focus_layout(self._current_active_jaw())
        else:
            self._restore_standard_layout()

    def _toggle_window_fullscreen(self) -> None:
        """Pencereyi işletim sistemi seviyesinde tam ekrana alır/çıkarır."""
        self.window_fullscreen_mode = not self.window_fullscreen_mode
        if self.window_fullscreen_mode:
            self.showFullScreen()
        else:
            self.showNormal()
            self.resize(1700, 900)

    def _exit_fullscreen_views(self) -> None:
        """Escape ile odak modu ve pencere tam ekranını kapatır."""
        if self.model_focus_mode:
            self.model_focus_mode = False
            self._restore_standard_layout()
        if self.window_fullscreen_mode:
            self.window_fullscreen_mode = False
            self.showNormal()
            self.resize(1700, 900)
            self.viewer_mandible.setStyleSheet("""
                MeshViewer {
                    border: 1px solid #D7E3EA;
                    border-radius: 14px;
                    background-color: #FFFFFF;
                }
            """)
        else:
            self.viewer_maxilla.setStyleSheet("""
                MeshViewer {
                    border: 1px solid #D7E3EA;
                    border-radius: 14px;
                    background-color: #FFFFFF;
                }
            """)
            self.viewer_mandible.setStyleSheet("""
                MeshViewer {
                    border: 2px solid #2F80ED;
                    border-radius: 14px;
                    background-color: #FFFFFF;
                }
            """)

    # ──────────────────────────────────────────────
    # SİNYAL BAĞLANTILARI
    # ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """
        Ölçüm paneli ve 3D görüntüleyiciler arasındaki sinyal bağlantılarını kurar.
        """
        # Ölçüm paneli → nokta seçim modu başlat
        self.measurement_panel.picking_requested.connect(self._on_picking_requested)

        # 3D görüntüleyiciler → nokta seçildi (panale devret)
        self.viewer_maxilla.point_picked.connect(self._on_point_picked_maxilla)
        self.viewer_mandible.point_picked.connect(self._on_point_picked_mandible)
        self.viewer_maxilla.marker_moved.connect(
            lambda marker_name, point: self._on_viewer_marker_moved(
                self.viewer_maxilla,
                marker_name,
                point,
            )
        )
        self.viewer_mandible.marker_moved.connect(
            lambda marker_name, point: self._on_viewer_marker_moved(
                self.viewer_mandible,
                marker_name,
                point,
            )
        )
        self.viewer_maxilla.tooth_selected.connect(self.start_guided_measurement)
        self.viewer_mandible.tooth_selected.connect(self.start_guided_measurement)
        self.viewer_maxilla.arch_perimeter_requested.connect(
            lambda: self.start_arch_perimeter_measurement("maxillary")
        )
        self.viewer_mandible.arch_perimeter_requested.connect(
            lambda: self.start_arch_perimeter_measurement("mandibular")
        )
        self.viewer_maxilla.next_stage_requested.connect(self._switch_to_mandible_stage)
        self.viewer_mandible.finish_requested.connect(self._finish_and_report)

        # Ölçüm tamamlandı
        self.measurement_panel.measurement_complete.connect(self._on_all_complete)
        
        # Panel -> Viewer Çizim ve Kontrol Komutları
        self.measurement_panel.draw_marker_requested.connect(self._on_draw_marker)
        self.measurement_panel.draw_line_requested.connect(self._on_draw_line)
        self.measurement_panel.picking_finished.connect(self._on_picking_finished)

    def _reset_guided_measurement_state(self) -> None:
        """Rehberli ölçüm durum makinesini temizler."""
        self.guided_active = False
        self.guided_sequence = []
        self.guided_index = -1
        self.guided_step = ""
        self.guided_jaw = None
        self.guided_mesial_point = None
        self.guided_distal_point = None
        self.guided_pending_point = None

        self.viewer_maxilla.disable_picking()
        self.viewer_mandible.disable_picking()
        self.viewer_maxilla.hide_active_tooth_label()
        self.viewer_mandible.hide_active_tooth_label()
        self.viewer_maxilla.set_active_tooth(None)
        self.viewer_mandible.set_active_tooth(None)
        self.viewer_maxilla.set_draggable_marker_names(set())
        self.viewer_mandible.set_draggable_marker_names(set())

        self.measurement_panel._active_fdi = None
        self.measurement_panel._active_jaw = None
        self.measurement_panel._picking_active = False
        self.measurement_panel._current_step = ""
        self.measurement_panel._update_button_states()

    def _set_guided_status(self, message: str) -> None:
        """Rehberli akış için durum çubuğunu ve panel bilgisini senkron tutar."""
        self.statusBar().showMessage(message, 0)
        self.measurement_panel.status_label.setText(message)
        self.measurement_panel.status_label.setStyleSheet("""
            QLabel {
                color: #0F4C5C;
                background-color: #ECFDFF;
                padding: 8px;
                border-radius: 10px;
                font-size: 11px;
                border: 1px solid #B9E6F2;
            }
        """)

    def _prompt_next_guided_step(
        self,
        tooth_fdi: int,
        jaw: str,
        message: str,
    ) -> None:
        """Aktif dişi, layout odağını ve durum mesajını birlikte günceller."""
        self._show_arch_page(jaw)
        active_viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        inactive_viewer = self.viewer_mandible if jaw == "maxillary" else self.viewer_maxilla
        active_viewer.show_active_tooth_label(tooth_fdi)
        active_viewer.set_active_tooth(tooth_fdi)
        active_viewer.set_completed_teeth(sorted(self.completed_teeth[jaw]))
        active_viewer.set_overlay_hint(message)
        inactive_viewer.hide_active_tooth_label()
        inactive_viewer.set_active_tooth(None)
        self.lbl_active_step.setText(message)
        self.lbl_active_mode.setText(
            f"Aktif: {'Üst Çene' if jaw == 'maxillary' else 'Alt Çene'} | Diş {tooth_fdi}"
        )
        self._set_guided_status(message)
        self._autosave_session()

    def _get_guided_tooth_jaw(self, tooth_fdi: int) -> str:
        """FDI numarasından çeneyi belirler."""
        return "maxillary" if tooth_fdi in MAXILLARY_OVERALL else "mandibular"

    def _activate_guided_viewer(self, jaw: str) -> MeshViewer:
        """Sadece aktif çenenin görüntüleyicisinde picking açık kalsın."""
        self.viewer_maxilla.disable_picking()
        self.viewer_mandible.disable_picking()

        viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        viewer.enable_picking()
        return viewer

    def _update_guided_draggable_markers(self, jaw: str, tooth_fdi: int) -> None:
        """Yalnızca aktif dişin marker'larını sürüklenebilir yapar."""
        marker_names = {f"guided_mesial_{tooth_fdi}"}
        if self.guided_step == "distal":
            marker_names.add(f"guided_distal_{tooth_fdi}")

        active_viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        inactive_viewer = self.viewer_mandible if jaw == "maxillary" else self.viewer_maxilla
        active_viewer.set_draggable_marker_names(marker_names)
        inactive_viewer.set_draggable_marker_names(set())

    def _update_arch_draggable_markers(self) -> None:
        """Ark boyu modundaki mevcut noktaları sürüklenebilir yapar."""
        marker_names = (
            {
                f"arch_point_{self.arch_mode_jaw}_{idx}"
                for idx in range(len(self.arch_points))
            }
            if self.arch_mode_active and self.arch_mode_jaw is not None
            else set()
        )
        self.viewer_maxilla.set_draggable_marker_names(
            marker_names if self.arch_mode_jaw == "maxillary" else set()
        )
        self.viewer_mandible.set_draggable_marker_names(
            marker_names if self.arch_mode_jaw == "mandibular" else set()
        )

    def start_guided_measurement(self, start_tooth_fdi: Optional[int] = None) -> None:
        """Aktif çene için rehberli diş ölçüm akışını başlatır."""
        if start_tooth_fdi is None:
            if self.maxilla_mesh is not None and (
                len(self.completed_teeth["maxillary"]) + len(self.missing_teeth["maxillary"])
            ) < len(self.guided_sequences["maxillary"]):
                jaw = "maxillary"
            elif self.mandible_mesh is not None and (
                len(self.completed_teeth["mandibular"]) + len(self.missing_teeth["mandibular"])
            ) < len(self.guided_sequences["mandibular"]):
                jaw = "mandibular"
            else:
                QMessageBox.information(
                    self,
                    "Ölçüm Hazır",
                    "Tüm diş ölçümleri tamamlanmış görünüyor. Ark boyu ölçümüne veya rapora geçebilirsiniz."
                )
                return
            remaining = [
                tooth for tooth in self.guided_sequences[jaw]
                if tooth not in self.completed_teeth[jaw] and tooth not in self.missing_teeth[jaw]
            ]
            if not remaining:
                return
            start_tooth_fdi = remaining[0]
        else:
            jaw = self._get_guided_tooth_jaw(int(start_tooth_fdi))

        if jaw == "maxillary" and self.maxilla_mesh is None:
            QMessageBox.warning(
                self,
                "STL Eksik",
                "Seçtiğiniz diş için önce üst çene STL dosyasını yükleyin."
            )
            return
        if jaw == "mandibular" and self.mandible_mesh is None:
            QMessageBox.warning(
                self,
                "STL Eksik",
                "Seçtiğiniz diş için önce alt çene STL dosyasını yükleyin."
            )
            return

        if self.arch_mode_active:
            self._cancel_arch_perimeter_mode()

        if self.measurement_panel.is_picking_active:
            self.measurement_panel._cancel_measurement()

        self._reset_guided_measurement_state()
        self.guided_active = True
        self.guided_jaw = jaw
        self.missing_teeth[jaw].discard(int(start_tooth_fdi))
        self._remove_tooth_row(int(start_tooth_fdi))
        base_sequence = list(self.guided_sequences[jaw])
        start_index = base_sequence.index(int(start_tooth_fdi))
        self.guided_sequence = base_sequence[start_index:] + base_sequence[:start_index]
        self.guided_index = 0
        self._advance_guided_measurement()

    def _advance_guided_measurement(self) -> None:
        """Sıradaki rehberli ölçüm dişini ve adımını hazırlar."""
        if not self.guided_active or self.guided_jaw is None:
            return

        while (
            self.guided_index < len(self.guided_sequence)
            and (
                self.guided_sequence[self.guided_index] in self.completed_teeth[self.guided_jaw]
                or self.guided_sequence[self.guided_index] in self.missing_teeth[self.guided_jaw]
            )
        ):
            self.guided_index += 1

        if self.guided_index >= len(self.guided_sequence):
            self._finish_guided_measurement()
            return

        tooth_fdi = self.guided_sequence[self.guided_index]
        jaw = self.guided_jaw
        mesh = self.maxilla_mesh if jaw == "maxillary" else self.mandible_mesh
        if mesh is None:
            QMessageBox.warning(
                self,
                "STL Eksik",
                f"Rehberli akış devam edemedi. {'Üst' if jaw == 'maxillary' else 'Alt'} çene STL dosyası eksik."
            )
            self._reset_guided_measurement_state()
            return

        self.guided_jaw = jaw
        self.guided_step = "mesial"
        self.guided_mesial_point = None
        self.guided_distal_point = None
        self.guided_pending_point = None

        self.measurement_panel._active_fdi = tooth_fdi
        self.measurement_panel._active_jaw = jaw
        self.measurement_panel._update_button_states()

        self._activate_guided_viewer(jaw)
        self._update_guided_draggable_markers(jaw, tooth_fdi)
        active_viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        active_viewer.set_arch_measure_visible(False)
        active_viewer.set_next_stage_visible(False)
        active_viewer.set_finish_visible(False)
        self._prompt_next_guided_step(
            tooth_fdi,
            jaw,
            f"📍 DİŞ {tooth_fdi} | Lütfen dişin MEZİAL noktasını seçin."
        )

    def _guided_current_tooth(self) -> Optional[int]:
        """Rehberli akıştaki aktif diş numarasını döndürür."""
        if 0 <= self.guided_index < len(self.guided_sequence):
            return self.guided_sequence[self.guided_index]
        return None

    def _guided_previous_processed_index(self) -> Optional[int]:
        """Mevcut indeksin gerisindeki en son işlenmiş dişi bulur."""
        if not self.guided_sequence:
            return None

        for idx in range(self.guided_index - 1, -1, -1):
            tooth_fdi = self.guided_sequence[idx]
            jaw = self._get_guided_tooth_jaw(tooth_fdi)
            if tooth_fdi in self.completed_teeth[jaw] or tooth_fdi in self.missing_teeth[jaw]:
                return idx
        return None

    def _restore_previous_tooth_for_edit(self, tooth_fdi: int, jaw: str) -> None:
        """Bir önceki ölçülmüş dişi distal adımına geri alır."""
        viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        row = self.measurement_panel.df[self.measurement_panel.df["tooth_fdi"] == tooth_fdi]
        if row.empty:
            return

        row = row.iloc[0]
        mesial_pt = np.asarray(row["mesial_xyz"], dtype=np.float64)

        self.measurement_panel.df = self.measurement_panel.df[
            self.measurement_panel.df["tooth_fdi"] != tooth_fdi
        ].reset_index(drop=True)
        self.completed_teeth[jaw].discard(tooth_fdi)
        self.measurement_panel._refresh_table()
        self.measurement_panel._update_bolton_summary()
        self.measurement_panel._update_button_states()
        self.measurement_panel._update_progress()
        self.measurement_panel._check_completion()
        self._sync_dashboard_from_measurements()

        self.guided_jaw = jaw
        self.guided_mesial_point = mesial_pt
        self.guided_distal_point = None
        self.guided_pending_point = None
        self.guided_step = "distal"

        self._show_arch_page(jaw)
        self._activate_guided_viewer(jaw)
        self._clear_guided_actors(viewer, tooth_fdi, render=False)
        viewer.add_point_marker(
            mesial_pt,
            color="#06D6A0",
            label="M",
            radius=0.25,
            name=f"guided_mesial_{tooth_fdi}",
            render=False,
        )
        self._update_guided_draggable_markers(jaw, tooth_fdi)
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass
        self._prompt_next_guided_step(
            tooth_fdi,
            jaw,
            f"↩ DİŞ {tooth_fdi} | Distal geri alındı. Lütfen dişin DİSTAL noktasını yeniden seçin."
        )

    def mark_current_tooth_missing(self) -> None:
        """Aktif dişi arkta mevcut değil olarak işaretler ve sıradaki dişe geçer."""
        if not self.guided_active or self.guided_jaw is None:
            return

        tooth_fdi = self._guided_current_tooth()
        if tooth_fdi is None:
            return

        viewer = self.viewer_maxilla if self.guided_jaw == "maxillary" else self.viewer_mandible
        for actor_name in (
            f"guided_mesial_{tooth_fdi}",
            f"label_guided_mesial_{tooth_fdi}",
            f"guided_distal_{tooth_fdi}",
            f"label_guided_distal_{tooth_fdi}",
            f"guided_line_{tooth_fdi}",
            f"dist_label_guided_line_{tooth_fdi}",
        ):
            viewer.remove_named_actor(actor_name, render=False)

        self.completed_teeth[self.guided_jaw].discard(tooth_fdi)
        self.missing_teeth[self.guided_jaw].add(tooth_fdi)
        self._remove_tooth_row(tooth_fdi)

        estimated_width = self._resolve_missing_tooth_width(tooth_fdi)
        if estimated_width is not None:
            self._upsert_missing_tooth_estimate(tooth_fdi, self.guided_jaw, estimated_width)

        self.measurement_panel._refresh_table()
        self.measurement_panel._update_bolton_summary()
        self.measurement_panel._update_button_states()
        self.measurement_panel._update_progress()
        self.measurement_panel._check_completion()
        self._sync_dashboard_from_measurements()
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass

        self.guided_mesial_point = None
        self.guided_distal_point = None
        self.guided_pending_point = None
        self.guided_step = ""
        if estimated_width is not None:
            viewer.set_overlay_hint(
                f"Diş {tooth_fdi} arkta yok olarak işaretlendi. Bolton için {estimated_width:.2f} mm tahmini kullanılıyor."
            )
            self.lbl_active_step.setText(
                f"Diş {tooth_fdi} eksik. Bolton hesabı için {estimated_width:.2f} mm tahmini eklendi."
            )
        else:
            viewer.set_overlay_hint(
                f"Diş {tooth_fdi} arkta yok olarak işaretlendi. Bolton hesabı için tahmini değer bekleniyor."
            )
            self.lbl_active_step.setText(
                f"Diş {tooth_fdi} eksik olarak işaretlendi. Tahmini değer girilmediği için Bolton hesabı beklemede."
            )
        self.guided_index += 1
        self._advance_guided_measurement()

    def _clear_guided_actors(
        self,
        viewer: MeshViewer,
        tooth_fdi: int,
        *,
        clear_mesial: bool = True,
        clear_distal: bool = True,
        clear_line: bool = True,
        render: bool = False,
    ) -> None:
        """Aktif dişe ait preview/final aktörleri güvenle temizler."""
        actor_names = []
        if clear_mesial:
            actor_names.extend(
                [
                    f"guided_mesial_{tooth_fdi}",
                    f"label_guided_mesial_{tooth_fdi}",
                ]
            )
        if clear_distal:
            actor_names.extend(
                [
                    f"guided_distal_{tooth_fdi}",
                    f"label_guided_distal_{tooth_fdi}",
                ]
            )
        if clear_line:
            actor_names.extend(
                [
                    f"guided_line_{tooth_fdi}",
                    f"dist_label_guided_line_{tooth_fdi}",
                ]
            )

        for actor_name in actor_names:
            viewer.remove_named_actor(actor_name, render=False)

        if render and viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass

    def _handle_guided_picked_point(self, point: np.ndarray, viewer: MeshViewer) -> None:
        """Rehberli ölçüm akışında gelen tekil point pick olayını işler."""
        if not self.guided_active:
            return

        if self.guided_index < 0 or self.guided_index >= len(self.guided_sequence):
            return

        tooth_fdi = self.guided_sequence[self.guided_index]
        jaw = self._get_guided_tooth_jaw(tooth_fdi)
        if jaw != self.guided_jaw:
            return

        pt = np.asarray(point, dtype=np.float64)
        if pt.shape != (3,):
            return

        if self.guided_step == "mesial":
            self._clear_guided_actors(
                viewer,
                tooth_fdi,
                clear_mesial=True,
                clear_distal=True,
                clear_line=True,
            )
            self.guided_pending_point = pt
            viewer.add_point_marker(
                pt,
                color="#06D6A0",
                label="M?",
                radius=0.25,
                name=f"guided_mesial_{tooth_fdi}",
                render=False,
            )
            self._update_guided_draggable_markers(jaw, tooth_fdi)
            if viewer.plotter is not None:
                try:
                    viewer.plotter.render()
                except Exception:
                    pass
            self._prompt_next_guided_step(
                tooth_fdi,
                jaw,
                f"📍 DİŞ {tooth_fdi} | MEZİAL nokta seçildi. Onaylamak için Enter/Space basın veya yeniden tıklayarak düzeltin."
            )
            return

        if self.guided_step != "distal" or self.guided_mesial_point is None:
            return

        width_mm = euclidean_distance_3d(self.guided_mesial_point, pt)
        if width_mm < 0.2:
            return

        self._clear_guided_actors(
            viewer,
            tooth_fdi,
            clear_mesial=False,
            clear_distal=True,
            clear_line=True,
        )
        self.guided_pending_point = pt
        viewer.add_point_marker(
            pt,
            color="#FFD166",
            label="D?",
            radius=0.25,
            name=f"guided_distal_{tooth_fdi}",
            render=False,
        )
        viewer.add_measurement_line(
            self.guided_mesial_point,
            self.guided_pending_point,
            label=f"{width_mm:.2f} mm",
            color="#06D6A0",
            name=f"guided_line_{tooth_fdi}",
            render=False,
        )
        self._update_guided_draggable_markers(jaw, tooth_fdi)
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass
        self._prompt_next_guided_step(
            tooth_fdi,
            jaw,
            f"📍 DİŞ {tooth_fdi} | DİSTAL nokta seçildi ({width_mm:.2f} mm). Onaylamak için Enter/Space basın veya yeniden tıklayarak düzeltin."
        )

    def _on_guided_shortcut_triggered(self) -> None:
        """Enter/Space ile rehberli ölçümde mevcut önizlemeyi onaylar."""
        if self.arch_mode_active:
            self._complete_arch_perimeter_measurement()
            return

        if not self.guided_active or self.guided_pending_point is None:
            return

        tooth_fdi = self._guided_current_tooth()
        if tooth_fdi is None or self.guided_jaw is None:
            return

        viewer = self.viewer_maxilla if self.guided_jaw == "maxillary" else self.viewer_mandible

        if self.guided_step == "mesial":
            self._clear_guided_actors(
                viewer,
                tooth_fdi,
                clear_mesial=True,
                clear_distal=False,
                clear_line=False,
            )
            self.guided_mesial_point = np.asarray(self.guided_pending_point, dtype=np.float64)
            viewer.add_point_marker(
                self.guided_mesial_point,
                color="#06D6A0",
                label="M",
                radius=0.25,
                name=f"guided_mesial_{tooth_fdi}",
                render=False,
            )
            self.guided_pending_point = None
            self.guided_step = "distal"
            self._update_guided_draggable_markers(self.guided_jaw, tooth_fdi)
            if viewer.plotter is not None:
                try:
                    viewer.plotter.render()
                except Exception:
                    pass
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"📍 DİŞ {tooth_fdi} | Lütfen dişin DİSTAL noktasını seçin."
            )
            return

        if self.guided_step != "distal" or self.guided_mesial_point is None:
            return

        self.guided_distal_point = np.asarray(self.guided_pending_point, dtype=np.float64)
        width_mm = euclidean_distance_3d(self.guided_mesial_point, self.guided_distal_point)
        if width_mm < 0.2:
            return

        self._clear_guided_actors(
            viewer,
            tooth_fdi,
            clear_mesial=False,
            clear_distal=True,
            clear_line=True,
        )
        viewer.add_point_marker(
            self.guided_distal_point,
            color="#FFD166",
            label="D",
            radius=0.25,
            name=f"guided_distal_{tooth_fdi}",
            render=False,
        )
        viewer.add_measurement_line(
            self.guided_mesial_point,
            self.guided_distal_point,
            label=f"{width_mm:.2f} mm",
            color="#06D6A0",
            name=f"guided_line_{tooth_fdi}",
            render=False,
        )
        self.guided_pending_point = None
        self._update_guided_draggable_markers(self.guided_jaw, tooth_fdi)
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass

        self._append_guided_measurement(
            jaw=self.guided_jaw,
            tooth_fdi=tooth_fdi,
            mesial_pt=self.guided_mesial_point,
            distal_pt=self.guided_distal_point,
            width_mm=width_mm,
        )
        self.completed_teeth[self.guided_jaw].add(tooth_fdi)
        viewer.set_completed_teeth(sorted(self.completed_teeth[self.guided_jaw]))
        viewer.set_active_tooth(None)

        try:
            self._save_training_data(
                jaw=self.guided_jaw,
                tooth_fdi=tooth_fdi,
                mesial_pt=self.guided_mesial_point,
                distal_pt=self.guided_distal_point,
            )
        except Exception as exc:
            print(f"[MainWindow] Training data kaydı başarısız: {exc}", flush=True)

        self.guided_index += 1
        self._advance_guided_measurement()

    def undo_current_tooth_measurement(self) -> None:
        """Geri almayı adım adım uygular: distal -> mesial -> önceki diş."""
        if self.arch_mode_active:
            self._undo_arch_perimeter_point()
            return

        if not self.guided_active or self.guided_jaw is None:
            return

        tooth_fdi = self._guided_current_tooth()
        if tooth_fdi is None:
            return

        viewer = self.viewer_maxilla if self.guided_jaw == "maxillary" else self.viewer_mandible

        if self.guided_step == "distal" and self.guided_pending_point is not None:
            self._clear_guided_actors(
                viewer,
                tooth_fdi,
                clear_mesial=False,
                clear_distal=True,
                clear_line=True,
                render=True,
            )
            self.guided_pending_point = None
            self.guided_distal_point = None
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"↩ DİŞ {tooth_fdi} | Distal seçim silindi. Lütfen dişin DİSTAL noktasını seçin."
            )
            return

        if self.guided_step == "distal" and self.guided_mesial_point is not None:
            self._clear_guided_actors(
                viewer,
                tooth_fdi,
                clear_mesial=True,
                clear_distal=True,
                clear_line=True,
                render=True,
            )
            self.guided_mesial_point = None
            self.guided_distal_point = None
            self.guided_pending_point = None
            self.guided_step = "mesial"
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"↩ DİŞ {tooth_fdi} | Mesial seçim silindi. Lütfen dişin MEZİAL noktasını yeniden seçin."
            )
            return

        if self.guided_step == "mesial" and self.guided_pending_point is not None:
            self._clear_guided_actors(
                viewer,
                tooth_fdi,
                clear_mesial=True,
                clear_distal=True,
                clear_line=True,
                render=True,
            )
            self.guided_pending_point = None
            self.guided_mesial_point = None
            self.guided_distal_point = None
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"↩ DİŞ {tooth_fdi} | Mesial önizleme silindi. Lütfen dişin MEZİAL noktasını seçin."
            )
            return

        previous_index = self._guided_previous_processed_index()
        if previous_index is None:
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"↩ DİŞ {tooth_fdi} | Geri alınacak önceki ölçüm bulunamadı."
            )
            return

        previous_tooth = self.guided_sequence[previous_index]
        previous_jaw = self._get_guided_tooth_jaw(previous_tooth)
        self.guided_index = previous_index
        self.guided_jaw = previous_jaw

        if previous_tooth in self.missing_teeth[previous_jaw]:
            self.missing_teeth[previous_jaw].discard(previous_tooth)
            self._remove_tooth_row(previous_tooth)
            self.guided_mesial_point = None
            self.guided_distal_point = None
            self.guided_pending_point = None
            self.guided_step = "mesial"
            self.measurement_panel._active_fdi = previous_tooth
            self.measurement_panel._active_jaw = previous_jaw
            self.measurement_panel._update_button_states()
            self._sync_dashboard_from_measurements()
            rewind_viewer = self._activate_guided_viewer(previous_jaw)
            self._clear_guided_actors(rewind_viewer, previous_tooth, render=True)
            self._prompt_next_guided_step(
                previous_tooth,
                previous_jaw,
                f"↩ DİŞ {previous_tooth} | Eksik diş işareti geri alındı. Lütfen dişin MEZİAL noktasını seçin."
            )
            return

        self.measurement_panel._active_fdi = previous_tooth
        self.measurement_panel._active_jaw = previous_jaw
        self.measurement_panel._update_button_states()
        self._restore_previous_tooth_for_edit(previous_tooth, previous_jaw)

    def _append_guided_measurement(
        self,
        jaw: str,
        tooth_fdi: int,
        mesial_pt: np.ndarray,
        distal_pt: np.ndarray,
        width_mm: float,
    ) -> None:
        """Rehberli ölçüm sonucunu MeasurementPanel veri tablosuna işler."""
        panel = self.measurement_panel
        panel.df = panel.df[panel.df["tooth_fdi"] != tooth_fdi].reset_index(drop=True)

        new_row = pd.DataFrame([{
            "tooth_fdi": tooth_fdi,
            "jaw": jaw,
            "mesial_xyz": np.asarray(mesial_pt, dtype=np.float64).tolist(),
            "distal_xyz": np.asarray(distal_pt, dtype=np.float64).tolist(),
            "width_mm": round(float(width_mm), 2),
        }])

        panel.df = pd.concat([panel.df, new_row], ignore_index=True)
        panel._refresh_table()
        panel._update_bolton_summary()
        panel._update_button_states()
        panel._update_progress()
        panel._check_completion()
        self._sync_dashboard_from_measurements()

    def _finish_guided_measurement(self) -> None:
        """Aktif çene tamamlanınca otomatik olarak bir sonraki akışa geçer."""
        finished_jaw = self.guided_jaw
        self._reset_guided_measurement_state()
        if finished_jaw is None:
            return

        viewer = self.viewer_maxilla if finished_jaw == "maxillary" else self.viewer_mandible
        viewer.set_overlay_hint("Bu cenenin olcumleri tamamlandi.")

        if finished_jaw == "maxillary":
            if self.mandible_mesh is not None:
                self._show_arch_page("mandibular")
                self.start_guided_measurement(self.guided_sequences["mandibular"][0])
            else:
                self._show_arch_page("maxillary")
                self._set_guided_status(
                    "Maksilla tamamlandi. Devam etmek icin alt cene STL dosyasini yukleyin."
                )
            return

        self._show_arch_page("mandibular")
        self.viewer_mandible.set_overlay_hint(
            "Tum Bolton olcumleri tamamlandi. Simdi ark boyunu olcebilirsiniz."
        )
        self.lbl_active_step.setText("Tüm Bolton ölçümleri tamamlandı. Ark boyu ölçümü açıldı.")
        self.lbl_active_mode.setText("Aktif: Ark Boyu Hazır")
        self._set_guided_status("Tum rehberli olcumler tamamlandi. Simdi ark boyunu olcun.")
        self._sync_dashboard_from_measurements()

    def _save_training_data(
        self,
        jaw: str,
        tooth_fdi: int,
        mesial_pt: np.ndarray,
        distal_pt: np.ndarray,
    ) -> None:
        """Seçilen landmark çiftlerini JSONL formatında eğitim verisine ekler."""
        dataset_dir = Path(__file__).resolve().parent.parent / "ai_training_data"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = dataset_dir / "landmark_dataset.jsonl"

        stl_filename = self._maxilla_filename if jaw == "maxillary" else self._mandible_filename
        width_mm = euclidean_distance_3d(mesial_pt, distal_pt)

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "stl_file": stl_filename,
            "jaw": jaw,
            "tooth_fdi": tooth_fdi,
            "mesial_xyz": np.asarray(mesial_pt, dtype=np.float64).tolist(),
            "distal_xyz": np.asarray(distal_pt, dtype=np.float64).tolist(),
            "width_mm": round(float(width_mm), 4),
        }

        with dataset_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _cancel_arch_perimeter_mode(self) -> None:
        """Ark boyu çoklu nokta ölçüm modunu kapatır."""
        if self.arch_mode_jaw is not None:
            viewer = self.viewer_maxilla if self.arch_mode_jaw == "maxillary" else self.viewer_mandible
            viewer.disable_picking()
            self._clear_arch_preview(self.arch_mode_jaw)
        self.arch_mode_active = False
        self.arch_mode_jaw = None
        self.arch_points = []
        self._autosave_session()

    def _clear_arch_preview(self, jaw: str) -> None:
        """Ark boyu için eklenen geçici marker ve çizgileri kaldırır."""
        viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        for idx in range(40):
            viewer.remove_named_actor(f"arch_point_{jaw}_{idx}", render=False)
            viewer.remove_named_actor(f"label_arch_point_{jaw}_{idx}", render=False)
            viewer.remove_named_actor(f"arch_seg_{jaw}_{idx}", render=False)
            viewer.remove_named_actor(f"dist_label_arch_seg_{jaw}_{idx}", render=False)
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass
        viewer.set_draggable_marker_names(set())

    def start_arch_perimeter_measurement(self, jaw: str) -> None:
        """Seçili çene için ark boyu polyline ölçüm modunu başlatır."""
        if (len(self.completed_teeth[jaw]) + len(self.missing_teeth[jaw])) < len(self.guided_sequences[jaw]):
            QMessageBox.information(
                self,
                "Diş Ölçümleri Eksik",
                "Ark boyunu ölçmeden önce bu çenedeki tüm diş genişliklerini tamamlayın."
            )
            return

        self._reset_guided_measurement_state()
        self._clear_arch_preview(jaw)
        self.arch_mode_active = True
        self.arch_mode_jaw = jaw
        self.arch_points = []

        viewer = self._activate_guided_viewer(jaw)
        self._update_arch_draggable_markers()
        viewer.set_overlay_hint(
            "Ark boyunca sırasıyla noktalar yerleştirin. Bitirmek için Enter veya Space basın."
        )
        viewer.set_arch_measure_visible(False)
        viewer.set_next_stage_visible(False)
        viewer.set_finish_visible(False)
        self._show_arch_page(jaw)
        self.lbl_active_step.setText(
            f"{'Üst' if jaw == 'maxillary' else 'Alt'} ark boyunca noktalar yerleştirin. Bitirmek için Space basın."
        )
        self._set_guided_status(
            "📐 Ark boyu modu aktif. Ark hattı boyunca noktalar yerleştirin, tamamlayınca Enter/Space basın."
        )
        self._autosave_session()

    def _handle_arch_perimeter_point(self, point: np.ndarray, viewer: MeshViewer) -> None:
        """Ark boyu ölçümünde çoklu nokta girişini toplar ve polyline önizler."""
        if not self.arch_mode_active or self.arch_mode_jaw is None:
            return

        pt = np.asarray(point, dtype=np.float64)
        if pt.shape != (3,):
            return

        idx = len(self.arch_points)
        self.arch_points.append(pt)
        viewer.add_point_marker(
            pt,
            color="#0EA5A4",
            radius=0.22,
            label=str(idx + 1),
            name=f"arch_point_{self.arch_mode_jaw}_{idx}",
            render=False,
        )
        if idx > 0:
            segment_length = euclidean_distance_3d(self.arch_points[idx - 1], pt)
            viewer.add_measurement_line(
                self.arch_points[idx - 1],
                pt,
                label=f"{segment_length:.2f} mm",
                color="#38BDF8",
                name=f"arch_seg_{self.arch_mode_jaw}_{idx}",
                render=False,
            )
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass
        self._update_arch_draggable_markers()

        viewer.set_overlay_hint(
            f"Ark hattı için {len(self.arch_points)} nokta eklendi. Bitirmek için Enter veya Space basın."
        )
        self._autosave_session()

    def _undo_arch_perimeter_point(self) -> None:
        """Ark boyu modunda en son eklenen noktayı ve segmenti geri alır."""
        if not self.arch_mode_active or self.arch_mode_jaw is None:
            return
        if not self.arch_points:
            self._set_guided_status("Ark boyu modunda geri alınacak nokta yok.")
            return

        viewer = self.viewer_maxilla if self.arch_mode_jaw == "maxillary" else self.viewer_mandible
        last_idx = len(self.arch_points) - 1
        self.arch_points.pop()
        viewer.remove_named_actor(f"arch_point_{self.arch_mode_jaw}_{last_idx}", render=False)
        viewer.remove_named_actor(f"label_arch_point_{self.arch_mode_jaw}_{last_idx}", render=False)
        viewer.remove_named_actor(f"arch_seg_{self.arch_mode_jaw}_{last_idx}", render=False)
        viewer.remove_named_actor(f"dist_label_arch_seg_{self.arch_mode_jaw}_{last_idx}", render=False)
        if viewer.plotter is not None:
            try:
                viewer.plotter.render()
            except Exception:
                pass
        self._update_arch_draggable_markers()

        if self.arch_points:
            message = (
                f"↩ Ark boyu | Son nokta silindi. Kalan nokta sayısı: {len(self.arch_points)}. "
                "Devam edin veya Space ile bitirin."
            )
        else:
            message = "↩ Ark boyu | Tüm geçici noktalar silindi. Ark boyunca yeniden nokta seçin."

        viewer.set_overlay_hint(message)
        self.lbl_active_step.setText(message)
        self._set_guided_status(message)
        self._autosave_session()

    def _on_viewer_marker_moved(self, viewer: MeshViewer, marker_name: str, point: np.ndarray) -> None:
        """Sürüklenen aktif marker'ları veri modeline ve önizlemeye yansıtır."""
        pt = np.asarray(point, dtype=np.float64)
        if pt.shape != (3,) or not np.all(np.isfinite(pt)):
            return

        if self.arch_mode_active and self.arch_mode_jaw is not None:
            expected_viewer = self.viewer_maxilla if self.arch_mode_jaw == "maxillary" else self.viewer_mandible
            marker_prefix = f"arch_point_{self.arch_mode_jaw}_"
            if viewer is expected_viewer and marker_name.startswith(marker_prefix):
                try:
                    idx = int(marker_name.removeprefix(marker_prefix))
                except ValueError:
                    return
                if 0 <= idx < len(self.arch_points):
                    self.arch_points[idx] = pt
                    self._restore_arch_preview_visuals()
                    viewer.set_overlay_hint(
                        f"Ark noktasi {idx + 1} guncellendi. Bitirmek icin Enter veya Space basin."
                    )
                    self.lbl_active_step.setText(
                        f"Ark boyu noktasi {idx + 1} hassas olarak guncellendi."
                    )
                    self._set_guided_status(
                        "📐 Ark boyu noktası güncellendi. Gerekirse diğer noktaları da taşıyabilirsiniz."
                    )
                    self._autosave_session()
                return

        if not self.guided_active or self.guided_jaw is None:
            return

        expected_viewer = self.viewer_maxilla if self.guided_jaw == "maxillary" else self.viewer_mandible
        if viewer is not expected_viewer:
            return

        tooth_fdi = self._guided_current_tooth()
        if tooth_fdi is None:
            return

        mesial_name = f"guided_mesial_{tooth_fdi}"
        distal_name = f"guided_distal_{tooth_fdi}"

        if marker_name == mesial_name:
            if self.guided_step == "mesial":
                self.guided_pending_point = pt
            else:
                self.guided_mesial_point = pt
        elif marker_name == distal_name and self.guided_step == "distal":
            self.guided_pending_point = pt
        else:
            return

        self._restore_partial_guided_visuals()

        if self.guided_step == "mesial":
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"📍 DİŞ {tooth_fdi} | MEZİAL nokta güncellendi. Onaylamak için Enter/Space basın veya yeniden sürükleyin."
            )
            return

        if self.guided_pending_point is not None and self.guided_mesial_point is not None:
            width_mm = euclidean_distance_3d(self.guided_mesial_point, self.guided_pending_point)
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"📍 DİŞ {tooth_fdi} | DİSTAL nokta güncellendi ({width_mm:.2f} mm). Onaylamak için Enter/Space basın veya yeniden sürükleyin."
            )
        else:
            self._prompt_next_guided_step(
                tooth_fdi,
                self.guided_jaw,
                f"📍 DİŞ {tooth_fdi} | MEZİAL nokta güncellendi. Lütfen dişin DİSTAL noktasını seçin."
            )

    def _complete_arch_perimeter_measurement(self) -> None:
        """Ark boyu çoklu nokta ölçümünü toplam uzunluk olarak kaydeder."""
        if not self.arch_mode_active or self.arch_mode_jaw is None:
            return
        if len(self.arch_points) < 2:
            QMessageBox.information(
                self,
                "Yetersiz Nokta",
                "Ark boyu ölçümü için en az 2 nokta yerleştirin."
            )
            return

        jaw = self.arch_mode_jaw
        total_length = 0.0
        for idx in range(1, len(self.arch_points)):
            total_length += euclidean_distance_3d(self.arch_points[idx - 1], self.arch_points[idx])

        self.arch_lengths[jaw] = float(total_length)
        self.arch_paths[jaw] = [np.asarray(point, dtype=np.float64).copy() for point in self.arch_points]
        viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        viewer.set_arch_length_value(total_length)
        viewer.set_overlay_hint(f"Ark boyu kaydedildi: {total_length:.2f} mm")
        viewer.disable_picking()

        self.arch_mode_active = False
        self.arch_mode_jaw = None
        self.arch_points = []
        viewer.set_draggable_marker_names(set())

        if jaw == "maxillary":
            self._set_guided_status(
                "✅ Maksilla ark boyu kaydedildi. Gerekirse düzenleyebilir veya alt ark boyuna geçebilirsiniz."
            )
            self.lbl_active_step.setText("Üst ark boyu kaydedildi. Düzenlemek veya alt ark boyuna geçmek için alttaki butonları kullanın.")
        else:
            self._set_guided_status(
                "✅ Mandibula ark boyu kaydedildi. Gerekirse düzenleyebilir veya rapora geçebilirsiniz."
            )
            self.lbl_active_step.setText("Tüm ark ölçümleri tamamlandı. Düzenleyebilir veya rapora geçebilirsiniz.")
        self._sync_dashboard_from_measurements()
        self._autosave_session()

    def _switch_to_mandible_stage(self) -> None:
        """Mandibula ekranına geçer ve gerekirse ilk eksik dişi başlatır."""
        if self.mandible_mesh is None:
            QMessageBox.warning(
                self,
                "Alt Çene STL Eksik",
                "Mandibula aşamasına geçmeden önce alt çene STL dosyasını yükleyin."
            )
            return
        self._show_arch_page("mandibular")
        self.viewer_mandible.set_overlay_hint(
            "Mandibula aşamasına hoş geldiniz. Ölçeceğiniz dişi odontogramdan seçin."
        )
        if (len(self.completed_teeth["mandibular"]) + len(self.missing_teeth["mandibular"])) < len(self.guided_sequences["mandibular"]):
            remaining = [
                tooth for tooth in self.guided_sequences["mandibular"]
                if tooth not in self.completed_teeth["mandibular"] and tooth not in self.missing_teeth["mandibular"]
            ]
            if remaining:
                self.start_guided_measurement(remaining[0])

    def _finish_and_report(self) -> None:
        """Ark boyları tamamlandıktan sonra Excel şablonuna aktarımı başlatır."""
        if self.arch_lengths["maxillary"] is None or self.arch_lengths["mandibular"] is None:
            QMessageBox.information(
                self,
                "Ark Boyu Eksik",
                "Excel çıktısı oluşturmadan önce üst ve alt çene ark boyu ölçümlerini tamamlayın."
            )
            return

        if not self._validate_bolton_calculation_ready():
            return
        self._export_excel_template()

    def _show_report_overlay(self, title: str, subtitle: str) -> None:
        """Yükleme overlay'ini görünür yapar."""
        self.report_overlay_title.setText(title)
        self.report_overlay_subtitle.setText(subtitle)
        self.report_overlay.show()
        self.report_overlay.raise_()
        self._reposition_report_overlay()

    def _hide_report_overlay(self) -> None:
        """Yükleme overlay'ini kapatır."""
        self.report_overlay.hide()

    def _on_report_ready(self, output_path: str) -> None:
        """PDF hazır olduğunda overlay'i kapatır ve dosyayı açar."""
        self._hide_report_overlay()
        self.statusBar().showMessage(f"✅ PDF rapor hazır: {os.path.basename(output_path)}", 8000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(output_path))
        self.report_thread = None

    def _on_report_failed(self, error_message: str) -> None:
        """PDF üretim hatasında kullanıcıyı bilgilendirir."""
        self._hide_report_overlay()
        self.report_thread = None
        QMessageBox.critical(
            self,
            "PDF Hatası",
            f"PDF rapor oluşturulurken hata oluştu:\n\n{error_message}"
        )

    def _reposition_report_overlay(self) -> None:
        """Rapor overlay'ini pencere boyutuna göre ortalar."""
        if not hasattr(self, "report_overlay"):
            return
        self.report_overlay.setGeometry(self.central_root.rect())
        card_width = 520
        card_height = 180
        x = max(24, (self.report_overlay.width() - card_width) // 2)
        y = max(24, (self.report_overlay.height() - card_height) // 2)
        self.report_overlay_card.setGeometry(x, y, card_width, card_height)

    def _on_picking_requested(self, jaw: str) -> None:
        """
        Ölçüm panelinden gelen nokta seçim isteğini işler.
        Doğru görüntüleyicide picking'i etkinleştirir.

        Args:
            jaw: "maxillary" veya "mandibular".
        """
        if self.guided_active:
            self.measurement_panel._cancel_measurement()
            self._set_guided_status(
                "🧭 Rehberli ölçüm aktif. Lütfen yönlendirilen diş sırasını takip edin."
            )
            return

        if jaw == "maxillary":
            if self.maxilla_mesh is None:
                QMessageBox.warning(
                    self,
                    "STL Yüklenmedi",
                    "Üst çene STL dosyası yüklenmemiş.\n"
                    "Lütfen önce '⬆ Üst Çene' butonuyla STL yükleyin."
                )
                self.measurement_panel._cancel_measurement()
                return
            self.viewer_maxilla.enable_picking()
            self.statusBar().showMessage(
                "📍 Maksilla: Mesh üzerinde MEZİAL noktayı işaretleyin (Dişin köşesine tıklayın)",
                0  # Kalıcı
            )
        else:
            if self.mandible_mesh is None:
                QMessageBox.warning(
                    self,
                    "STL Yüklenmedi",
                    "Alt çene STL dosyası yüklenmemiş.\n"
                    "Lütfen önce '⬇ Alt Çene' butonuyla STL yükleyin."
                )
                self.measurement_panel._cancel_measurement()
                return
            self.viewer_mandible.enable_picking()
            self.statusBar().showMessage(
                "📍 Mandibula: Mesh üzerinde MEZİAL noktayı işaretleyin (Dişin köşesine tıklayın)",
                0
            )

    def _on_point_picked_maxilla(self, point: np.ndarray) -> None:
        """Maksilla görüntüleyicisinde seçilen noktayı işler."""
        self._handle_picked_point(point, self.viewer_maxilla)

    def _on_point_picked_mandible(self, point: np.ndarray) -> None:
        """Mandibula görüntüleyicisinde seçilen noktayı işler."""
        self._handle_picked_point(point, self.viewer_mandible)

    def _handle_picked_point(self, point: np.ndarray, viewer: MeshViewer) -> None:
        """
        Görüntüleyiciden gelen nokta tıklamasını doğrudan panele iletir.
        (Eskiden çizim de burada yapılıyordu, ancak manuel düzeltme akışı
         sayesinde artık çizim kararlarını MeasurementPanel veriyor).
        """
        if self.arch_mode_active:
            expected_viewer = (
                self.viewer_maxilla if self.arch_mode_jaw == "maxillary" else self.viewer_mandible
            )
            if viewer is expected_viewer:
                self._handle_arch_perimeter_point(point, viewer)
            return

        if self.guided_active:
            expected_viewer = (
                self.viewer_maxilla if self.guided_jaw == "maxillary" else self.viewer_mandible
            )
            if viewer is expected_viewer:
                self._handle_guided_picked_point(point, viewer)
            return

        if not self.measurement_panel.is_picking_active:
            return

        self.measurement_panel.receive_picked_point(point)

    def _on_draw_marker(self, point: np.ndarray, color: str, label: str, name: str) -> None:
        """MeasurementPanel'dan gelen 'işaretleyici çiz/güncelle' sinyali."""
        viewer = self.viewer_maxilla if self.measurement_panel._active_jaw == "maxillary" else self.viewer_mandible
        if viewer:
            viewer.add_point_marker(point, color=color, label=label, radius=0.25, name=name)

    def _on_draw_line(self, p_a: np.ndarray, p_b: np.ndarray, label: str, color: str) -> None:
        """MeasurementPanel'dan gelen 'ölçüm çizgisi çiz' sinyali."""
        viewer = self.viewer_maxilla if self.measurement_panel._active_jaw == "maxillary" else self.viewer_mandible
        if viewer:
            viewer.add_measurement_line(p_a, p_b, label=label, color=color)

    def _on_picking_finished(self, jaw: str) -> None:
        """MeasurementPanel'dan gelen 'seçim modundan çık' sinyali."""
        viewer = self.viewer_maxilla if jaw == "maxillary" else self.viewer_mandible
        if viewer:
            viewer.disable_picking()

    def _on_all_complete(self) -> None:
        """Tüm diş genişlikleri tamamlandığında kullanıcıyı bilgilendirir."""
        self.statusBar().showMessage(
            "Tum dis genislikleri tamamlandi. Disa Aktar menusu uzerinden rapor alabilirsiniz.",
            0
        )

    # ──────────────────────────────────────────────
    # DURUM ÇUBUĞU
    # ──────────────────────────────────────────────

    def _init_status_bar(self) -> None:
        """Alt durum çubuğunu oluşturur."""
        status = QStatusBar()
        self.setStatusBar(status)

        self.status_info = QLabel("SelçukBolt • Klinik Çalışma Alanı")
        self.status_info.setStyleSheet("color: #64748B; padding-right: 10px;")
        status.addPermanentWidget(self.status_info)

    # ──────────────────────────────────────────────
    # STL YÜKLEME İŞLEMLERİ
    # ──────────────────────────────────────────────

    def _load_stl(self, target: str) -> None:
        """
        STL dosyası seçme ve SENKRON yükleme.
        macOS üzerinde QThread içerisinde PyVista (VTK) başlatmak C++ seviyesinde deadlock 
        yaratabildiği için dosya okuma işlemi direkt GUI thread'de yapılır.
        """
        if self.guided_active:
            self._reset_guided_measurement_state()
        if self.arch_mode_active:
            self._cancel_arch_perimeter_mode()

        start_dir = os.path.join(os.path.dirname(__file__), "..", "data", "patients")
        if not os.path.isdir(start_dir):
            start_dir = ""

        ark_label = "Üst Çene (Maksilla)" if target == "maxilla" else "Alt Çene (Mandibula)"

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"{ark_label} — STL Dosyası Seçin",
            start_dir,
            "STL Dosyaları (*.stl);;Tüm Dosyalar (*.*)"
        )

        if not file_path:
            return

        try:
            self._load_stl_from_path(target, file_path, allow_resume=True)
        except Exception as e:
            # Hataları kullanıcıya bildir
            print(f"[MainWindow:{target}] STL yükleme/görüntüleme hatası: {e}")
            traceback.print_exc()
            viewer = self.viewer_maxilla if target == "maxilla" else self.viewer_mandible
            viewer.show_error_state(
                f"{ark_label} yüklenemedi.\nAyrıntılar konsola yazıldı.\n{e}"
            )
            self.statusBar().showMessage(f"❌ {ark_label} yüklenemedi.", 5000)
            QMessageBox.warning(
                self,
                f"STL Hatası — {ark_label}",
                f"{os.path.basename(file_path)} yüklenirken hata oluştu.\n\n{e}"
            )

    def _load_maxilla(self) -> None:
        """Üst çene STL dosyasını yükler."""
        self._load_stl("maxilla")

    def _load_mandible(self) -> None:
        """Alt çene STL dosyasını yükler."""
        self._load_stl("mandible")

    def _clear_all(self) -> None:
        """Tüm yüklenen modelleri ve ölçümleri temizler."""
        confirm = QMessageBox.question(
            self,
            "Temizle",
            "Tüm modeller, ölçümler ve Bolton sonuçları silinecek.\n"
            "Devam etmek istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self._reset_guided_measurement_state()
            self._cancel_arch_perimeter_mode()
            self.viewer_maxilla.clear()
            self.viewer_mandible.clear()
            self.viewer_occlusion.clear()
            self.maxilla_mesh = None
            self.mandible_mesh = None
            self._maxilla_filename = ""
            self._mandible_filename = ""
            self._maxilla_path = ""
            self._mandible_path = ""
            self.lbl_maxilla_file.setText("MAKSILLA • Yüklenmedi")
            self.lbl_mandible_file.setText("MANDIBULA • Yüklenmedi")
            self.completed_teeth = {"maxillary": set(), "mandibular": set()}
            self.missing_teeth = {"maxillary": set(), "mandibular": set()}
            self.arch_lengths = {"maxillary": None, "mandibular": None}
            self.arch_paths = {"maxillary": [], "mandibular": []}
            self.current_view_mode = "maxillary"
            self.active_navigation_tool = "rotate"
            self.measurement_panel.clear_all()
            self._clear_autosave_session()
            self._show_home_page()
            self._refresh_toolbar_availability()
            self._sync_dashboard_from_measurements()
            self.statusBar().showMessage("🗑 Tüm modeller ve ölçümler temizlendi.", 3000)

    def _save_session_as(self) -> None:
        """Mevcut oturumu kullanıcı seçimiyle JSON dosyasına kaydeder."""
        payload = self._build_session_payload()
        if (
            not payload["measurement_rows"]
            and not payload["maxilla_path"]
            and not payload["mandible_path"]
        ):
            QMessageBox.information(
                self,
                "Kaydedilecek Veri Yok",
                "Oturum kaydetmek için önce ölçüm veya yüklenmiş model bulunmalı."
            )
            return

        default_name = f"selcukbolt_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "SelçukBolt Oturumunu Kaydet",
            str(self._session_path.parent / default_name),
            "SelçukBolt Oturum Dosyası (*.json)"
        )
        if not save_path:
            return

        try:
            with open(save_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(
                f"💾 Oturum kaydedildi: {os.path.basename(save_path)}",
                6000
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Oturum Kaydetme Hatası",
                f"Oturum dosyası kaydedilemedi:\n\n{exc}"
            )

    def _load_session_from_file(self) -> None:
        """Kullanıcının seçtiği oturum dosyasını anında uygular."""
        has_current_data = bool(
            not self.measurement_panel.df.empty
            or self.maxilla_mesh is not None
            or self.mandible_mesh is not None
            or self._maxilla_filename
            or self._mandible_filename
        )
        if has_current_data:
            confirm = QMessageBox.question(
                self,
                "Oturum Yüklensin mi?",
                "Mevcut çalışma alanı yüklenecek oturumla değiştirilecek.\nDevam etmek istiyor musunuz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "SelçukBolt Oturum Dosyası Seçin",
            str(self._session_path.parent),
            "SelçukBolt Oturum Dosyası (*.json)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
            self._apply_session_payload(payload, source_label="Kaydedilmiş oturum")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Oturum Yükleme Hatası",
                f"Oturum dosyası yüklenemedi:\n\n{exc}"
            )

    def _export_excel_template(self) -> None:
        """
        Klinik Excel şablonunu ölçüm verileriyle doldurur.

        Şablondaki Bolton formülleri korunur; uygulama yalnızca giriş
        hücrelerine diş genişliklerini ve temel hasta bilgisini yazar.
        """
        df = self.measurement_panel.get_dataframe()
        if df.empty:
            QMessageBox.warning(
                self,
                "Ölçüm Yok",
                "Excel çıktısı oluşturmak için önce diş ölçümlerini tamamlayın."
            )
            return

        if not self._validate_bolton_calculation_ready():
            return

        template_path = self._resolve_bolton_template_path()
        if template_path is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("📊 SelçukBolt Excel — Hasta Bilgileri")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #F9FCFD;
                color: #16303A;
            }
            QLabel {
                color: #16303A;
                font-size: 11px;
            }
            QLineEdit, QTextEdit {
                background-color: #FFFFFF;
                color: #16303A;
                border: 1px solid #D4E3EA;
                border-radius: 8px;
                padding: 6px;
                font-size: 11px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #7CC7DA;
            }
        """)

        form = QFormLayout(dialog)
        form.setSpacing(10)
        form.setContentsMargins(20, 20, 20, 20)

        patient_input = QLineEdit()
        patient_input.setPlaceholderText("Hasta adı veya kimlik numarası")
        form.addRow("Hasta ID / Ad:", patient_input)

        date_str = datetime.now().strftime("%d.%m.%Y")
        date_label = QLineEdit(date_str)
        date_label.setReadOnly(True)
        date_label.setStyleSheet(
            date_label.styleSheet() + "color: #6F8290; background-color: #F4F8FA;"
        )
        form.addRow("Tarih:", date_label)

        doctor_input = QLineEdit("Dt. Muhammet Ali")
        form.addRow("Doktor:", doctor_input)

        notes_input = QTextEdit()
        notes_input.setPlaceholderText("İsteğe bağlı kısa not")
        notes_input.setMaximumHeight(90)
        form.addRow("Not:", notes_input)

        template_label = QLineEdit(str(template_path))
        template_label.setReadOnly(True)
        template_label.setStyleSheet(
            template_label.styleSheet() + "color: #6F8290; background-color: #F4F8FA;"
        )
        form.addRow("Şablon:", template_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        patient_name = patient_input.text().strip() or "Bilinmeyen Hasta"
        doctor_name = doctor_input.text().strip() or "Dt. Muhammet Ali"
        notes = notes_input.toPlainText().strip()
        arch_notes = []
        if self.arch_lengths["maxillary"] is not None:
            arch_notes.append(f"Maksilla Ark Boyu: {self.arch_lengths['maxillary']:.2f} mm")
        if self.arch_lengths["mandibular"] is not None:
            arch_notes.append(f"Mandibula Ark Boyu: {self.arch_lengths['mandibular']:.2f} mm")
        if arch_notes:
            notes = "\n".join([notes, *arch_notes]).strip()

        default_name = f"SelcukBolt_Excel_{patient_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "SelçukBolt Excel Dosyasını Kaydet",
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "Excel Dosyaları (*.xlsx)"
        )
        if not save_path:
            return

        try:
            self.statusBar().showMessage("📊 Excel şablonu dolduruluyor...", 0)
            QApplication.processEvents()

            output = export_bolton_excel_template(
                template_path=template_path,
                output_path=save_path,
                measurements_df=df,
                patient_name=patient_name,
                report_date=date_str,
                doctor_name=doctor_name,
                notes=notes,
            )

            self.statusBar().showMessage(
                f"✅ SelçukBolt Excel dosyası kaydedildi: {os.path.basename(output)}",
                8000
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(output))
        except BoltonExcelExportError as exc:
            QMessageBox.critical(
                self,
                "Excel Şablon Hatası",
                str(exc)
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Excel Dışa Aktarma Hatası",
                f"Excel dosyası oluşturulurken hata oluştu:\n\n{exc}"
            )

    def _export_csv(self) -> None:
        """Ölçüm tablosunu CSV olarak dışa aktarır."""
        df = self.measurement_panel.get_dataframe()
        if df.empty:
            QMessageBox.warning(self, "Ölçüm Yok", "CSV dışa aktarım için önce ölçüm verisi oluşturun.")
            return

        default_name = f"SelcukBolt_Analiz_{datetime.now().strftime('%Y%m%d')}.csv"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "SelçukBolt CSV Dışa Aktar",
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "CSV Dosyaları (*.csv)",
        )
        if not save_path:
            return

        output = export_measurements_csv(output_path=save_path, measurements_df=df)
        self.statusBar().showMessage(f"✅ CSV kaydedildi: {os.path.basename(output)}", 6000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(output))

    def _export_json(self) -> None:
        """Analiz durumunu JSON olarak dışa aktarır."""
        payload = self._build_session_payload()
        payload["exported_from"] = "SelçukBolt"
        payload["exported_at"] = datetime.now().isoformat(timespec="seconds")

        default_name = f"SelcukBolt_Analiz_{datetime.now().strftime('%Y%m%d')}.json"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "SelçukBolt JSON Dışa Aktar",
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "JSON Dosyaları (*.json)",
        )
        if not save_path:
            return

        output = export_analysis_json(output_path=save_path, payload=payload)
        self.statusBar().showMessage(f"✅ JSON kaydedildi: {os.path.basename(output)}", 6000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(output))

    # ──────────────────────────────────────────────
    # FAZ 4: PDF RAPOR DIŞA AKTARMA
    # ──────────────────────────────────────────────

    def _export_pdf(self) -> None:
        """
        Bolton analiz raporunu PDF olarak dışa aktarır.

        İş Akışı:
            1. Ölçüm verisi kontrolü
            2. Kullanıcıdan hasta ID ve tedavi notu al (dialog)
            3. Kayıt konumu seç (QFileDialog)
            4. PDF oluştur → aç
        """
        # ── Ölçüm verisi kontrolü ──
        df = self.measurement_panel.get_dataframe()
        if df.empty:
            QMessageBox.warning(
                self,
                "Ölçüm Yok",
                "PDF rapor oluşturmak için en az bir diş ölçümü gereklidir.\n\n"
                "Önce dişleri ölçün veya 🤖 Otomatik Segmentasyon kullanın."
            )
            return

        if not self._validate_bolton_calculation_ready():
            return

        # ── Hasta bilgileri dialog'u ──
        dialog = QDialog(self)
        dialog.setWindowTitle("📄 SelçukBolt PDF — Hasta Bilgileri")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #F9FCFD;
                color: #16303A;
            }
            QLabel {
                color: #16303A;
                font-size: 11px;
            }
            QLineEdit, QTextEdit {
                background-color: #FFFFFF;
                color: #16303A;
                border: 1px solid #D4E3EA;
                border-radius: 8px;
                padding: 6px;
                font-size: 11px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #7CC7DA;
            }
        """)

        form = QFormLayout(dialog)
        form.setSpacing(10)
        form.setContentsMargins(20, 20, 20, 20)

        # Hasta ID
        patient_input = QLineEdit()
        patient_input.setPlaceholderText("Hasta adı veya kimlik numarası")
        form.addRow("Hasta ID / Ad:", patient_input)

        # Tarih (otomatik)
        from datetime import datetime
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        date_label = QLineEdit(date_str)
        date_label.setReadOnly(True)
        date_label.setStyleSheet(
            date_label.styleSheet() + "color: #6F8290; background-color: #F4F8FA;"
        )
        form.addRow("Rapor Tarihi:", date_label)

        # STL dosyaları (salt okunur)
        max_lbl = QLineEdit(self._maxilla_filename or "(yüklenmedi)")
        max_lbl.setReadOnly(True)
        max_lbl.setStyleSheet(max_lbl.styleSheet() + "color: #6F8290; background-color: #F4F8FA;")
        form.addRow("Üst Çene STL:", max_lbl)

        mand_lbl = QLineEdit(self._mandible_filename or "(yüklenmedi)")
        mand_lbl.setReadOnly(True)
        mand_lbl.setStyleSheet(mand_lbl.styleSheet() + "color: #6F8290; background-color: #F4F8FA;")
        form.addRow("Alt Çene STL:", mand_lbl)

        # Tedavi notu
        notes_input = QTextEdit()
        notes_input.setPlaceholderText(
            "Tedavi planı, IPR notları, klinik gözlemler..."
        )
        notes_input.setMaximumHeight(100)
        form.addRow("Tedavi Notu:", notes_input)

        # Dialog butonları
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        patient_id = patient_input.text().strip() or "Bilinmeyen Hasta"
        treatment_notes = notes_input.toPlainText().strip()
        arch_notes = []
        if self.arch_lengths["maxillary"] is not None:
            arch_notes.append(f"Maksilla Ark Boyu: {self.arch_lengths['maxillary']:.2f} mm")
        if self.arch_lengths["mandibular"] is not None:
            arch_notes.append(f"Mandibula Ark Boyu: {self.arch_lengths['mandibular']:.2f} mm")
        if arch_notes:
            treatment_notes = "\n".join([treatment_notes, *arch_notes]).strip()

        # ── Kayıt konumu seç ──
        default_name = f"SelcukBolt_Rapor_{patient_id.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "SelçukBolt PDF Raporunu Kaydet",
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "PDF Dosyaları (*.pdf)"
        )

        if not save_path:
            return

        # ── PDF oluştur ──
        try:
            self.statusBar().showMessage("📄 PDF rapor oluşturuluyor...", 0)
            QApplication.processEvents()

            output = generate_bolton_report(
                output_path=save_path,
                patient_id=patient_id,
                report_date=date_str,
                maxilla_filename=self._maxilla_filename or "(yüklenmedi)",
                mandible_filename=self._mandible_filename or "(yüklenmedi)",
                measurements_df=df,
                treatment_notes=treatment_notes,
            )

            self.statusBar().showMessage(
                f"✅ PDF rapor kaydedildi: {os.path.basename(save_path)}", 8000
            )

            # Raporu varsayılan PDF görüntüleyicide aç
            QDesktopServices.openUrl(QUrl.fromLocalFile(save_path))

        except Exception as e:
            QMessageBox.critical(
                self,
                "PDF Hatası",
                f"PDF rapor oluşturulurken hata:\n\n{str(e)}"
            )
            self.statusBar().showMessage("❌ PDF oluşturma hatası.", 5000)

    # ──────────────────────────────────────────────
    # HAKKINDA
    # ──────────────────────────────────────────────

    def _show_about(self) -> None:
        """Uygulama hakkında bilgi diyaloğu."""
        QMessageBox.about(
            self,
            "SelçukBolt Hakkında",
            "<h2>🦷 SelçukBolt</h2>"
            "<p><b>Klinik ortodontik analiz çalışma alanı</b></p>"
            "<p>STL yüzey taramaları kullanarak otomatik Bolton Analizi "
            "gerçekleştiren ortodontik tanı yazılımı.</p>"
            "<hr>"
            "<p><b>Bolton Referans Değerleri:</b></p>"
            "<ul>"
            "<li>Anterior Oran (3-3): %77.2 ± 1.65</li>"
            "<li>Overall Oran (6-6): %91.3 ± 1.91</li>"
            "</ul>"
            "<p><b>Ölçüm İş Akışı:</b></p>"
            "<ol>"
            "<li>Üst ve alt çene STL dosyalarını yükleyin</li>"
            "<li>Ölçüm panelinden çene ve diş seçin</li>"
            "<li>'Ölçüm Başlat' ile picking modunu açın</li>"
            "<li>Mesh üzerinde mezial ve distal noktaları tıklayın</li>"
            "<li>Bolton oranları otomatik hesaplanacaktır</li>"
            "</ol>"
            "<p><i>Ortodontik Araştırma ve Klinik Mükemmellik için</i></p>"
        )

    # ──────────────────────────────────────────────
    # FAZ 3: OTOMATİK SEGMENTASYON
    # ──────────────────────────────────────────────

    def _run_segmentation(self) -> None:
        """
        Tam AI segmentasyon boru hattı:
        1. Her iki çeneyi ön işle (STL → nokta bulutu)
        2. Segmentor ile dişleri etiketle
        3. Landmark finder ile mezial/distal bul
        4. Ölçüm tablosunu otomatik doldur
        5. 3D sahnede dişleri renklendir
        """
        # ── Ön kontrol: her iki çene yüklenmiş mi? ──
        if self.maxilla_mesh is None or self.mandible_mesh is None:
            missing = []
            if self.maxilla_mesh is None:
                missing.append("Üst Çene (Maksilla)")
            if self.mandible_mesh is None:
                missing.append("Alt Çene (Mandibula)")
            QMessageBox.warning(
                self,
                "STL Eksik",
                f"Otomatik segmentasyon için her iki çene STL dosyası gereklidir.\n\n"
                f"Eksik: {', '.join(missing)}"
            )
            return

        # ── Mevcut ölçümleri temizle ──
        self.measurement_panel.clear_all()
        self.statusBar().showMessage("🤖 AI segmentasyon başlatılıyor...", 0)
        QApplication.processEvents()

        # ── Segmentor'u başlat (lazy init) ──
        if self._segmentor is None:
            self._segmentor = ToothSegmentor()

        self.status_info.setText(f"Faz 3 — {self._segmentor.mode_description}")

        all_landmarks = {}

        try:
            # ── MAKSILLA ──
            self.statusBar().showMessage("🤖 Üst çene ön işleniyor...", 0)
            QApplication.processEvents()

            features_max, centroid_max, scale_max, raw_max = mesh_to_feature_tensor(
                self.maxilla_mesh
            )

            self.statusBar().showMessage("🤖 Üst çene segmente ediliyor...", 0)
            QApplication.processEvents()

            labels_max, tooth_pts_max = self._segmentor.segment(
                features_max, jaw_type="maxillary", raw_points=raw_max
            )
            landmarks_max = find_landmarks(tooth_pts_max)
            all_landmarks.update(landmarks_max)

            # 3D sahnede renklendir
            self._visualize_segmented_teeth(
                self.viewer_maxilla, self.maxilla_mesh,
                raw_max, labels_max, landmarks_max
            )

            # ── MANDİBULA ──
            self.statusBar().showMessage("🤖 Alt çene ön işleniyor...", 0)
            QApplication.processEvents()

            features_mand, centroid_mand, scale_mand, raw_mand = mesh_to_feature_tensor(
                self.mandible_mesh
            )

            self.statusBar().showMessage("🤖 Alt çene segmente ediliyor...", 0)
            QApplication.processEvents()

            labels_mand, tooth_pts_mand = self._segmentor.segment(
                features_mand, jaw_type="mandibular", raw_points=raw_mand
            )
            landmarks_mand = find_landmarks(tooth_pts_mand)
            all_landmarks.update(landmarks_mand)

            self._visualize_segmented_teeth(
                self.viewer_mandible, self.mandible_mesh,
                raw_mand, labels_mand, landmarks_mand
            )

            # ── Ölçüm tablosunu doldur ──
            rows = landmarks_to_dataframe_rows(all_landmarks)
            self.measurement_panel.auto_fill_measurements(rows)
            self.completed_teeth["maxillary"] = set(MAXILLARY_OVERALL)
            self.completed_teeth["mandibular"] = set(MANDIBULAR_OVERALL)
            self.viewer_maxilla.set_completed_teeth(sorted(self.completed_teeth["maxillary"]))
            self.viewer_mandible.set_completed_teeth(sorted(self.completed_teeth["mandibular"]))
            self.viewer_maxilla.set_arch_measure_visible(True)
            self.viewer_mandible.set_arch_measure_visible(True)
            self.viewer_maxilla.set_overlay_hint("AI ölçümleri tamamlandı. İsterseniz ark boyunu ölçün.")
            self.viewer_mandible.set_overlay_hint("AI ölçümleri tamamlandı. İsterseniz ark boyunu ölçün.")
            self._sync_dashboard_from_measurements()

            n_teeth = len(all_landmarks)
            valid = sum(1 for lm in all_landmarks.values() if lm.valid)
            self.statusBar().showMessage(
                f"✅ Segmentasyon tamamlandı: {n_teeth} diş tespit edildi "
                f"({valid} geçerli ölçüm).",
                8000
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Segmentasyon Hatası",
                f"AI segmentasyon sırasında bir hata oluştu:\n\n{str(e)}"
            )
            self.statusBar().showMessage("❌ Segmentasyon hatası.", 5000)

    def _visualize_segmented_teeth(
        self,
        viewer: MeshViewer,
        mesh,
        raw_points: np.ndarray,
        labels: np.ndarray,
        landmarks: dict,
    ) -> None:
        """
        Segmente edilmiş dişleri 3D sahnede renklendirir ve
        landmark noktalarını işaretler.

        Renk paleti: Her FDI numarasına benzersiz bir renk atanır.
        Landmark'lar küre + ölçüm çizgisi olarak gösterilir.
        """
        import pyvista as pv

        # ── Diş renk paleti (24 diş için) ──
        tooth_colors = {
            11: "#FF6B6B", 12: "#FF8E8E", 13: "#FFB4B4",
            14: "#4ECDC4", 15: "#45B7AA", 16: "#3CA090",
            21: "#6BCB77", 22: "#8FDB8F", 23: "#B4ECAC",
            24: "#FFD93D", 25: "#FFE066", 26: "#FFE999",
            31: "#6C5CE7", 32: "#8B7BEA", 33: "#A99AED",
            34: "#FD79A8", 35: "#FDA7C4", 36: "#FDC5D9",
            41: "#00B4D8", 42: "#48CAE4", 43: "#90E0EF",
            44: "#F4845F", 45: "#F79D6E", 46: "#FAB67D",
        }

        # Diş landmark'larını göster
        for fdi, lm in landmarks.items():
            color = tooth_colors.get(fdi, "#FFFFFF")

            # Mezial marker
            viewer.add_point_marker(lm.mesial, color="#06D6A0", label="M", radius=0.2)
            # Distal marker
            viewer.add_point_marker(lm.distal, color="#FFD166", label="D", radius=0.2)
            # Ölçüm çizgisi
            viewer.add_measurement_line(
                lm.mesial, lm.distal,
                label=f"{fdi}: {lm.width_mm:.1f}mm",
                color=color,
            )

    # ──────────────────────────────────────────────
    # PENCERE KAPANIŞI
    # ──────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """Pencere kapatılırken PyVista plotter'ları güvenli şekilde temizler."""
        try:
            self._autosave_session()
            if self.report_thread is not None and self.report_thread.isRunning():
                self.report_thread.quit()
                self.report_thread.wait(1500)
            self.viewer_maxilla.close()
            self.viewer_mandible.close()
            self.viewer_occlusion.close()
        except Exception:
            pass
        event.accept()

    def resizeEvent(self, event) -> None:
        """Overlay katmanlarını pencere boyutuna göre yeniden yerleştir."""
        super().resizeEvent(event)
        self._reposition_report_overlay()
