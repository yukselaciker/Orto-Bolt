"""
2.5D Height Map / Z-Buffer Okluzyon Prototipi
============================================

Amaç:
    Üst ve alt çene STL/PLY taramalarını orijinal 3Shape world-space
    koordinatlarında açmak, ardından alt çeneyi sadece X/Y düzleminde
    kaydırırken temas düzeltmesini tam 3D collision yerine 2D yükseklik
    haritaları (height map) ile gerçek zamanlı hesaplamak.

Temel fikir:
    - Mesh'ler açılışta yalnızca bir kez raycasting ile 2D grid üzerine
      projekte edilir.
    - Üst çene için alt yüzeyin Z haritası (minimum Z) çıkarılır.
    - Alt çene için üst yüzeyin Z haritası (maximum Z) çıkarılır.
    - Slider değiştiğinde yalnızca lower_z_map grid'i kaydırılır.
    - overlap = lower_shifted - upper_map
    - z_düzeltme = -max(overlap)
    - Bu Z düzeltmesi yüksek çözünürlüklü görsel mesh actor'üne uygulanır.

Önemli:
    - Update döngüsünde kesinlikle raycasting yoktur.
    - Auto-centering yapılmaz; world-space korunur.
    - Bu prototip klinik fikir doğrulama amaçlıdır.

Çalıştırma:
    python scripts/heightmap_occlusion_prototype.py
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh
from scipy.ndimage import binary_erosion, binary_fill_holes


def configure_qt_environment() -> None:
    """macOS üzerinde Qt cocoa plugin ve framework yollarını görünür yapar."""
    os.environ.setdefault("QT_API", "pyside6")
    os.environ.setdefault("PYVISTA_QT_BACKEND", "PySide6")
    os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

    if sys.platform != "darwin":
        return

    try:
        import PySide6  # noqa: F401
    except Exception:
        return

    qt_root = Path(PySide6.__file__).resolve().parent / "Qt"
    qt_plugins = qt_root / "plugins"
    qt_platforms = qt_plugins / "platforms"
    qt_lib = qt_root / "lib"

    if qt_plugins.exists():
        os.environ["QT_PLUGIN_PATH"] = str(qt_plugins)
    if qt_platforms.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_platforms)
    if qt_lib.exists():
        lib_path = str(qt_lib)
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            current = os.environ.get(key, "")
            pieces = [lib_path]
            if current:
                pieces.extend(part for part in current.split(":") if part and part != lib_path)
            os.environ[key] = ":".join(pieces)


def activate_macos_app() -> None:
    """Qt penceresini macOS'ta öne almaya çalışır."""
    if sys.platform != "darwin":
        return

    try:
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        msg_send = objc.objc_msgSend
        msg_send.restype = ctypes.c_void_p
        msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        ns_application = objc.objc_getClass(b"NSApplication")
        shared_application = objc.sel_registerName(b"sharedApplication")
        app = msg_send(ns_application, shared_application)

        set_activation_policy = objc.sel_registerName(b"setActivationPolicy:")
        activate_ignoring_other_apps = objc.sel_registerName(b"activateIgnoringOtherApps:")

        msg_send.restype = None
        msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        msg_send(app, set_activation_policy, 0)

        msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        msg_send(app, activate_ignoring_other_apps, True)
    except Exception:
        return


configure_qt_environment()

import pyvista as pv
from pyvista.plotting import _vtk
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


SUPPORTED_EXTENSIONS = (".stl", ".ply")
GRID_RESOLUTION_MM = 0.1
RAY_MARGIN_MM = 4.0
TRANSVERSAL_RANGE_MM = (-10.0, 10.0)
SAGITTAL_RANGE_MM = (-15.0, 15.0)
DEBUG_DISABLE_COLLISION = False
CROWN_HEIGHT_LIMIT_MM = 15.0

# 3Shape world-space varsayımı:
# X = sağ-sol, Y = ön-arka, Z = vertikal
# Grid[satır, sütun] => [Y, X]
GRID_X_SIGN = +1
GRID_Y_SIGN = +1


def _translation_matrix(tx: float, ty: float, tz: float) -> np.ndarray:
    """X/Y/Z ötelenmesi için 4x4 homojen transformasyon matrisi üretir."""
    matrix = np.eye(4, dtype=float)
    matrix[0, 3] = tx
    matrix[1, 3] = ty
    matrix[2, 3] = tz
    return matrix


def fast_shift_2d(arr: np.ndarray, shift_y: int, shift_x: int) -> np.ndarray:
    """
    2D matrisi wrap-around olmadan, NaN ile doldurarak çok hızlı kaydırır.

    Grid eşlemesi:
        axis 0 (satırlar) -> Y
        axis 1 (sütunlar) -> X
    """
    res = np.full_like(arr, np.nan)
    y_start_orig = max(0, -shift_y)
    y_end_orig = arr.shape[0] - max(0, shift_y)
    x_start_orig = max(0, -shift_x)
    x_end_orig = arr.shape[1] - max(0, shift_x)

    y_start_res = max(0, shift_y)
    y_end_res = res.shape[0] - max(0, -shift_y)
    x_start_res = max(0, shift_x)
    x_end_res = res.shape[1] - max(0, -shift_x)

    if y_start_orig >= y_end_orig or x_start_orig >= x_end_orig:
        return res

    res[y_start_res:y_end_res, x_start_res:x_end_res] = arr[
        y_start_orig:y_end_orig, x_start_orig:x_end_orig
    ]
    return res


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


def _parse_startup_paths() -> tuple[Path | None, Path | None]:
    """
    Komut satırından üst ve alt çene dosya yolu alır.

    Kullanım:
        python scripts/heightmap_occlusion_prototype.py /path/ust.stl /path/alt.stl
    """
    if len(sys.argv) >= 3:
        return Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    return None, None


def _scene_to_single_mesh(scene: trimesh.Scene) -> trimesh.Trimesh:
    """Scene içindeki tüm geometrileri world-space korunarak tek meshe birleştirir."""
    geometries: list[trimesh.Trimesh] = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        geometry = scene.geometry[geometry_name].copy()
        geometry.apply_transform(transform)
        geometries.append(geometry)

    if not geometries:
        raise ValueError("Scene içinde geometri bulunamadı.")
    if len(geometries) == 1:
        return geometries[0]
    return trimesh.util.concatenate(geometries)


def load_trimesh_preserve_world(file_path: Path) -> trimesh.Trimesh:
    """
    Mesh'i world-space koordinatlarını bozmadan yükler.

    Çok önemli:
        process=False ile trimesh normalize / merkezleme yapmaz.
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
    return tri_mesh


def trimesh_to_pyvista(mesh: trimesh.Trimesh) -> pv.PolyData:
    """Trimesh -> PyVista PolyData dönüşümü."""
    faces_with_sizes = np.hstack(
        (
            np.full((len(mesh.faces), 1), 3, dtype=np.int64),
            mesh.faces.astype(np.int64),
        )
    ).ravel()
    poly = pv.PolyData(mesh.vertices.astype(np.float64), faces_with_sizes)
    poly.compute_normals(inplace=True, split_vertices=False, consistent_normals=True)
    return poly


def rotate_meshes_for_occlusal_heightmap(
    upper_mesh: trimesh.Trimesh,
    lower_mesh: trimesh.Trimesh,
    angle_rad: float = -np.pi / 2,
) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """
    3Shape world-space eksenlerini height-map üretimi için oklüzal düzleme yatırır.

    Not:
        Görsel actor'ler için değil, yalnızca Z-map çıkarımı için kullanılan kopyalara uygulanır.
    """
    rot_matrix = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, np.cos(angle_rad), -np.sin(angle_rad), 0.0],
            [0.0, np.sin(angle_rad), np.cos(angle_rad), 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=float,
    )

    upper_rot = upper_mesh.copy()
    lower_rot = lower_mesh.copy()
    upper_rot.apply_transform(rot_matrix)
    lower_rot.apply_transform(rot_matrix)
    return upper_rot, lower_rot


@dataclass(slots=True)
class HeightMapBundle:
    x_coords: np.ndarray
    y_coords: np.ndarray
    upper_z_map: np.ndarray
    lower_z_map: np.ndarray
    resolution_mm: float
    z_offset_calibration: float


def _batched_ray_intersections(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    directions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Çok sayıda ray'i tek çağrıda mesh'e çarptırır.

    Dönüş:
        (z_hits, ray_indices)
    """
    try:
        locations, ray_indices, _ = mesh.ray.intersects_location(
            ray_origins=origins,
            ray_directions=directions,
            multiple_hits=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Raycasting başarısız: {exc}") from exc

    if locations.size == 0:
        return np.empty((0,), dtype=float), np.empty((0,), dtype=np.int64)

    return locations[:, 2].astype(float), ray_indices.astype(np.int64)


def _light_spatial_mask(
    z_map: np.ndarray,
    *,
    z_min: float = -12.0,
    z_max: float = 12.0,
    resolution: float = GRID_RESOLUTION_MM,
    erode_mm: float = 1.0,
) -> np.ndarray:
    """
    Mutlak Z koridorunda padding destekli hafif dış sınır tıraşlaması uygular.
    """
    valid_mask = np.isfinite(z_map)
    if not np.any(valid_mask):
        return z_map

    candidate_mask = valid_mask & (z_map > z_min) & (z_map < z_max)
    if not np.any(candidate_mask):
        return z_map

    pad_width = 10
    padded_mask = np.pad(candidate_mask, pad_width=pad_width, mode="constant", constant_values=False)
    solid_hull = binary_fill_holes(padded_mask)
    erode_pixels = max(0, int(erode_mm / max(resolution, 1e-6)))
    if erode_pixels > 0:
        shaved_padded = binary_erosion(
            solid_hull,
            structure=np.ones((3, 3), dtype=bool),
            iterations=erode_pixels,
        )
    else:
        shaved_padded = solid_hull

    shaved_mask = shaved_padded[pad_width:-pad_width, pad_width:-pad_width]
    final_mask = shaved_mask & candidate_mask
    return np.where(final_mask, z_map, np.nan)


def apply_crown_only_mask(
    upper_z_map: np.ndarray,
    lower_z_map: np.ndarray,
    crown_height_limit_mm: float = CROWN_HEIGHT_LIMIT_MM,
    resolution_mm: float = GRID_RESOLUTION_MM,
) -> tuple[np.ndarray, np.ndarray]:
    """
    V6b: Üst çeneye hafif, alt çeneye agresif padding destekli sınır erozyonu uygular.
    """
    upper_masked = _light_spatial_mask(
        upper_z_map,
        z_min=-crown_height_limit_mm,
        z_max=crown_height_limit_mm,
        resolution=resolution_mm,
        erode_mm=1.0,
    )
    lower_masked = _light_spatial_mask(
        lower_z_map,
        z_min=-crown_height_limit_mm,
        z_max=crown_height_limit_mm,
        resolution=resolution_mm,
        erode_mm=7.0,
    )
    return upper_masked, lower_masked


def build_height_maps(
    upper_mesh: trimesh.Trimesh,
    lower_mesh: trimesh.Trimesh,
    resolution_mm: float = GRID_RESOLUTION_MM,
) -> HeightMapBundle:
    """
    Üst ve alt çene için 2.5D yükseklik haritalarını yalnızca bir kez üretir.

    upper_z_map:
        Üst çenenin aşağı bakan en alt yüzeyi -> minimum Z
    lower_z_map:
        Alt çenenin yukarı bakan en üst yüzeyi -> maximum Z
    """
    combined_min = np.minimum(upper_mesh.bounds[0], lower_mesh.bounds[0]).astype(float)
    combined_max = np.maximum(upper_mesh.bounds[1], lower_mesh.bounds[1]).astype(float)

    min_x = combined_min[0] - resolution_mm
    max_x = combined_max[0] + resolution_mm
    min_y = combined_min[1] - resolution_mm
    max_y = combined_max[1] + resolution_mm
    min_z = combined_min[2] - RAY_MARGIN_MM
    max_z = combined_max[2] + RAY_MARGIN_MM

    # Grid düzeni: satırlar Y (sagital), sütunlar X (transversal)
    x_coords = np.arange(min_x, max_x + resolution_mm, resolution_mm, dtype=float)
    y_coords = np.arange(min_y, max_y + resolution_mm, resolution_mm, dtype=float)
    grid_x, grid_y = np.meshgrid(x_coords, y_coords, indexing="xy")
    flat_xy = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    num_rays = flat_xy.shape[0]

    upper_origins = np.column_stack(
        (
            flat_xy[:, 0],
            flat_xy[:, 1],
            np.full(num_rays, max_z, dtype=float),
        )
    )
    upper_dirs = np.tile(np.array([0.0, 0.0, -1.0], dtype=float), (num_rays, 1))
    upper_hit_z, upper_hit_ray_idx = _batched_ray_intersections(upper_mesh, upper_origins, upper_dirs)

    upper_min_hits = np.full(num_rays, np.inf, dtype=float)
    if upper_hit_z.size:
        np.minimum.at(upper_min_hits, upper_hit_ray_idx, upper_hit_z)
    upper_min_hits[np.isinf(upper_min_hits)] = np.nan
    upper_z_map = upper_min_hits.reshape(grid_x.shape)

    lower_origins = np.column_stack(
        (
            flat_xy[:, 0],
            flat_xy[:, 1],
            np.full(num_rays, min_z, dtype=float),
        )
    )
    lower_dirs = np.tile(np.array([0.0, 0.0, 1.0], dtype=float), (num_rays, 1))
    lower_hit_z, lower_hit_ray_idx = _batched_ray_intersections(lower_mesh, lower_origins, lower_dirs)

    lower_max_hits = np.full(num_rays, -np.inf, dtype=float)
    if lower_hit_z.size:
        np.maximum.at(lower_max_hits, lower_hit_ray_idx, lower_hit_z)
    lower_max_hits[np.isneginf(lower_max_hits)] = np.nan
    lower_z_map = lower_max_hits.reshape(grid_x.shape)

    upper_z_map, lower_z_map = apply_crown_only_mask(
        upper_z_map,
        lower_z_map,
        resolution_mm=resolution_mm,
    )

    if upper_z_map.shape != lower_z_map.shape:
        raise RuntimeError(
            f"Z-map shape uyusmazligi: upper={upper_z_map.shape}, lower={lower_z_map.shape}"
        )

    initial_overlap = lower_z_map - upper_z_map
    artefact_pixels = initial_overlap > 2.0
    lower_z_map[artefact_pixels] = np.nan

    clean_overlap = lower_z_map - upper_z_map
    if np.all(np.isnan(clean_overlap)):
        z_offset_calibration = 0.0
    else:
        z_offset_calibration = float(np.nanmax(clean_overlap))

    return HeightMapBundle(
        x_coords=x_coords,
        y_coords=y_coords,
        upper_z_map=upper_z_map,
        lower_z_map=lower_z_map,
        resolution_mm=resolution_mm,
        z_offset_calibration=z_offset_calibration,
    )


def shift_nan_map(height_map: np.ndarray, shift_x_idx: int, shift_y_idx: int) -> np.ndarray:
    """
    NaN güvenli grid kaydırması.

    Grid düzeni:
        axis 0 -> Y (satırlar)
        axis 1 -> X (sütunlar)
    """
    return fast_shift_2d(height_map, shift_y_idx, shift_x_idx)


def solve_occlusion_z(
    bundle: HeightMapBundle,
    delta_x_mm: float,
    delta_y_mm: float,
) -> tuple[float, float]:
    """
    Verilen X/Y kaydırmada gerekli Z düzeltmesini hesaplar.

    Klinik kural:
        - Baseline Z her zaman 0 kabul edilir.
        - overlap = shifted_lower - upper
        - max_overlap > 0 ise penetrasyon vardır -> aşağı indir
        - max_overlap <= 0 ise boşluk vardır -> Z tekrar 0 olur

    Dönüş:
        (z_correction_mm, max_overlap_mm)
    """
    shift_x_idx = int(np.round((delta_x_mm / bundle.resolution_mm) * GRID_X_SIGN))
    shift_y_idx = int(np.round((delta_y_mm / bundle.resolution_mm) * GRID_Y_SIGN))
    shifted_lower = fast_shift_2d(bundle.lower_z_map, shift_y_idx, shift_x_idx)

    valid_mask = np.isfinite(bundle.upper_z_map) & np.isfinite(shifted_lower)
    if not np.any(valid_mask):
        return 0.0, float("nan")

    overlap = shifted_lower[valid_mask] - bundle.upper_z_map[valid_mask]
    max_overlap = float(np.max(overlap))
    z_correction = -max_overlap if max_overlap > 0.0 else 0.0
    return z_correction, max_overlap


class SliderRow(QWidget):
    """Minimalist tek satır slider bileşeni."""

    def __init__(self, title: str, min_value: int, max_value: int, parent: QWidget | None = None) -> None:
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


class HeightMapOcclusionWindow(QMainWindow):
    """2.5D height-map tabanlı dental oklüzyon prototipi."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SelçukBolt | 2.5D Height Map Oklüzyon")
        self.resize(1380, 900)

        self.plotter: QtInteractor | None = None
        self.maxilla_actor = None
        self.mandible_actor = None
        self.maxilla_tri: trimesh.Trimesh | None = None
        self.mandible_tri: trimesh.Trimesh | None = None
        self.maxilla_pv: pv.PolyData | None = None
        self.mandible_pv: pv.PolyData | None = None
        self.height_maps: HeightMapBundle | None = None
        self.mandible_centric_matrix = np.eye(4, dtype=float)

        self.transversal_mm = 0.0
        self.sagittal_mm = 0.0
        self.vertical_correction_mm = 0.0

        arg_maxilla_path, arg_mandible_path = _parse_startup_paths()
        self.maxilla_path = arg_maxilla_path or _resolve_default_file(["ust_cene.stl", "ust_cene.ply"])
        self.mandible_path = arg_mandible_path or _resolve_default_file(["alt_cene.stl", "alt_cene.ply"])

        self._build_ui()
        self._load_startup_meshes()

    def _build_ui(self) -> None:
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

        title = QLabel("2.5D Height Map Oklüzyon Prototipi")
        title.setObjectName("windowTitle")
        subtitle = QLabel(
            "Raycasting yalnızca açılışta çalışır. Slider hareketinde sadece NumPy grid kaydırma ve çıkarma yapılır."
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

        self.transversal_slider = SliderRow(
            "Sağ-Sol Kaydırma (X / Transversal)",
            int(TRANSVERSAL_RANGE_MM[0] * 10),
            int(TRANSVERSAL_RANGE_MM[1] * 10),
        )
        self.sagittal_slider = SliderRow(
            "Ön-Arka Kaydırma (Y / Sagital)",
            int(SAGITTAL_RANGE_MM[0] * 10),
            int(SAGITTAL_RANGE_MM[1] * 10),
        )

        self.transversal_slider.slider.valueChanged.connect(self._on_transversal_changed)
        self.sagittal_slider.slider.valueChanged.connect(self._on_sagittal_changed)

        self.transversal_slider.set_mm_text(0.0)
        self.sagittal_slider.set_mm_text(0.0)

        self.status_label = QLabel("Hazır")
        self.status_label.setObjectName("statusLabel")

        controls_layout.addWidget(self.transversal_slider)
        controls_layout.addWidget(self.sagittal_slider)
        controls_layout.addWidget(self.status_label)
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
            QLabel#statusLabel {
                color: #475569;
                background: #F1F5F9;
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 12px;
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
        try:
            if self.maxilla_path is None:
                self.maxilla_path = self._ask_mesh_file("Üst çene dosyasını seçin")
            if self.mandible_path is None:
                self.mandible_path = self._ask_mesh_file("Alt çene dosyasını seçin")

            if self.maxilla_path is None or self.mandible_path is None:
                raise FileNotFoundError("Her iki çene dosyası seçilmeden prototip başlatılamaz.")

            self.maxilla_tri = load_trimesh_preserve_world(self.maxilla_path)
            self.mandible_tri = load_trimesh_preserve_world(self.mandible_path)
            self.maxilla_pv = trimesh_to_pyvista(self.maxilla_tri)
            self.mandible_pv = trimesh_to_pyvista(self.mandible_tri)
            maxilla_occlusal, mandible_occlusal = rotate_meshes_for_occlusal_heightmap(
                self.maxilla_tri,
                self.mandible_tri,
            )
            self.height_maps = build_height_maps(maxilla_occlusal, mandible_occlusal)
            self._render_scene()
            self._update_mandible_pose()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Mesh / Height Map Hatası", str(exc))
            self.close()

    def _ask_mesh_file(self, title: str) -> Path | None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            title,
            str(Path.cwd()),
            "Mesh Dosyalari (*.stl *.ply)",
        )
        return Path(selected) if selected else None

    def _render_scene(self) -> None:
        if self.plotter is None or self.maxilla_pv is None or self.mandible_pv is None:
            return

        self.plotter.clear()
        self.plotter.set_background("#EEF2F4")
        self.plotter.enable_trackball_style()

        self.maxilla_actor = self.plotter.add_mesh(
            self.maxilla_pv,
            color="#F4E7D5",
            smooth_shading=True,
            ambient=0.34,
            diffuse=0.80,
            specular=0.02,
            specular_power=4,
            name="maxilla",
        )
        self.mandible_actor = self.plotter.add_mesh(
            self.mandible_pv,
            color="#EDE1CE",
            smooth_shading=True,
            ambient=0.34,
            diffuse=0.80,
            specular=0.02,
            specular_power=4,
            name="mandible",
        )
        self.mandible_centric_matrix = np.eye(4, dtype=float)

        self.plotter.add_axes(line_width=1, labels_off=True)
        self.plotter.show_grid(color="#D5DDE5", xtitle="", ytitle="", ztitle="")
        self.plotter.reset_camera()
        self.plotter.render()

    def _update_mandible_pose(self) -> None:
        if self.mandible_actor is None:
            return

        dx_mm = float(self.transversal_mm)
        dy_mm = float(self.sagittal_mm)
        max_overlap_mm = float("nan")

        # Debug izolasyon modu:
        # Temas ve çarpışma hesabını tamamen kapatıp yalnızca saf transformu test et.
        if DEBUG_DISABLE_COLLISION or self.height_maps is None:
            self.vertical_correction_mm = 0.0
        else:
            resolution_mm = float(self.height_maps.resolution_mm)
            # Height-map grid eksenleri (kritik):
            #   rotate_meshes_for_occlusal_heightmap X ekseninde -90° döndürür:
            #     eski-Y → yeni-Z (vertikal),  eski-Z → yeni-Y (sagital)
            #   build_height_maps indexing="xy" ile grid kurar:
            #     axis 0 (satırlar) → döndürülmüş Y = orijinal Z ekseni
            #     axis 1 (sütunlar) → X = transversal (değişmedi)
            #   Sonuç:
            #     dx_mm (transversal, 3Shape X) → axis-1 (cols)
            #     dy_mm (sagital, 3Shape Y) → 3Shape Y, rotasyonla grid-row haline gelir
            #     Dolayısıyla her ikisi de doğru ekse uygulanıyor; np.round ekle.
            shift_col_transversal = int(np.round(dx_mm / resolution_mm))
            shift_row_sagittal    = int(np.round(dy_mm / resolution_mm))

            shifted_lower_z = fast_shift_2d(
                self.height_maps.lower_z_map,
                shift_row_sagittal,
                shift_col_transversal,
            )
            valid_mask = np.isfinite(self.height_maps.upper_z_map) & np.isfinite(shifted_lower_z)

            if np.any(valid_mask):
                overlap = shifted_lower_z[valid_mask] - self.height_maps.upper_z_map[valid_mask]
                max_overlap_mm = float(np.nanmax(overlap))
            else:
                max_overlap_mm = 0.0

            dynamic_penetration = max_overlap_mm - float(self.height_maps.z_offset_calibration)
            self.vertical_correction_mm = (
                -dynamic_penetration if np.isfinite(dynamic_penetration) and dynamic_penetration > 0.0 else 0.0
            )

        # Saf, mutlak transform: sentrik referans her zaman (0,0,0)
        matrix = np.eye(4, dtype=float)
        matrix[0, 3] = dx_mm
        matrix[1, 3] = self.vertical_correction_mm
        matrix[2, 3] = dy_mm
        self.mandible_actor.SetUserMatrix(_numpy_to_vtk_matrix(matrix))

        if DEBUG_DISABLE_COLLISION:
            status_text = (
                f"DEBUG | X: {self.transversal_mm:+.2f} mm | "
                f"Y: {self.sagittal_mm:+.2f} mm | "
                "Temas kapali | Z: +0.000 mm"
            )
        elif np.isnan(max_overlap_mm):
            status_text = (
                f"X: {self.transversal_mm:+.2f} mm | "
                f"Y: {self.sagittal_mm:+.2f} mm | "
                f"Z: {self.vertical_correction_mm:+.3f} mm | "
                "Geçerli temas bölgesi yok"
            )
        else:
            status_text = (
                f"X: {self.transversal_mm:+.2f} mm | "
                f"Y: {self.sagittal_mm:+.2f} mm | "
                f"Penetration: {max_overlap_mm:+.3f} mm | "
                f"Dara: {self.height_maps.z_offset_calibration:+.3f} mm | "
                f"Z telafi: {self.vertical_correction_mm:+.3f} mm"
            )
        self.status_label.setText(status_text)

        if self.plotter is not None:
            self.plotter.render()

    def _on_transversal_changed(self, raw_value: int) -> None:
        self.transversal_mm = raw_value / 10.0
        self.transversal_slider.set_mm_text(self.transversal_mm)
        self._update_mandible_pose()

    def _on_sagittal_changed(self, raw_value: int) -> None:
        self.sagittal_mm = raw_value / 10.0
        self.sagittal_slider.set_mm_text(self.sagittal_mm)
        self._update_mandible_pose()


def main() -> int:
    app = QApplication(sys.argv)
    window = HeightMapOcclusionWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    activate_macos_app()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
