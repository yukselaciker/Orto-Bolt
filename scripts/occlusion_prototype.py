"""
Minimal okluzyon prototipi
==========================

Amaç:
    3Shape dışa aktarımı üst ve alt çene meshlerini orijinal world-space
    koordinatlarında açmak ve alt çeneyi yalnızca X/Y düzleminde manuel
    ötelemek.

Önemli Klinik Kural:
    Mesh'lere kesinlikle auto-centering uygulanmaz. Dosyalar yüklenirken
    3Shape tarafından verilen uzay koordinatları birebir korunur.

Çalıştırma:
    python scripts/occlusion_prototype.py

Varsayılan dosya adları:
    - ust_cene.stl / ust_cene.ply
    - alt_cene.stl / alt_cene.ply

Varsayılan dosyalar bulunamazsa uygulama açılışta kullanıcıdan seçim ister.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from pyvista.plotting import _vtk


SUPPORTED_EXTENSIONS = (".stl", ".ply")


def _translation_matrix(tx: float, ty: float) -> np.ndarray:
    """Yalnızca X ve Y düzleminde öteleme yapan 4x4 homojen matris üretir."""
    matrix = np.eye(4, dtype=float)
    matrix[0, 3] = tx
    matrix[1, 3] = ty
    return matrix


def _numpy_to_vtk_matrix(matrix: np.ndarray) -> _vtk.vtkMatrix4x4:
    """NumPy 4x4 matrisi VTK matrise çevirir."""
    vtk_matrix = _vtk.vtkMatrix4x4()
    for row in range(4):
        for col in range(4):
            vtk_matrix.SetElement(row, col, float(matrix[row, col]))
    return vtk_matrix


def _resolve_default_file(candidates: Iterable[str]) -> Path | None:
    """Varsayılan mesh dosyalarını çalışma klasörü ve proje kökünde arar."""
    search_roots = [Path.cwd(), Path(__file__).resolve().parent.parent]
    for root in search_roots:
        for candidate in candidates:
            path = root / candidate
            if path.exists():
                return path
    return None


def _scene_to_single_mesh(scene: trimesh.Scene) -> trimesh.Trimesh:
    """
    Trimesh scene içindeki tüm geometrileri world-space korunarak tek meshe birleştirir.

    Not:
        process=False ile yüklediğimiz için yüzeyler yeniden merkezlenmez veya
        otomatik temizlenmez.
    """
    geometries: list[trimesh.Trimesh] = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        geometry = scene.geometry[geometry_name].copy()
        geometry.apply_transform(transform)
        geometries.append(geometry)

    if not geometries:
        raise ValueError("Scene içinde görüntülenecek geometri bulunamadı.")

    if len(geometries) == 1:
        return geometries[0]

    return trimesh.util.concatenate(geometries)


def load_mesh_preserve_world(file_path: Path) -> pv.PolyData:
    """
    STL/PLY mesh'i world-space koordinatlarını koruyarak yükler.

    Çok kritik:
        process=False kullanılır; böylece trimesh mesh üzerinde normalize,
        center veya temizlik adımı uygulamaz.
    """
    loaded = trimesh.load(file_path, process=False, maintain_order=True, force="mesh")

    if isinstance(loaded, trimesh.Scene):
        tri_mesh = _scene_to_single_mesh(loaded)
    elif isinstance(loaded, trimesh.Trimesh):
        tri_mesh = loaded
    else:
        raise TypeError(f"Desteklenmeyen mesh tipi: {type(loaded)!r}")

    if tri_mesh.vertices.size == 0 or tri_mesh.faces.size == 0:
        raise ValueError(f"Mesh boş veya geçersiz: {file_path.name}")

    faces_with_sizes = np.hstack(
        (
            np.full((len(tri_mesh.faces), 1), 3, dtype=np.int64),
            tri_mesh.faces.astype(np.int64),
        )
    ).ravel()

    mesh = pv.PolyData(tri_mesh.vertices.astype(np.float64), faces_with_sizes)
    mesh.compute_normals(inplace=True, split_vertices=False, consistent_normals=True)
    return mesh


class SliderRow(QWidget):
    """Minimalist tek satır slider bileşeni."""

    def __init__(
        self,
        title: str,
        min_value: int,
        max_value: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value_label = QLabel("0.0 mm")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(min_value, max_value)
        self.slider.setValue(0)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)

        title_label = QLabel(title)
        title_label.setObjectName("controlTitle")
        self._value_label.setObjectName("valueLabel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(title_label)
        top_row.addStretch(1)
        top_row.addWidget(self._value_label)

        layout.addLayout(top_row)
        layout.addWidget(self.slider)

    def set_mm_text(self, value_mm: float) -> None:
        self._value_label.setText(f"{value_mm:+.1f} mm")


class OcclusionPrototypeWindow(QMainWindow):
    """Üst/alt çene oklüzyon prototipi ana penceresi."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SelçukBolt | Okluzyon Prototipi")
        self.resize(1360, 860)

        self.plotter: QtInteractor | None = None
        self.maxilla_actor = None
        self.mandible_actor = None
        self.maxilla_mesh: pv.PolyData | None = None
        self.mandible_mesh: pv.PolyData | None = None

        self.transversal_mm = 0.0
        self.sagittal_mm = 0.0

        self.maxilla_path = _resolve_default_file(["ust_cene.stl", "ust_cene.ply"])
        self.mandible_path = _resolve_default_file(["alt_cene.stl", "alt_cene.ply"])

        self._build_ui()
        self._load_startup_meshes()

    def _build_ui(self) -> None:
        """Arayüzü kurar: büyük viewport + yalnızca iki slider."""
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QFrame()
        header.setObjectName("headerCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(6)

        title = QLabel("3Shape Okluzyon Prototipi")
        title.setObjectName("windowTitle")
        subtitle = QLabel(
            "Mesh'ler world-space koordinatlarinda yuklenir. Alt cene sadece sag-sol ve on-arka yonlerde kaydirilir."
        )
        subtitle.setObjectName("subtitle")

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        viewport_frame = QFrame()
        viewport_frame.setObjectName("viewportCard")
        viewport_layout = QVBoxLayout(viewport_frame)
        viewport_layout.setContentsMargins(10, 10, 10, 10)
        viewport_layout.setSpacing(0)

        self.plotter = QtInteractor(viewport_frame)
        viewport_layout.addWidget(self.plotter.interactor)
        root.addWidget(viewport_frame, 1)

        controls = QFrame()
        controls.setObjectName("controlsCard")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(16, 16, 16, 16)
        controls_layout.setSpacing(14)

        self.transversal_slider = SliderRow("Sag-Sol Kaydirma (X / Transversal)", -100, 100)
        self.sagittal_slider = SliderRow("On-Arka Kaydirma (Y / Sagital)", -100, 100)

        self.transversal_slider.slider.valueChanged.connect(self._on_transversal_changed)
        self.sagittal_slider.slider.valueChanged.connect(self._on_sagittal_changed)

        self.transversal_slider.set_mm_text(0.0)
        self.sagittal_slider.set_mm_text(0.0)

        controls_layout.addWidget(self.transversal_slider)
        controls_layout.addWidget(self.sagittal_slider)
        root.addWidget(controls)

        self.setStyleSheet(
            """
            QMainWindow {
                background: #EFF2F5;
            }
            QFrame#headerCard, QFrame#controlsCard, QFrame#viewportCard {
                background: #FAFBFC;
                border: 1px solid #D8E0E8;
                border-radius: 14px;
            }
            QLabel#windowTitle {
                color: #1E293B;
                font-size: 21px;
                font-weight: 700;
            }
            QLabel#subtitle {
                color: #64748B;
                font-size: 12px;
            }
            QLabel#controlTitle {
                color: #334155;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#valueLabel {
                color: #0F172A;
                background: #E8EEF6;
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QSlider::groove:horizontal {
                background: #D7DEE7;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #5B8FF9;
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #9DB9FF;
                border-radius: 3px;
            }
            """
        )

    def _load_startup_meshes(self) -> None:
        """Varsayılan dosyaları yükler; yoksa kullanıcıdan seçim ister."""
        try:
            if self.maxilla_path is None:
                self.maxilla_path = self._ask_mesh_file("Ust cene dosyasini secin")
            if self.mandible_path is None:
                self.mandible_path = self._ask_mesh_file("Alt cene dosyasini secin")

            if self.maxilla_path is None or self.mandible_path is None:
                raise FileNotFoundError("Her iki cene dosyasi secilmeden prototip baslatilamaz.")

            self.maxilla_mesh = load_mesh_preserve_world(self.maxilla_path)
            self.mandible_mesh = load_mesh_preserve_world(self.mandible_path)
            self._render_scene()
        except Exception as exc:  # noqa: BLE001 - prototipte kullanıcıya net mesaj önemli
            QMessageBox.critical(self, "Mesh Yukleme Hatasi", str(exc))
            self.close()

    def _ask_mesh_file(self, title: str) -> Path | None:
        """Dosya bulunamazsa kullanıcıdan STL/PLY seçim ister."""
        selected, _ = QFileDialog.getOpenFileName(
            self,
            title,
            str(Path.cwd()),
            "Mesh Dosyalari (*.stl *.ply)",
        )
        return Path(selected) if selected else None

    def _render_scene(self) -> None:
        """PyVista sahnesini oluşturur ve mesh'leri orijinal koordinatlarda gösterir."""
        if self.plotter is None or self.maxilla_mesh is None or self.mandible_mesh is None:
            return

        self.plotter.clear()
        self.plotter.set_background("#EEF2F4")
        self.plotter.enable_trackball_style()

        # Yumuşak ve klinik görünümlü pastel renkler.
        self.maxilla_actor = self.plotter.add_mesh(
            self.maxilla_mesh,
            color="#F4E7D5",
            smooth_shading=True,
            ambient=0.35,
            diffuse=0.78,
            specular=0.03,
            specular_power=4,
            name="maxilla",
        )
        self.mandible_actor = self.plotter.add_mesh(
            self.mandible_mesh,
            color="#EDE1CE",
            smooth_shading=True,
            ambient=0.35,
            diffuse=0.78,
            specular=0.03,
            specular_power=4,
            name="mandible",
        )

        self.plotter.add_axes(line_width=1, labels_off=True)
        self.plotter.show_grid(color="#D5DDE5", xtitle="", ytitle="", ztitle="")
        self._apply_mandible_translation()
        self.plotter.reset_camera()
        self.plotter.render()

    def _apply_mandible_translation(self) -> None:
        """
        Alt çeneye yalnızca X/Y öteleme matrisi uygular.

        Önemli:
            Mesh verisini kopyalayıp yeniden taşımak yerine actor üzerinde
            kullanıcı matrisi uygulanır. Böylece orijinal world-space veri
            korunur ve slider hareketi akıcı kalır.
        """
        if self.mandible_actor is None:
            return

        matrix = _translation_matrix(self.transversal_mm, self.sagittal_mm)
        self.mandible_actor.SetUserMatrix(_numpy_to_vtk_matrix(matrix))
        if self.plotter is not None:
            self.plotter.render()

    def _on_transversal_changed(self, raw_value: int) -> None:
        """Sağ-sol slider değeri 0.1 mm hassasiyetle X ötelemesine çevrilir."""
        self.transversal_mm = raw_value / 10.0
        self.transversal_slider.set_mm_text(self.transversal_mm)
        self._apply_mandible_translation()

    def _on_sagittal_changed(self, raw_value: int) -> None:
        """Ön-arka slider değeri 0.1 mm hassasiyetle Y ötelemesine çevrilir."""
        self.sagittal_mm = raw_value / 10.0
        self.sagittal_slider.set_mm_text(self.sagittal_mm)
        self._apply_mandible_translation()


def main() -> int:
    app = QApplication(sys.argv)
    window = OcclusionPrototypeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
