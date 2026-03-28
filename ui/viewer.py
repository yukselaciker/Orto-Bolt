"""
ui/viewer.py — 3D Mesh Görüntüleyici Widget
=============================================
Faz 1: PyVista tabanlı 3D görselleştirme, PySide6 içine gömülü.

Tasarım Kararı:
    BackgroundPlotter yerine QtInteractor kullanıyoruz çünkü:
    - Ayrı pencere açmak yerine ana pencere içine gömülür
    - Klinik kullanıcılar için daha sezgisel tek pencere deneyimi
    - PySide6 layout sistemiyle tam uyumlu

    On-Demand Plotter:
    QtInteractor yalnızca mesh yüklendiğinde oluşturulur.
    Bu sayede ana pencere hafif açılır ve render bileşeni yalnızca gerektiğinde başlar.
"""
# SELÇUKBOLT UI REDESIGN — Mesh Viewer

from typing import Optional, List, Any
import traceback
import numpy as np

import pyvista as pv

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QApplication,
    QProgressBar, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtGui import QFont

class MeshViewer(QFrame):
    """
    Tek bir dental ark (üst veya alt çene) için 3D görüntüleyici.

    Klinik İş Akışı:
        1. STL dosyası yüklenir → mesh gösterilir
        2. Kullanıcı mesh üzerinde noktalar seçer (Faz 2'de etkinleşir)
        3. Seçilen noktalar arasındaki mesafe hesaplanır

    Sinyaller:
        point_picked: Kullanıcı mesh üzerinde bir nokta seçtiğinde tetiklenir.
    """

    # Kullanıcı mesh üzerinde nokta seçtiğinde (x, y, z) koordinatları gönderir
    point_picked = Signal(np.ndarray)
    marker_moved = Signal(str, np.ndarray)
    tooth_selected = Signal(int)
    arch_perimeter_requested = Signal()
    next_stage_requested = Signal()
    finish_requested = Signal()

    # Görselleştirme renk ayarları — fildişi rengi dental modellere benzer
    MESH_COLOR = "#F6EFE6"
    MESH_COLOR_MANDIBLE = "#EDE5DA"
    BACKGROUND_COLOR = "#0A0D14"
    POINT_COLOR = "#0EA5A4"
    LINE_COLOR = "#0284C7"
    HIGHLIGHT_COLOR = "#38BDF8"

    def __init__(
        self,
        title: str = "3D Görüntüleyici",
        is_mandible: bool = False,
        parent: Optional[QWidget] = None
    ):
        """
        Args:
            title: Görüntüleyici başlığı (ör. "Maksilla" veya "Mandibula").
            is_mandible: Alt çene ise True — renk tonu değişir.
            parent: Ana widget.
        """
        super().__init__(parent)
        self.title_text = title
        self.is_mandible = is_mandible

        # Durum değişkenleri
        self.current_mesh: Optional[pv.PolyData] = None
        self.picked_points: List[np.ndarray] = []
        self.point_actors: list = []         # Seçilen noktaların 3D aktörleri
        self.measurement_actors: list = []   # Ölçüm çizgisi aktörleri
        self._odontogram_teeth: list[int] = []

        # Plotter on-demand: yalnızca mesh yüklendiğinde oluşturulur
        self.plotter = None
        self._plotter_initialized = False
        self._interaction_mode_configured = False
        self._focus_key_registered = False
        self._mouse_tracking_enabled = False
        self._click_tracking_enabled = False
        self._left_pick_observer = None
        self._left_release_observer = None
        self._mouse_move_pick_observer = None
        self._pick_press_position = None
        self._pick_dragging = False
        self._touchpad_filter_installed = False
        self._marker_meta: dict[str, dict[str, Any]] = {}
        self._draggable_marker_names: set[str] = set()
        self._drag_marker_name: Optional[str] = None
        self._drag_camera_state: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._navigation_mode = "rotate"
        self._jaw_label = "MAKSILLA" if not self.is_mandible else "MANDIBULA"
        self._base_camera_distance: Optional[float] = None
        self._zoom_factor = 1.0

        self._init_ui()

    def _init_ui(self) -> None:
        """Widget arayüzünü oluşturur (plotter hariç — on-demand)."""
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.setLineWidth(1)
        # UI STYLE UPDATE — viewer frame shell
        self.setStyleSheet("""
            QFrame {
                background-color: #0F1219;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
            }
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)

        # Başlık ve Ortala butonu satırı
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Başlık etiketi
        self.title_label = QLabel(self.title_text)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.Bold))
        # UI STYLE UPDATE — viewer title label
        self.title_label.setStyleSheet("""
            QLabel {
                color: #64748B;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                padding: 8px 12px;
            }
        """)
        header_layout.addWidget(self.title_label, stretch=1)

        self.btn_reset_view = QPushButton("🎯 Ortala")
        self.btn_reset_view.setToolTip("Görüş açısını ve yakınlaştırmayı sıfırla")
        self.btn_reset_view.clicked.connect(self.reset_camera)
        self.btn_reset_view.setStyleSheet("""
            QPushButton {
                background-color: rgba(59, 130, 246, 0.1);
                color: #3B82F6;
                border: 1px solid rgba(59,130,246,0.3);
                border-radius: 10px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #3B82F6;
                color: #FFFFFF;
            }
        """)
        header_layout.addWidget(self.btn_reset_view)
        self.title_label.show()
        self.btn_reset_view.hide()
        self._layout.addLayout(header_layout)

        self.current_tooth_label = QLabel("")
        self.current_tooth_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_tooth_label.setVisible(False)
        self.current_tooth_label.setFont(QFont(".AppleSystemUIFont", 15, QFont.Weight.Bold))
        self.current_tooth_label.setStyleSheet("""
            QLabel {
                color: #F8FAFC;
                background-color: rgba(30, 41, 59, 0.9);
                border: 1px solid rgba(59, 130, 246, 0.4);
                border-radius: 14px;
                padding: 12px 18px;
                font-weight: 800;
            }
        """)
        self._layout.addWidget(self.current_tooth_label)
        self.current_tooth_label.hide()

        # Yükleme/hata durumu kullanıcıya widget içinde görünür tutulur
        self.state_label = QLabel("")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setWordWrap(True)
        self.state_label.setVisible(False)
        self._layout.addWidget(self.state_label)

        # Belirsiz ilerleme çubuğu "spinner" eşdeğeri olarak kullanılır
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(8)
        self.loading_bar.setVisible(False)
        self.loading_bar.setStyleSheet("""
            QProgressBar {
                background-color: #111722;
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 4px;
            }
        """)
        self._layout.addWidget(self.loading_bar)

        # Placeholder — plotter olmadan görünen widget
        self._placeholder = QLabel("STL dosyası yükleyin")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # UI STYLE UPDATE — viewer empty state
        self._placeholder.setStyleSheet("""
            QLabel {
                color: #7C8AA5;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: 0.4px;
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0C111A, stop:1 #101826);
                border: 1px dashed rgba(96, 165, 250, 0.28);
                border-radius: 14px;
                padding: 24px;
            }
        """)
        self._layout.addWidget(self._placeholder, stretch=1)

        # Bilgi etiketi — mesh istatistikleri
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("""
            QLabel {
                color: #64748B;
                font-size: 10px;
                padding: 4px;
                font-family: "Menlo";
            }
        """)
        self._layout.addWidget(self.info_label)
        self.info_label.hide()

        self.overlay_panel = QFrame(self)
        self.overlay_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(15, 23, 42, 0.85);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 12px;
            }
            QLabel {
                color: #F1F5F9;
            }
        """)
        self.overlay_panel.setFixedWidth(250)
        self.overlay_panel.hide()

        overlay_layout = QVBoxLayout(self.overlay_panel)
        overlay_layout.setContentsMargins(12, 12, 12, 12)
        overlay_layout.setSpacing(8)

        self.overlay_header = QLabel(f"{self._jaw_label} — STL BEKLENIYOR")
        self.overlay_header.setStyleSheet("font-size: 12px; font-weight: 700; font-family: 'Syne'; letter-spacing: 0.6px;")
        self.overlay_header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        overlay_layout.addWidget(self.overlay_header)

        self.overlay_hint_label = QLabel("STL yukleyin ve sol tik ile nokta secin.")
        self.overlay_hint_label.setWordWrap(True)
        self.overlay_hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.overlay_hint_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-family: 'JetBrains Mono', 'Menlo', monospace;
                letter-spacing: -0.2px;
            }
        """)
        overlay_layout.addWidget(self.overlay_hint_label)

        self.shortcut_label = QLabel(
            "Space: Ileri\nBackspace: Sil\nN: Dis Yok / Gec\nSol Tik: Sec\nNoktayi Surukle: Ince Ayar\nSag Tik: Dondur\nTekerlek: Zoom"
        )
        self.shortcut_label.setWordWrap(True)
        self.shortcut_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.shortcut_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 10px;
                background-color: rgba(2, 6, 23, 0.6);
                border: 1px solid rgba(255,255,255,0.05);
                border-radius: 10px;
                padding: 10px;
                font-family: 'JetBrains Mono', 'Menlo', monospace;
                line-height: 1.4;
            }
        """)
        overlay_layout.addWidget(self.shortcut_label)

        self.arch_length_label = QLabel("Ark Boyu: Henüz ölçülmedi")
        self.arch_length_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arch_length_label.setStyleSheet("""
            QLabel {
                color: #3B82F6;
                background-color: rgba(59, 130, 246, 0.1);
                border: 1px solid rgba(59, 130, 246, 0.2);
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
                font-weight: 700;
                font-family: 'JetBrains Mono', 'Menlo', monospace;
            }
        """)
        overlay_layout.addWidget(self.arch_length_label)
        self.arch_length_label.hide()

        self.btn_measure_arch = QPushButton("Ark Boyunu Ölç")
        self.btn_measure_arch.clicked.connect(self.arch_perimeter_requested.emit)
        self.btn_measure_arch.hide()
        overlay_layout.addWidget(self.btn_measure_arch)

        self.btn_next_stage = QPushButton("Alt Çeneye Geç")
        self.btn_next_stage.clicked.connect(self.next_stage_requested.emit)
        self.btn_next_stage.hide()
        overlay_layout.addWidget(self.btn_next_stage)

        self.btn_finish_workflow = QPushButton("Ölçümleri Bitir ve Raporla")
        self.btn_finish_workflow.clicked.connect(self.finish_requested.emit)
        self.btn_finish_workflow.hide()
        overlay_layout.addWidget(self.btn_finish_workflow)

        self.zoom_chip = QLabel("ZOOM 1.0×", self)
        self.zoom_chip.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                background-color: rgba(15, 23, 42, 0.8);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 700;
                font-family: 'JetBrains Mono', 'Menlo', monospace;
            }
        """)
        self.zoom_chip.adjustSize()
        self.zoom_chip.hide()



    # ──────────────────────────────────────────────
    # ON-DEMAND PLOTTER: mesh yüklendiğinde oluştur
    # ──────────────────────────────────────────────

    def show_loading_state(self, message: str) -> None:
        """Yükleme başladığında görünür spinner ve durum metni göster."""
        # Kritik adım: yeni yükleme öncesi eski hata mesajını temizle
        self.state_label.setText(message)
        self.state_label.setStyleSheet("""
            QLabel {
                color: #93C5FD;
                background-color: rgba(59,130,246,0.10);
                border: 1px solid rgba(59,130,246,0.28);
                border-radius: 10px;
                padding: 8px 12px;
                margin: 2px 0;
            }
        """)
        self.state_label.setVisible(True)
        self.loading_bar.setVisible(True)

    def clear_state_message(self) -> None:
        """Yükleme tamamlandığında spinner ve durum bandını kapat."""
        self.state_label.clear()
        self.state_label.setVisible(False)
        self.loading_bar.setVisible(False)

    def show_error_state(self, message: str) -> None:
        """Yükleme veya render hatasını kullanıcıya widget içinde göster."""
        # Kritik adım: hata olsa bile spinner'ı kapat
        self.loading_bar.setVisible(False)
        self.state_label.setText(message)
        self.state_label.setStyleSheet("""
            QLabel {
                color: #FCA5A5;
                background-color: rgba(239,68,68,0.12);
                border: 1px solid rgba(239,68,68,0.28);
                border-radius: 10px;
                padding: 8px 12px;
                margin: 2px 0;
            }
        """)
        self.state_label.setVisible(True)

    def _ensure_plotter(self) -> bool:
        """
        QtInteractor'un hazır olduğundan emin ol.
        Yoksa oluştur. Başarılıysa True döner.
        MacOS üzerinde UI donmasını (beachball) önlemek için plotter SADECE
        kullanıcı bir mesh yüklediğinde oluşturulur (On-Demand).
        """
        if self._plotter_initialized and self.plotter is not None:
            return True

        try:
            print("DEBUG: _ensure_plotter -> from pyvistaqt import QtInteractor", flush=True)
            from pyvistaqt import QtInteractor

            print("DEBUG: _ensure_plotter -> QtInteractor(self, multi_samples=0) çağrılıyor...", flush=True)
            # auto_update KESİNLİKLE kapalı olmalıdır, aksi halde 5ms'lik loop UI'ı kilitler
            self.plotter = QtInteractor(
                self,
                multi_samples=0,
            )
            
            # MACOS DEADLOCK FIX KESİN ÇÖZÜMÜ:
            # PySide6 macOS üzerinde QVTKRenderWindowInteractor'un paintEvent'i içerisindeki 
            # self._Iren.Render() çağrısı sonsuz döngüye girip (beachball) uygulamayı kilitliyor.
            # VTK ve Cocoa zaten kendi resize eventlerini yakaladığı için Qt paintEvent boş geçilmeli.
            def safe_paintEvent(ev):
                pass
            self.plotter.paintEvent = safe_paintEvent

            self.plotter.set_background(self.BACKGROUND_COLOR)
            self.plotter.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            
            if not self._interaction_mode_configured:
                self._apply_navigation_style()
                self._interaction_mode_configured = True

            if not self._mouse_tracking_enabled:
                self.plotter.track_mouse_position()
                self._mouse_tracking_enabled = True

            if not self._focus_key_registered:
                self.plotter.add_key_event("f", self._focus_on_hovered_point)
                self.plotter.add_key_event("F", self._focus_on_hovered_point)
                self._focus_key_registered = True

            if not self._touchpad_filter_installed:
                self.plotter.installEventFilter(self)
                self._touchpad_filter_installed = True

            # Placeholder'ı kaldır, plotter'ı ekle
            if self._placeholder is not None:
                self._placeholder.setVisible(False)
                self._layout.replaceWidget(self._placeholder, self.plotter)
                self._placeholder.setParent(None)
                self._placeholder.deleteLater()
                self._placeholder = None

            self.overlay_panel.raise_()
            self.zoom_chip.raise_()

            self._plotter_initialized = True
            print("DEBUG: _ensure_plotter -> TAMAMLANDI.", flush=True)
            return True

        except Exception as e:
            print(f"[MeshViewer] QtInteractor oluşturulamadı: {e}")
            import traceback
            traceback.print_exc()
            self.info_label.setText(f"3D hata: {e}")
            self.show_error_state(f"3D görüntüleyici başlatılamadı:\n{e}")
            return False

    def _configure_lighting(self, mesh_center: np.ndarray, max_dim: float) -> None:
        """Diş modelinin hacmini ortaya çıkaran sabit sahne ışıklarını kur."""
        if self.plotter is None:
            return

        ambient_intensity = 0.16 if self.is_mandible else 0.18
        key_intensity = 0.88 if self.is_mandible else 0.96
        fill_intensity = 0.24 if self.is_mandible else 0.28
        rim_intensity = 0.34 if self.is_mandible else 0.38

        # Kritik adım: düz beyaz silüeti önlemek için varsayılan ışıkları temizle
        self.plotter.remove_all_lights()

        # Headlight, ambient light benzeri taban dolgu ışığı sağlar
        ambient_like = pv.Light(
            light_type="headlight",
            intensity=ambient_intensity,
            color="white",
        )
        self.plotter.add_light(ambient_like)

        # Ana yönlü ışık yüzey detaylarını ve specular parlamayı görünür kılar
        key_light = pv.Light(
            position=(
                mesh_center[0] + max_dim * 0.8,
                mesh_center[1] + max_dim * 1.2,
                mesh_center[2] + max_dim * 0.9,
            ),
            focal_point=tuple(mesh_center),
            color="#FFF7ED",
            intensity=key_intensity,
            light_type="scene light",
        )
        self.plotter.add_light(key_light)

        # Karşı taraftan gelen zayıf dolgu ışığı sert gölgeleri yumuşatır
        fill_light = pv.Light(
            position=(
                mesh_center[0] - max_dim * 0.9,
                mesh_center[1] - max_dim * 0.35,
                mesh_center[2] + max_dim * 0.52,
            ),
            focal_point=tuple(mesh_center),
            color="#DBEAFE",
            intensity=fill_intensity,
            light_type="scene light",
        )
        self.plotter.add_light(fill_light)

        # Arkadan gelen rim light diş tepeleri ve fissurleri silüetten ayırır.
        rim_light = pv.Light(
            position=(
                mesh_center[0] - max_dim * 0.25,
                mesh_center[1] + max_dim * 1.05,
                mesh_center[2] - max_dim * 1.15,
            ),
            focal_point=tuple(mesh_center),
            color="#F8FAFC",
            intensity=rim_intensity,
            light_type="scene light",
        )
        self.plotter.add_light(rim_light)

        self._configure_render_effects(max_dim)

    def _configure_render_effects(self, max_dim: float) -> None:
        """Yüzey temas gölgelerini ve self-shadow etkisini güvenle etkinleştir."""
        if self.plotter is None:
            return

        ssao_radius = max(0.45, min(1.35, max_dim * 0.018))

        try:
            self.plotter.disable_ssao()
        except Exception:
            pass

        try:
            self.plotter.enable_ssao(
                radius=ssao_radius,
                bias=0.008,
                kernel_size=128,
                blur=True,
            )
        except Exception:
            pass

        try:
            self.plotter.disable_shadows()
        except Exception:
            pass

        try:
            self.plotter.enable_shadows()
        except Exception:
            pass

    def _fit_camera_to_mesh(self, mesh: pv.PolyData) -> None:
        """Kamerayı oklüzal düzleme yukarıdan bakacak şekilde konumlandır."""
        if self.plotter is None:
            return

        bounds = mesh.bounds
        center = np.asarray(mesh.center, dtype=float)
        size = np.array([
            bounds[1] - bounds[0],
            bounds[3] - bounds[2],
            bounds[5] - bounds[4],
        ], dtype=float)
        max_dim = max(float(size.max()), 1.0)

        # Varsayılan klinik görünüm: modele tam yukarıdan bak
        camera = self.plotter.camera
        camera.SetFocalPoint(*center)
        camera.SetPosition(
            center[0],
            center[1],
            center[2] + max_dim * 2.4,
        )
        camera.SetViewUp(0.0, 1.0, 0.0)
        self.plotter.renderer.ResetCamera()
        self.plotter.renderer.ResetCameraClippingRange()
        self._base_camera_distance = float(np.linalg.norm(np.asarray(camera.GetPosition()) - np.asarray(camera.GetFocalPoint())))
        self._zoom_factor = 1.0
        self._update_zoom_indicator()

    def reset_camera(self) -> None:
        """Kamerayı modelin bounding box merkezine sıfırlar."""
        if self.plotter is None or self.current_mesh is None:
            return
        self._fit_camera_to_mesh(self.current_mesh)
        self.plotter.render()

    def _update_zoom_indicator(self) -> None:
        """Alt sağ zoom göstergesini günceller."""
        if self.plotter is None:
            return
        try:
            camera = self.plotter.camera
            current_distance = float(np.linalg.norm(
                np.asarray(camera.GetPosition(), dtype=np.float64) -
                np.asarray(camera.GetFocalPoint(), dtype=np.float64)
            ))
            if self._base_camera_distance and self._base_camera_distance > 1e-6:
                self._zoom_factor = max(0.1, self._base_camera_distance / current_distance)
        except Exception:
            pass
        self.zoom_chip.setText(f"ZOOM {self._zoom_factor:.1f}×")
        self.zoom_chip.adjustSize()
        self.zoom_chip.show()
        self._reposition_zoom_chip()

    def _apply_navigation_style(self) -> None:
        """Aktif araç moduna göre trackball etkileşimini ayarlar."""
        if self.plotter is None:
            return
        try:
            custom_trackball = getattr(self.plotter, "enable_custom_trackball_style", None)
            if custom_trackball is None:
                self.plotter.enable_trackball_style()
                return

            if self._navigation_mode == "rotate":
                custom_trackball(
                    left="rotate",
                    middle="pan",
                    right="rotate",
                    shift_right="pan",
                    control_right="pan",
                )
            else:
                custom_trackball(
                    left="pan",
                    middle="pan",
                    right="rotate",
                    shift_right="pan",
                    control_right="pan",
                )
        except Exception:
            try:
                self.plotter.enable_trackball_style()
            except Exception:
                pass

    def set_navigation_mode(self, tool_name: str) -> None:
        """Toolbar araç durumunu viewer etkileşimine yansıtır."""
        self._navigation_mode = tool_name if tool_name in {"rotate", "pan", "zoom"} else "rotate"
        self._apply_navigation_style()

    # ──────────────────────────────────────────────
    # MESH GÖRÜNTÜLEME
    # ──────────────────────────────────────────────

    def display_mesh(self, mesh: pv.PolyData) -> None:
        """
        Yüklenen mesh'i 3D olarak görüntüler.

        Args:
            mesh: PyVista PolyData nesnesi.
        """
        try:
            # Kritik adım: renderer hazır değilse mesh ekleme başlamasın
            if not self._ensure_plotter():
                raise RuntimeError("3D görüntüleyici hazır değil.")

            # Kritik adım: önceki aktörleri temizle ama yükleme bandını koru
            self.clear(preserve_status=True)

            # Ölçüm/AI mantığını etkilememek için render kopyası üzerinde çalış
            render_mesh = mesh.copy(deep=True)
            render_mesh = render_mesh.triangulate()

            # Kritik adım: smooth shading için vertex normallerini yeniden üret
            try:
                render_mesh.compute_normals(
                    inplace=True,
                    cell_normals=False,
                    split_vertices=True,
                    auto_orient_normals=True,
                    consistent_normals=True,
                    feature_angle=42.0,
                )
            except TypeError:
                render_mesh.compute_normals(inplace=True)

            self.current_mesh = render_mesh
            mesh_color = self.MESH_COLOR_MANDIBLE if self.is_mandible else self.MESH_COLOR
            ambient = 0.14 if self.is_mandible else 0.12
            diffuse = 0.88 if self.is_mandible else 0.9
            specular = 0.045 if self.is_mandible else 0.05
            specular_power = 10 if self.is_mandible else 12
            bounds = render_mesh.bounds
            size = np.array([
                bounds[1] - bounds[0],
                bounds[3] - bounds[2],
                bounds[5] - bounds[4],
            ], dtype=float)
            max_dim = max(float(size.max()), 1.0)

            # Kritik adım: ışıkları mesh eklenecek sahne için önceden kur
            self._configure_lighting(np.asarray(render_mesh.center, dtype=float), max_dim)

            print("DEBUG: display_mesh -> self.plotter.add_mesh başlıyor...", flush=True)
            # Kritik adım: diş modeli materyalini specular ile ekle, sonra render et
            self.plotter.add_mesh(
                render_mesh,
                color=mesh_color,
                smooth_shading=True,
                ambient=ambient,
                diffuse=diffuse,
                specular=specular,
                specular_power=specular_power,
                show_scalar_bar=False,
                name="dental_mesh",
            )
            print("DEBUG: display_mesh -> self.plotter.add_mesh tamamlandı.", flush=True)

            # Doğal QT render iptal edildiği (safe_paintEvent) için manuel render yapmamız ŞART:
            self.plotter.render()
            print("DEBUG: display_mesh -> self.plotter.render() tamamlandı.", flush=True)
        except Exception as e:
            print(f"[MeshViewer] Mesh görüntülenemedi: {e}")
            traceback.print_exc()
            self.current_mesh = None
            self.info_label.setText("")
            raise

        # Mesh bilgilerini güncelle
        self.info_label.setText(
            f"▲ {render_mesh.n_cells:,} yüzey  |  ● {render_mesh.n_points:,} nokta"
        )
        self.overlay_header.setText(f"{self._jaw_label} — STL LOADED")
        self._update_zoom_indicator()

    def display_occlusion_meshes(
        self,
        maxilla_mesh: pv.PolyData,
        mandible_mesh: pv.PolyData,
    ) -> None:
        """Maksilla ve mandibulayı tek sahnede kapanış görünümüyle gösterir."""
        if not self._ensure_plotter():
            raise RuntimeError("3D görüntüleyici hazır değil.")

        self.clear(preserve_status=True)

        max_render = maxilla_mesh.copy(deep=True).triangulate()
        mand_render = mandible_mesh.copy(deep=True).triangulate()

        try:
            max_render.compute_normals(
                inplace=True,
                cell_normals=False,
                split_vertices=True,
                auto_orient_normals=True,
                consistent_normals=True,
                feature_angle=42.0,
            )
            mand_render.compute_normals(
                inplace=True,
                cell_normals=False,
                split_vertices=True,
                auto_orient_normals=True,
                consistent_normals=True,
                feature_angle=42.0,
            )
        except TypeError:
            max_render.compute_normals(inplace=True)
            mand_render.compute_normals(inplace=True)

        merged = max_render.copy(deep=True).merge(mand_render, merge_points=False)
        self.current_mesh = merged

        bounds = merged.bounds
        size = np.array([
            bounds[1] - bounds[0],
            bounds[3] - bounds[2],
            bounds[5] - bounds[4],
        ], dtype=float)
        max_dim = max(float(size.max()), 1.0)
        self._configure_lighting(np.asarray(merged.center, dtype=float), max_dim)

        self.plotter.add_mesh(
            max_render,
            color=self.MESH_COLOR,
            smooth_shading=True,
            ambient=0.12,
            diffuse=0.9,
            specular=0.05,
            specular_power=12,
            show_scalar_bar=False,
            name="occlusion_maxilla",
        )
        self.plotter.add_mesh(
            mand_render,
            color=self.MESH_COLOR_MANDIBLE,
            smooth_shading=True,
            ambient=0.14,
            diffuse=0.88,
            specular=0.045,
            specular_power=10,
            show_scalar_bar=False,
            name="occlusion_mandible",
        )
        center = np.asarray(merged.center, dtype=float)
        camera = self.plotter.camera
        camera.SetFocalPoint(*center)
        camera.SetPosition(
            center[0],
            center[1] - max_dim * 2.2,
            center[2] + max_dim * 0.55,
        )
        camera.SetViewUp(0.0, 0.0, 1.0)
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()
        self.info_label.setText(
            f"▲ {merged.n_cells:,} yüzey  |  ● {merged.n_points:,} nokta | Kapanış görünümü"
        )
        self.overlay_header.setText("KAPANIŞ — İKI STL HAZIR")
        self._base_camera_distance = float(np.linalg.norm(np.asarray(camera.GetPosition()) - np.asarray(camera.GetFocalPoint())))
        self._zoom_factor = 1.0
        self._update_zoom_indicator()

    def clear(self, preserve_status: bool = False) -> None:
        """Görüntüleyiciyi temizler — tüm mesh ve işaretleyicileri kaldırır."""
        if self.plotter is not None:
            self.plotter.clear()
            self.plotter.add_axes()
        self.current_mesh = None
        self.picked_points.clear()
        self.point_actors.clear()
        self.measurement_actors.clear()
        self._marker_meta.clear()
        self._draggable_marker_names.clear()
        self._drag_marker_name = None
        self._drag_camera_state = None
        self.info_label.setText("")
        self.hide_active_tooth_label()
        self.set_arch_length_value(None)
        self.set_active_tooth(None)
        self.overlay_header.setText(f"{self._jaw_label} — STL BEKLENIYOR")
        self._base_camera_distance = None
        self._zoom_factor = 1.0
        self.zoom_chip.setText("ZOOM 1.0×")
        self.show_workflow_overlay()
        if not preserve_status:
            self.clear_state_message()

    def show_active_tooth_label(self, tooth_fdi: int) -> None:
        """Aktif diş bilgisini büyük bir üst etiket olarak göster."""
        self.overlay_header.setText(f"{self._jaw_label} — DİŞ {tooth_fdi}")
        self.current_tooth_label.setVisible(False)

    def hide_active_tooth_label(self) -> None:
        """Aktif diş üst etiketini gizler."""
        self.current_tooth_label.clear()
        self.current_tooth_label.setVisible(False)
        self.overlay_header.setText(f"{self._jaw_label} — HAZIR")

    def configure_odontogram(self, jaw: str, teeth: list[int]) -> None:
        """Minimal HUD'i aktif eder."""
        self._odontogram_teeth = list(teeth)
        self._jaw_label = "MAKSILLA" if jaw == "maxillary" else "MANDIBULA"
        self.hide_active_tooth_label()
        self.set_overlay_hint(
            "Sol tik ile secin. Space ile ilerleyin, Backspace ile geri alin."
        )
        self.show_workflow_overlay()

    def set_overlay_hint(self, text: str) -> None:
        """Overlay yönlendirme metnini günceller."""
        self.overlay_hint_label.setText(text)

    def set_completed_teeth(self, completed_teeth: list[int] | set[int]) -> None:
        """Minimal HUD modunda tamamlanan dişleri göstermeyiz."""
        return

    def set_active_tooth(self, tooth_fdi: Optional[int]) -> None:
        """HUD içindeki aktif diş bilgisini günceller."""
        if tooth_fdi is None:
            self.overlay_header.setText(f"{self._jaw_label} — HAZIR")
        else:
            self.overlay_header.setText(f"{self._jaw_label} — DİŞ {tooth_fdi}")

    def set_arch_measure_visible(self, visible: bool) -> None:
        """Ark boyu ölçüm eylemini gösterir veya gizler."""
        self.btn_measure_arch.setVisible(False)

    def set_next_stage_visible(self, visible: bool) -> None:
        """Sonraki çeneye geçiş butonunu gösterir veya gizler."""
        self.btn_next_stage.setVisible(False)

    def set_finish_visible(self, visible: bool) -> None:
        """Raporlama butonunu gösterir veya gizler."""
        self.btn_finish_workflow.setVisible(False)

    def set_arch_length_value(self, value_mm: Optional[float]) -> None:
        """Ark boyu bilgisini overlay kartında gösterir."""
        if value_mm is None:
            self.arch_length_label.hide()
            return
        self.arch_length_label.setText(f"ARK BOYU {value_mm:.2f} mm")
        self.arch_length_label.show()

    def show_workflow_overlay(self) -> None:
        """Odontogram ve akış kartını görünür yapar."""
        self.overlay_panel.show()
        self.overlay_panel.raise_()
        self._reposition_overlay()
        self.zoom_chip.show()
        self.zoom_chip.raise_()
        self._reposition_zoom_chip()

    def hide_workflow_overlay(self) -> None:
        """Odontogram ve akış kartını gizler."""
        self.overlay_panel.hide()
        self.zoom_chip.hide()

    def remove_named_actor(self, actor_name: str, render: bool = True) -> None:
        """İsim verilmiş PyVista aktörünü sahneden kaldırır."""
        if self.plotter is None or not actor_name:
            return
        try:
            self.plotter.remove_actor(actor_name, render=render)
        except Exception:
            pass
        if actor_name in self._marker_meta:
            self._marker_meta.pop(actor_name, None)
            self._draggable_marker_names.discard(actor_name)

    def set_draggable_marker_names(self, marker_names: Optional[list[str] | set[str]]) -> None:
        """Aktif olarak sürüklenebilen marker isimlerini sınırlar."""
        self._draggable_marker_names = set(marker_names or [])

    def add_point_marker(
        self,
        point: np.ndarray,
        color: Optional[str] = None,
        radius: float = 0.3,
        label: str = "",
        name: Optional[str] = None,
        render: bool = True,
    ) -> None:
        """
        Mesh üzerinde bir nokta işaretleyici ekler.
        Faz 2'de nokta seçimi sırasında kullanılır.

        Args:
            point: (x, y, z) koordinatları.
            color: İşaretleyici rengi (varsayılan: kırmızı).
            radius: Küre yarıçapı (mm).
            label: Opsiyonel etiket metni.
            name: İşaretleyici ismi (varolanı değiştirmek için).
        """
        if self.plotter is None:
            return

        if color is None:
            color = self.POINT_COLOR

        actor_name = name if name else f"point_{len(self.point_actors)}"
        sphere = pv.Sphere(radius=radius, center=point)
        actor = self.plotter.add_mesh(
            sphere,
            color=color,
            ambient=0.5,
            name=actor_name
        )
        self.point_actors.append(actor)
        self._marker_meta[actor_name] = {
            "point": np.asarray(point, dtype=np.float64),
            "color": color,
            "radius": float(radius),
            "label": label,
        }

        # Etiketi varsa ekle
        if label:
            self.plotter.add_point_labels(
                [point],
                [label],
                font_size=12,
                point_color=color,
                text_color="#16303A",
                shape_color="#FFFFFF",
                shape_opacity=0.7,
                name=f"label_{actor_name}"
            )

        # safe_paintEvent workaround'undan dolayı ekranı manuel güncelle
        if render:
            self.plotter.render()

    def add_measurement_line(
        self,
        point_a: np.ndarray,
        point_b: np.ndarray,
        label: str = "",
        color: Optional[str] = None,
        name: Optional[str] = None,
        render: bool = True,
    ) -> None:
        """
        İki nokta arasında ölçüm çizgisi çizer.

        Args:
            point_a: Başlangıç noktası (x, y, z).
            point_b: Bitiş noktası (x, y, z).
            label: Mesafe etiketi (ör. "8.5 mm").
            color: Çizgi rengi.
        """
        if self.plotter is None:
            return

        if color is None:
            color = self.LINE_COLOR

        line = pv.Line(point_a, point_b)
        line_name = name if name else f"line_{len(self.measurement_actors)}"
        actor = self.plotter.add_mesh(
            line,
            color=color,
            line_width=3,
            name=line_name
        )
        self.measurement_actors.append(actor)

        # Orta noktaya mesafe etiketi ekle
        if label:
            midpoint = (np.asarray(point_a) + np.asarray(point_b)) / 2.0
            self.plotter.add_point_labels(
                [midpoint],
                [label],
                font_size=14,
                point_color=color,
                text_color="#16303A",
                shape_color="#FFFFFF",
                shape_opacity=0.8,
                name=f"dist_label_{line_name}"
            )

        # safe_paintEvent workaround'undan dolayı ekranı manuel güncelle
        if render:
            self.plotter.render()

    def _pick_surface_point(self, display_x: int, display_y: int) -> Optional[np.ndarray]:
        """Ekran koordinatından mesh yüzeyi üzerinde bir nokta seçer."""
        if self.plotter is None or self.current_mesh is None:
            return None

        from pyvista.plotting import _vtk

        try:
            renderer = self.plotter.iren.get_poked_renderer()
            picker = _vtk.vtkCellPicker()
            picker.SetTolerance(0.025)
            picker.Pick(display_x, display_y, 0, renderer)
            picked = np.asarray(picker.GetPickPosition(), dtype=np.float64)
            if picked.shape != (3,) or not np.all(np.isfinite(picked)):
                return None
            return picked
        except Exception:
            return None

    def _snap_to_nearest_vertex(self, point: np.ndarray) -> Optional[np.ndarray]:
        """Seçilen yüzey noktasını en yakın vertex'e sabitler."""
        if self.current_mesh is None:
            return None

        pt = np.asarray(point, dtype=np.float64)
        vertices = np.asarray(self.current_mesh.points, dtype=np.float64)
        if pt.shape != (3,) or vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
            return None

        deltas = vertices - pt
        nearest_idx = int(np.argmin(np.einsum("ij,ij->i", deltas, deltas)))
        snapped = np.asarray(vertices[nearest_idx], dtype=np.float64)
        if snapped.shape != (3,) or not np.all(np.isfinite(snapped)):
            return None
        return snapped

    def _world_to_display(self, point: np.ndarray) -> Optional[np.ndarray]:
        """3B dünya koordinatını ekran koordinatına dönüştürür."""
        if self.plotter is None:
            return None

        try:
            renderer = self.plotter.renderer
            renderer.SetWorldPoint(float(point[0]), float(point[1]), float(point[2]), 1.0)
            renderer.WorldToDisplay()
            display_point = np.asarray(renderer.GetDisplayPoint(), dtype=np.float64)
            if display_point.shape[0] < 2 or not np.all(np.isfinite(display_point[:2])):
                return None
            return display_point[:2]
        except Exception:
            return None

    def _find_draggable_marker_at(self, display_x: int, display_y: int) -> Optional[str]:
        """İmlecin altında aktif olarak sürüklenebilir bir marker arar."""
        if not self._draggable_marker_names:
            return None

        cursor = np.asarray([display_x, display_y], dtype=np.float64)
        best_name = None
        best_distance = 18.0

        for marker_name in self._draggable_marker_names:
            meta = self._marker_meta.get(marker_name)
            if not meta:
                continue
            projected = self._world_to_display(np.asarray(meta["point"], dtype=np.float64))
            if projected is None:
                continue
            distance = float(np.linalg.norm(projected - cursor))
            if distance <= best_distance:
                best_distance = distance
                best_name = marker_name

        return best_name

    def _capture_camera_state(self) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Drag sırasında kamera kaymasını sıfırlamak için mevcut durumu yakalar."""
        if self.plotter is None:
            return None
        try:
            camera = self.plotter.camera
            return (
                np.asarray(camera.GetPosition(), dtype=np.float64),
                np.asarray(camera.GetFocalPoint(), dtype=np.float64),
                np.asarray(camera.GetViewUp(), dtype=np.float64),
            )
        except Exception:
            return None

    def _restore_camera_state(self, state: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> None:
        """Kaydedilmiş kamera durumunu geri yükler."""
        if self.plotter is None or state is None:
            return
        try:
            camera = self.plotter.camera
            position, focal_point, view_up = state
            camera.SetPosition(*position)
            camera.SetFocalPoint(*focal_point)
            camera.SetViewUp(*view_up)
            self.plotter.renderer.ResetCameraClippingRange()
        except Exception:
            pass

    def _move_named_marker(self, marker_name: str, point: np.ndarray) -> bool:
        """Varolan marker'ı yeni noktaya taşır ve görünümünü korur."""
        meta = self._marker_meta.get(marker_name)
        if meta is None:
            return False

        self.remove_named_actor(marker_name, render=False)
        self.remove_named_actor(f"label_{marker_name}", render=False)
        self.add_point_marker(
            np.asarray(point, dtype=np.float64),
            color=str(meta["color"]),
            radius=float(meta["radius"]),
            label=str(meta["label"]),
            name=marker_name,
            render=False,
        )
        return True

    # ──────────────────────────────────────────────
    # FAZ 2: NOKTA SEÇİM MODU (Point Picking)
    # ──────────────────────────────────────────────

    def enable_picking(self) -> None:
        """
        Mesh üzerinde nokta seçim modunu etkinleştirir.

        Klinik İş Akışı:
            Sol tık yalnızca nokta seçer.
            Sağ tık modeli döndürmeye, fare tekerleği ise zoom'a devam eder.
        """
        if self.current_mesh is None or self.plotter is None:
            return

        def _on_pick(point):
            if point is None:
                return
            snapped = self._snap_to_nearest_vertex(point)
            if snapped is None:
                return
            pt = np.asarray(snapped, dtype=np.float64)
            if pt.shape != (3,) or not np.all(np.isfinite(pt)):
                return
            self.picked_points.append(pt)
            self.point_picked.emit(pt)

        def _on_left_press(*_args):
            try:
                press_x, press_y = self.plotter.iren.get_event_position()
                self._pick_press_position = (press_x, press_y)
                self._drag_marker_name = self._find_draggable_marker_at(press_x, press_y)
                self._drag_camera_state = self._capture_camera_state() if self._drag_marker_name else None
            except Exception:
                self._pick_press_position = None
                self._drag_marker_name = None
                self._drag_camera_state = None
            self._pick_dragging = False

        def _on_mouse_move(*_args):
            if self._pick_press_position is None:
                return
            try:
                cur_x, cur_y = self.plotter.iren.get_event_position()
            except Exception:
                return
            dx = cur_x - self._pick_press_position[0]
            dy = cur_y - self._pick_press_position[1]
            if (dx * dx + dy * dy) > 25:
                self._pick_dragging = True

            if self._drag_marker_name is None or not self._pick_dragging:
                return

            surface_point = self._pick_surface_point(cur_x, cur_y)
            snapped = None if surface_point is None else self._snap_to_nearest_vertex(surface_point)
            if snapped is None:
                return

            if self._move_named_marker(self._drag_marker_name, snapped):
                self._restore_camera_state(self._drag_camera_state)
                self.plotter.render()
                self.marker_moved.emit(self._drag_marker_name, np.asarray(snapped, dtype=np.float64))

        def _pick_from_release(*_args):
            if self._drag_marker_name is not None:
                if self._pick_dragging:
                    try:
                        release_x, release_y = self.plotter.iren.get_event_position()
                        surface_point = self._pick_surface_point(release_x, release_y)
                        snapped = None if surface_point is None else self._snap_to_nearest_vertex(surface_point)
                        if snapped is not None and self._move_named_marker(self._drag_marker_name, snapped):
                            self._restore_camera_state(self._drag_camera_state)
                            self.plotter.render()
                            self.marker_moved.emit(
                                self._drag_marker_name,
                                np.asarray(snapped, dtype=np.float64),
                            )
                    except Exception:
                        pass
                self._pick_press_position = None
                self._pick_dragging = False
                self._drag_marker_name = None
                self._drag_camera_state = None
                return

            if self._pick_dragging or self._pick_press_position is None:
                self._pick_press_position = None
                self._pick_dragging = False
                return
            try:
                click_x, click_y = self.plotter.iren.get_event_position()
                picked = self._pick_surface_point(click_x, click_y)
                if picked is not None:
                    _on_pick(picked)
            except Exception:
                pass
            finally:
                self._pick_press_position = None
                self._pick_dragging = False
                self._drag_marker_name = None
                self._drag_camera_state = None

        self.disable_picking()

        self._apply_navigation_style()

        try:
            self.plotter.track_mouse_position()
            self._mouse_tracking_enabled = True
        except TypeError:
            pass
        except Exception:
            pass

        try:
            self._left_pick_observer = self.plotter.iren.add_observer(
                "LeftButtonPressEvent",
                _on_left_press,
            )
            self._mouse_move_pick_observer = self.plotter.iren.add_observer(
                "MouseMoveEvent",
                _on_mouse_move,
            )
            self._left_release_observer = self.plotter.iren.add_observer(
                "LeftButtonReleaseEvent",
                _pick_from_release,
            )
            self._click_tracking_enabled = True
        except Exception:
            self._left_pick_observer = None
            self._left_release_observer = None
            self._mouse_move_pick_observer = None
            self._click_tracking_enabled = False

    def _focus_on_hovered_point(self) -> None:
        """Fare imlecinin altındaki mesh noktasına kamerayı yumuşakça yaklaştır."""
        if self.plotter is None or self.current_mesh is None:
            return

        try:
            self.plotter.fly_to_mouse_position()
            self.plotter.render()
        except Exception:
            try:
                point = np.asarray(self.plotter.pick_mouse_position(), dtype=np.float64)
                if point.shape == (3,) and np.all(np.isfinite(point)):
                    self.plotter.fly_to(point)
                    self.plotter.render()
            except Exception:
                pass

    def disable_picking(self) -> None:
        """Nokta seçim modunu kapatır — normal döndürme/zoom moduna döner."""
        if self.plotter is None:
            return
        if self._left_pick_observer is not None:
            try:
                self.plotter.iren.remove_observer(self._left_pick_observer)
            except Exception:
                pass
            self._left_pick_observer = None
        if self._left_release_observer is not None:
            try:
                self.plotter.iren.remove_observer(self._left_release_observer)
            except Exception:
                pass
            self._left_release_observer = None
        if self._mouse_move_pick_observer is not None:
            try:
                self.plotter.iren.remove_observer(self._mouse_move_pick_observer)
            except Exception:
                pass
            self._mouse_move_pick_observer = None
        self._pick_press_position = None
        self._pick_dragging = False
        self._drag_marker_name = None
        self._drag_camera_state = None
        self._click_tracking_enabled = False
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        self._apply_navigation_style()

    def _apply_touchpad_zoom(self, delta: float) -> bool:
        """Touchpad/wheel delta'sını yumuşak kamera zoom'una dönüştür."""
        if self.plotter is None or self.current_mesh is None or abs(delta) < 1e-6:
            return False

        factor = float(np.exp(delta * 0.0015))
        factor = max(0.7, min(1.35, factor))

        try:
            self.plotter.camera.Zoom(factor)
            self.plotter.renderer.ResetCameraClippingRange()
            self.plotter.render()
            self._update_zoom_indicator()
            return True
        except Exception:
            return False

    def _apply_touchpad_pan(self, delta_x: float, delta_y: float) -> bool:
        """Touchpad iki parmak kaydırmayı kamera pan hareketine dönüştür."""
        if self.plotter is None or self.current_mesh is None:
            return False
        if abs(delta_x) < 1e-6 and abs(delta_y) < 1e-6:
            return False

        camera = self.plotter.camera
        position = np.array(camera.GetPosition(), dtype=float)
        focal_point = np.array(camera.GetFocalPoint(), dtype=float)
        view_up = np.array(camera.GetViewUp(), dtype=float)

        forward = focal_point - position
        forward_norm = np.linalg.norm(forward)
        if forward_norm < 1e-6:
            return False
        forward = forward / forward_norm

        right = np.cross(forward, view_up)
        right_norm = np.linalg.norm(right)
        if right_norm < 1e-6:
            return False
        right = right / right_norm

        up = np.cross(right, forward)
        up_norm = np.linalg.norm(up)
        if up_norm < 1e-6:
            return False
        up = up / up_norm

        # Touchpad delta'larını ekran yüksekliğine ve kamera mesafesine göre
        # normalize ederek ani "ucma" etkisini azalt.
        viewport_height = max(float(self.height()), 1.0)
        view_angle = float(camera.GetViewAngle() or 30.0)
        visible_height = 2.0 * forward_norm * np.tan(np.radians(view_angle) / 2.0)
        units_per_pixel = visible_height / viewport_height

        clamped_dx = float(np.clip(delta_x, -36.0, 36.0))
        clamped_dy = float(np.clip(delta_y, -36.0, 36.0))
        pan_scale = units_per_pixel * 0.45
        translation = (-right * clamped_dx + up * clamped_dy) * pan_scale

        try:
            camera.SetPosition(*(position + translation))
            camera.SetFocalPoint(*(focal_point + translation))
            self.plotter.renderer.ResetCameraClippingRange()
            self.plotter.render()
            return True
        except Exception:
            return False

    def eventFilter(self, watched, event):
        """Wheel ve native gesture olaylarını touchpad-dostu zoom'a çevir."""
        if watched is self.plotter and self.plotter is not None:
            if event.type() == QEvent.Type.Wheel:
                angle = event.angleDelta()
                pixel = event.pixelDelta()
                has_touchpad_delta = not pixel.isNull()

                if has_touchpad_delta:
                    if self._apply_touchpad_pan(float(pixel.x()), float(pixel.y())):
                        event.accept()
                        return True
                else:
                    delta_y = float(angle.y())
                    if delta_y and self._apply_touchpad_zoom(delta_y):
                        event.accept()
                        return True

            if event.type() == QEvent.Type.NativeGesture:
                try:
                    gesture_type = event.gestureType()
                    if gesture_type == Qt.NativeGestureType.ZoomNativeGesture:
                        if self._apply_touchpad_zoom(float(event.value()) * 240.0):
                            event.accept()
                            return True
                except Exception:
                    pass

        return super().eventFilter(watched, event)

    def _reposition_overlay(self) -> None:
        """Overlay kartını görüntüleyicinin sol üstüne yerleştir."""
        if self.overlay_panel is None:
            return
        margin = 18
        width = self.overlay_panel.width()
        height = self.overlay_panel.sizeHint().height()
        self.overlay_panel.setGeometry(
            margin,
            70,
            width,
            min(height, max(220, self.height() - 90)),
        )

    def _reposition_zoom_chip(self) -> None:
        """Zoom göstergesini alt sağa yerleştirir."""
        if self.zoom_chip is None:
            return
        margin = 18
        self.zoom_chip.move(
            max(margin, self.width() - self.zoom_chip.width() - margin),
            max(margin, self.height() - self.zoom_chip.height() - margin),
        )

    def resizeEvent(self, event) -> None:
        """Widget yeniden boyutlandığında overlay yerini koru."""
        super().resizeEvent(event)
        self._reposition_overlay()
        self._reposition_zoom_chip()

    def close(self) -> None:
        """Widget kapatılırken PyVista plotter'ı temizle."""
        try:
            if self.plotter is not None:
                self.plotter.close()
        except Exception:
            pass
        super().close()
