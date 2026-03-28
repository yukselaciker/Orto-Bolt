from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from datetime import datetime
import math
import os
import uuid

from fastapi import UploadFile
import numpy as np
import pandas as pd
import pyvista as pv
import trimesh
from scipy.ndimage import binary_erosion, binary_fill_holes

from core.bolton_logic import (
    BOLTON_REF,
    MAXILLARY_ANTERIOR,
    MAXILLARY_OVERALL,
    MANDIBULAR_ANTERIOR,
    MANDIBULAR_OVERALL,
    TOOTH_NAMES,
    BoltonResult,
    analyze_anterior,
    analyze_overall,
)
from core.stl_loader import STLLoadError, STLLoader
from reports.pdf_generator import generate_bolton_report
from reports.excel_template_export import export_bolton_excel_template


_OCCLUSION_SESSIONS: dict[str, dict[str, object]] = {}
GRID_RESOLUTION_MM = 0.1
GRID_X_SIGN = +1
GRID_Y_SIGN = +1
CROWN_HEIGHT_LIMIT_MM = 15.0


def _sample_mesh_vertices(mesh: trimesh.Trimesh, max_points: int = 1400) -> np.ndarray:
    """Hizli proximity kontrolu icin mesh vertexlerini seyrelterek örnekler."""
    vertices = np.asarray(mesh.vertices, dtype=float)
    if len(vertices) <= max_points:
        return vertices.copy()
    step = max(1, len(vertices) // max_points)
    return vertices[::step].copy()


def _build_collision_proxy(mesh: trimesh.Trimesh, reduction: float = 0.9) -> trimesh.Trimesh:
    """
    Görsel mesh'i bozmadan yalnızca collision hesabı için düşük poligonlu bir kopya üretir.
    Öncelik PyVista decimate_pro; başarısız olursa orijinal mesh'e düşer.
    """
    try:
        faces = np.hstack(
            [
                np.full((len(mesh.faces), 1), 3, dtype=np.int64),
                np.asarray(mesh.faces, dtype=np.int64),
            ]
        )
        pv_mesh = pv.PolyData(np.asarray(mesh.vertices, dtype=float), faces.ravel())
        decimated = pv_mesh.decimate_pro(target_reduction=float(reduction), preserve_topology=True)
        if decimated.n_points < 4 or decimated.n_cells < 2:
            return mesh
        decimated_faces = decimated.faces.reshape(-1, 4)[:, 1:4]
        proxy = trimesh.Trimesh(
            vertices=np.asarray(decimated.points, dtype=float),
            faces=np.asarray(decimated_faces, dtype=np.int64),
            process=False,
            maintain_order=True,
        )
        if proxy.vertices.size == 0 or proxy.faces.size == 0:
            return mesh
        return proxy
    except Exception:
        return mesh


def _batched_ray_intersections(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    directions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Tek seferde çok sayıda ray göndererek Z-map üretimine yardımcı olur."""
    locations, ray_indices, _ = mesh.ray.intersects_location(
        ray_origins=origins,
        ray_directions=directions,
        multiple_hits=True,
    )
    if locations.size == 0:
        return np.empty((0,), dtype=float), np.empty((0,), dtype=np.int64)
    return locations[:, 2].astype(float), ray_indices.astype(np.int64)


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


def _apply_crown_only_mask(
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


def _build_height_maps(
    maxilla_mesh: trimesh.Trimesh,
    mandible_mesh: trimesh.Trimesh,
    resolution_mm: float = GRID_RESOLUTION_MM,
) -> dict[str, object]:
    """
    Proxy mesh'lerden 2.5D yükseklik haritaları üretir.

    upper_z_map = üst çenenin alttan görülen en düşük Z yüzeyi
    lower_z_map = alt çenenin üstten görülen en yüksek Z yüzeyi
    """
    ray_margin_mm = 4.0
    combined_min = np.minimum(maxilla_mesh.bounds[0], mandible_mesh.bounds[0]).astype(float)
    combined_max = np.maximum(maxilla_mesh.bounds[1], mandible_mesh.bounds[1]).astype(float)
    min_x = combined_min[0] - resolution_mm
    max_x = combined_max[0] + resolution_mm
    min_y = combined_min[1] - resolution_mm
    max_y = combined_max[1] + resolution_mm
    min_z = combined_min[2] - ray_margin_mm
    max_z = combined_max[2] + ray_margin_mm

    # Grid[rows, cols] => [Y, X]
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
    upper_hit_z, upper_hit_idx = _batched_ray_intersections(maxilla_mesh, upper_origins, upper_dirs)
    upper_min_hits = np.full(num_rays, np.inf, dtype=float)
    if upper_hit_z.size:
        np.minimum.at(upper_min_hits, upper_hit_idx, upper_hit_z)
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
    lower_hit_z, lower_hit_idx = _batched_ray_intersections(mandible_mesh, lower_origins, lower_dirs)
    lower_max_hits = np.full(num_rays, -np.inf, dtype=float)
    if lower_hit_z.size:
        np.maximum.at(lower_max_hits, lower_hit_idx, lower_hit_z)
    lower_max_hits[np.isneginf(lower_max_hits)] = np.nan
    lower_z_map = lower_max_hits.reshape(grid_x.shape)

    upper_z_map, lower_z_map = _apply_crown_only_mask(
        upper_z_map,
        lower_z_map,
        resolution_mm=resolution_mm,
    )

    if upper_z_map.shape != lower_z_map.shape:
        raise ValueError(
            f"Height-map shape uyusmazligi: upper={upper_z_map.shape}, lower={lower_z_map.shape}"
        )

    initial_overlap = lower_z_map - upper_z_map
    if np.all(np.isnan(initial_overlap)):
        z_offset_calibration = 0.0
    else:
        z_offset_calibration = float(np.nanmax(initial_overlap))

    return {
        "x_coords": x_coords,
        "y_coords": y_coords,
        "upper_z_map": upper_z_map,
        "lower_z_map": lower_z_map,
        "resolution_mm": float(resolution_mm),
        "z_offset_calibration": z_offset_calibration,
    }


def _shift_nan_map(height_map: np.ndarray, shift_x_idx: int, shift_y_idx: int) -> np.ndarray:
    """
    Wrap-around yapmadan NaN güvenli grid kaydırma.

    Grid düzeni:
        axis 0 -> Y (satırlar)
        axis 1 -> X (sütunlar)
    """
    return fast_shift_2d(height_map, shift_y_idx, shift_x_idx)


def _solve_height_map_occlusion(
    *,
    upper_z_map: np.ndarray,
    lower_z_map: np.ndarray,
    resolution_mm: float,
    delta_x_mm: float,
    delta_y_mm: float,
    z_offset_calibration: float = 0.0,
) -> tuple[float, float]:
    """
    Height-map yaklaşımı ile gerekli Z düzeltmeyi hesaplar.

    Klinik kural:
        - Baseline Z her zaman 0'dır.
        - Penetrasyon varsa alt çene yalnızca aşağı iner.
        - Boşluk varsa alt çene yukarı kaldırılmaz; Z tekrar 0 olur.
    """
    # axis 1 (cols) -> X, axis 0 (rows) -> Y
    shift_col_x = int(delta_x_mm / resolution_mm)
    shift_row_y = int(delta_y_mm / resolution_mm)
    shifted_lower = fast_shift_2d(lower_z_map, shift_row_y, shift_col_x)
    valid_mask = np.isfinite(upper_z_map) & np.isfinite(shifted_lower)
    if not np.any(valid_mask):
        return 0.0, 0.0

    overlap = shifted_lower[valid_mask] - upper_z_map[valid_mask]
    if np.all(np.isnan(overlap)):
        max_overlap = 0.0
    else:
        max_overlap = float(np.nanmax(overlap))
    dynamic_penetration = max_overlap - float(z_offset_calibration)
    z_correction = -dynamic_penetration if dynamic_penetration > 0.0 else 0.0
    return z_correction, max_overlap


def normalize_measurements(measurements: dict[int, float]) -> dict[int, float]:
    normalized: dict[int, float] = {}
    for tooth_fdi, width in measurements.items():
        try:
            fdi = int(tooth_fdi)
            width_mm = float(width)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Gecersiz olcum girdisi: {tooth_fdi} -> {width}") from exc

        if width_mm <= 0:
            raise ValueError(f"Dis {fdi} icin genislik sifirdan buyuk olmali.")

        normalized[fdi] = round(width_mm, 4)
    return normalized


def serialize_result(result: BoltonResult) -> dict:
    return asdict(result)


def analyze_anterior_measurements(measurements: dict[int, float]) -> dict:
    return serialize_result(analyze_anterior(normalize_measurements(measurements)))


def analyze_overall_measurements(measurements: dict[int, float]) -> dict:
    return serialize_result(analyze_overall(normalize_measurements(measurements)))


def analyze_combined_measurements(measurements: dict[int, float]) -> dict:
    normalized = normalize_measurements(measurements)
    return {
        "anterior": serialize_result(analyze_anterior(normalized)),
        "overall": serialize_result(analyze_overall(normalized)),
    }


def analyze_available_measurements(measurements: dict[int, float]) -> dict:
    normalized = normalize_measurements(measurements)
    payload: dict[str, dict] = {}
    try:
        payload["anterior"] = serialize_result(analyze_anterior(normalized))
    except ValueError:
        pass
    try:
        payload["overall"] = serialize_result(analyze_overall(normalized))
    except ValueError:
        pass
    return payload


def build_metadata() -> dict:
    return {
        "app_name": "SelcukBolt API",
        "modes": {
            "anterior": {
                "maxillary_teeth": list(MAXILLARY_ANTERIOR),
                "mandibular_teeth": list(MANDIBULAR_ANTERIOR),
            },
            "overall": {
                "maxillary_teeth": list(MAXILLARY_OVERALL),
                "mandibular_teeth": list(MANDIBULAR_OVERALL),
            },
        },
        "tooth_names": TOOTH_NAMES,
        "references": {
            "anterior_mean": BOLTON_REF.ANTERIOR_MEAN,
            "anterior_sd": BOLTON_REF.ANTERIOR_SD,
            "overall_mean": BOLTON_REF.OVERALL_MEAN,
            "overall_sd": BOLTON_REF.OVERALL_SD,
        },
    }


def measurements_to_dataframe(measurements: dict[int, float]) -> pd.DataFrame:
    normalized = normalize_measurements(measurements)
    rows: list[dict] = []
    for tooth_fdi, width_mm in sorted(normalized.items()):
        rows.append(
            {
                "tooth_fdi": tooth_fdi,
                "jaw": "maxillary" if tooth_fdi < 30 else "mandibular",
                "width_mm": round(width_mm, 2),
            }
        )
    return pd.DataFrame(rows)


def build_export_payload(
    *,
    measurements: dict[int, float],
    patient_id: str,
    report_date: str,
    maxilla_filename: str,
    mandible_filename: str,
    treatment_notes: str,
) -> dict:
    normalized = normalize_measurements(measurements)
    df = measurements_to_dataframe(normalized)
    return {
        "measurements": normalized,
        "dataframe": df,
        "patient_id": patient_id or "Bilinmeyen Hasta",
        "report_date": report_date or datetime.now().strftime("%d.%m.%Y"),
        "maxilla_filename": maxilla_filename or "maxilla.stl",
        "mandible_filename": mandible_filename or "mandibula.stl",
        "treatment_notes": treatment_notes or "",
        "analysis": analyze_available_measurements(normalized),
    }


async def inspect_uploaded_mesh(upload: UploadFile) -> dict:
    suffix = Path(upload.filename or "scan.stl").suffix or ".stl"
    try:
        with NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
            payload = await upload.read()
            tmp.write(payload)
            tmp.flush()
            mesh = STLLoader.load(tmp.name)
            info = STLLoader.get_mesh_info(mesh)
    except STLLoadError:
        raise
    except Exception as exc:
        raise STLLoadError(f"STL dosyasi islenemedi: {exc}") from exc

    center = info["merkez"]
    return {
        "file_name": upload.filename or "scan.stl",
        "point_count": int(info["nokta_sayisi"]),
        "face_count": int(info["yuzey_sayisi"]),
        "width_mm": round(float(info["genislik_mm"]), 2),
        "height_mm": round(float(info["yukseklik_mm"]), 2),
        "depth_mm": round(float(info["derinlik_mm"]), 2),
        "center": [round(float(value), 4) for value in center],
    }


def render_pdf_report(
    *,
    output_path: str,
    measurements: dict[int, float],
    patient_id: str,
    report_date: str,
    maxilla_filename: str,
    mandible_filename: str,
    treatment_notes: str,
) -> str:
    payload = build_export_payload(
        measurements=measurements,
        patient_id=patient_id,
        report_date=report_date,
        maxilla_filename=maxilla_filename,
        mandible_filename=mandible_filename,
        treatment_notes=treatment_notes,
    )
    return generate_bolton_report(
        output_path=output_path,
        patient_id=payload["patient_id"],
        report_date=payload["report_date"],
        maxilla_filename=payload["maxilla_filename"],
        mandible_filename=payload["mandible_filename"],
        measurements_df=payload["dataframe"],
        treatment_notes=payload["treatment_notes"],
    )


def resolve_excel_template_path(explicit_path: str = "") -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())

    env_path = os.environ.get("SELCUKBOLT_EXCEL_TEMPLATE_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.extend(
        [
            Path.home() / "Downloads" / "BOŞ BOLTON.xlsx",
            Path.home() / "Downloads" / "BOS BOLTON.xlsx",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Excel sablonu bulunamadi. SELCUKBOLT_EXCEL_TEMPLATE_PATH ayarlayin veya BOS BOLTON.xlsx dosyasini Downloads klasorune koyun."
    )


def render_excel_report(
    *,
    output_path: str,
    measurements: dict[int, float],
    patient_id: str,
    report_date: str,
    treatment_notes: str,
    template_path: str = "",
) -> str:
    payload = build_export_payload(
        measurements=measurements,
        patient_id=patient_id,
        report_date=report_date,
        maxilla_filename="",
        mandible_filename="",
        treatment_notes=treatment_notes,
    )

    return export_bolton_excel_template(
        template_path=resolve_excel_template_path(template_path),
        output_path=output_path,
        measurements_df=payload["dataframe"],
        patient_name=payload["patient_id"],
        report_date=payload["report_date"],
        doctor_name="SelcukBolt Web",
        notes=payload["treatment_notes"],
    )


def _load_trimesh_from_bytes(file_name: str, payload: bytes) -> trimesh.Trimesh:
    """Upload edilen STL/PLY dosyasını world-space korunarak trimesh'e çevirir."""
    file_type = Path(file_name or "scan.stl").suffix.lstrip(".") or "stl"
    loaded = trimesh.load(
        file_obj=BytesIO(payload),
        file_type=file_type,
        process=False,
        maintain_order=True,
        force="mesh",
    )

    if isinstance(loaded, trimesh.Scene):
        geometries: list[trimesh.Trimesh] = []
        for node_name in loaded.graph.nodes_geometry:
            transform, geometry_name = loaded.graph[node_name]
            geometry = loaded.geometry[geometry_name].copy()
            geometry.apply_transform(transform)
            geometries.append(geometry)
        if not geometries:
            raise STLLoadError("Scene icinde gecerli geometri bulunamadi.")
        loaded = trimesh.util.concatenate(geometries)

    if not isinstance(loaded, trimesh.Trimesh):
        raise STLLoadError("Dosya gecerli bir STL/PLY mesh olarak okunamadi.")
    if loaded.vertices.size == 0 or loaded.faces.size == 0:
        raise STLLoadError("Mesh bos veya gecersiz.")

    return loaded


def _collision_metrics(
    maxilla_mesh: trimesh.Trimesh,
    mandible_mesh: trimesh.Trimesh,
    tx: float,
    ty: float,
    tz: float,
) -> tuple[bool, float, str]:
    """
    Mandibulaya verilen X/Y ötelemesi sonrası temas/çarpışma olup olmadığını kontrol eder.

    Öncelik:
        1. trimesh.collision (python-fcl mevcutsa)
        2. signed-distance fallback
        3. AABB fallback
    """
    moved = mandible_mesh.copy()
    transform = np.eye(4, dtype=float)
    transform[0, 3] = tx
    transform[1, 3] = ty
    transform[2, 3] = tz
    moved.apply_transform(transform)

    contact_threshold_mm = 0.08
    broadphase_threshold_mm = 1.5
    proximity_threshold_mm = 0.35

    max_bounds = maxilla_mesh.bounds
    man_bounds = moved.bounds

    gap_x = max(0.0, max(max_bounds[0][0] - man_bounds[1][0], man_bounds[0][0] - max_bounds[1][0]))
    gap_y = max(0.0, max(max_bounds[0][1] - man_bounds[1][1], man_bounds[0][1] - max_bounds[1][1]))
    gap_z = max(0.0, max(max_bounds[0][2] - man_bounds[1][2], man_bounds[0][2] - max_bounds[1][2]))
    aabb_gap = float(math.sqrt(gap_x * gap_x + gap_y * gap_y + gap_z * gap_z))

    # Mesh'ler birbirinden belirgin şekilde uzaksa pahali collision adimina hiç girme.
    if aabb_gap > broadphase_threshold_mm:
        return False, aabb_gap, "broadphase_aabb"

    # Orta mesafede önce düşük maliyetli signed-distance örneklemesi yap.
    if aabb_gap > proximity_threshold_mm:
        try:
            sample = moved.vertices
            if len(sample) > 1200:
                step = max(1, len(sample) // 1200)
                sample = sample[::step]
            distances = trimesh.proximity.signed_distance(maxilla_mesh, sample)
            penetration = float(max(0.0, float(np.max(distances)) + 0.02))
            if penetration <= 0.0:
                return False, aabb_gap, "broadphase_signed_distance"
        except Exception:
            pass

    manager_collided: bool | None = None
    manager_distance: float | None = None
    try:
        manager = trimesh.collision.CollisionManager()
        manager.add_object("maxilla", maxilla_mesh)
        manager_collided = bool(manager.in_collision_single(moved))
        try:
            manager_distance = float(manager.min_distance_single(moved))
        except Exception:
            manager_distance = None
    except Exception:
        manager_collided = None
        manager_distance = None

    try:
        sample = moved.vertices
        if len(sample) > 1800:
            step = max(1, len(sample) // 1800)
            sample = sample[::step]
        distances = trimesh.proximity.signed_distance(maxilla_mesh, sample)
        penetration = float(max(0.0, float(np.max(distances)) + 0.02))
        distance_collided = penetration > 0.0
        proximity_collided = manager_distance is not None and manager_distance <= contact_threshold_mm
        effective_metric = penetration if penetration > 0.0 else (
            manager_distance if manager_distance is not None else float("inf")
        )
        if manager_collided is None:
            return distance_collided, effective_metric, "signed_distance_fallback"
        return manager_collided or distance_collided or proximity_collided, effective_metric, "trimesh.collision+distance"
    except Exception:
        collided = not (
            man_bounds[1][0] < max_bounds[0][0]
            or man_bounds[0][0] > max_bounds[1][0]
            or man_bounds[1][1] < max_bounds[0][1]
            or man_bounds[0][1] > max_bounds[1][1]
            or man_bounds[1][2] < max_bounds[0][2]
            or man_bounds[0][2] > max_bounds[1][2]
        )
        if manager_collided is None:
            return collided, 0.0 if collided else float("inf"), "aabb_fallback"
        if manager_distance is not None:
            return (
                manager_collided or collided or manager_distance <= contact_threshold_mm,
                manager_distance,
                "trimesh.collision+aabb",
            )
        return manager_collided or collided, 0.0 if (manager_collided or collided) else float("inf"), "trimesh.collision+aabb"


def _adaptive_step_mm(distance_mm: float) -> float:
    """
    Uzak hedeflerde daha iri, temasa yakın bölgede daha ince adım kullan.
    Bu sayede kullanıcı büyük kaydırmalarda beklemez, temas civarında ise hassasiyet korunur.
    """
    if distance_mm >= 6.0:
        return 0.6
    if distance_mm >= 3.0:
        return 0.35
    if distance_mm >= 1.25:
        return 0.2
    if distance_mm >= 0.5:
        return 0.1
    return 0.05


def create_occlusion_session(
    *,
    maxilla_filename: str,
    maxilla_payload: bytes,
    mandible_filename: str,
    mandible_payload: bytes,
) -> dict:
    """
    Mesh'leri world-space korunarak bir kez belleğe alır ve tekrar kullanılabilir
    bir session_id döndürür. Böylece her slider hareketinde STL yeniden parse edilmez.
    """
    maxilla_mesh = _load_trimesh_from_bytes(maxilla_filename, maxilla_payload)
    mandible_mesh = _load_trimesh_from_bytes(mandible_filename, mandible_payload)
    maxilla_proxy = _build_collision_proxy(maxilla_mesh, reduction=0.9)
    mandible_proxy = _build_collision_proxy(mandible_mesh, reduction=0.9)
    height_maps = _build_height_maps(maxilla_proxy, mandible_proxy, resolution_mm=GRID_RESOLUTION_MM)
    z_zero, overlap_zero = _solve_height_map_occlusion(
        upper_z_map=height_maps["upper_z_map"],
        lower_z_map=height_maps["lower_z_map"],
        resolution_mm=float(height_maps["resolution_mm"]),
        delta_x_mm=0.0,
        delta_y_mm=0.0,
        z_offset_calibration=float(height_maps.get("z_offset_calibration", 0.0)),
    )
    backend_name = "height_map"
    session_id = uuid.uuid4().hex
    _OCCLUSION_SESSIONS[session_id] = {
        "maxilla_mesh": maxilla_mesh,
        "mandible_mesh": mandible_mesh,
        "maxilla_proxy": maxilla_proxy,
        "mandible_proxy": mandible_proxy,
        "height_maps": height_maps,
        "initial_z_correction": z_zero,
        "initial_overlap": overlap_zero,
        "collision_backend": backend_name,
    }
    return {
        "session_id": session_id,
        "collision_backend": backend_name,
    }


def _resolve_occlusion_shift_with_meshes(
    *,
    maxilla_mesh: trimesh.Trimesh,
    mandible_mesh: trimesh.Trimesh,
    current_x: float,
    current_y: float,
    current_z: float,
    target_x: float,
    target_y: float,
    target_z: float,
    step_mm: float = 0.1,
) -> dict:
    """
    Alt çeneyi mevcut güvenli konumdan hedef konuma doğru 0.1 mm adımlarla ilerletir.
    İlk çarpışmada durur ve son güvenli X/Y değeri döndürülür.
    """
    if step_mm <= 0:
        raise ValueError("step_mm sifirdan buyuk olmali.")

    dx = float(target_x) - float(current_x)
    dy = float(target_y) - float(current_y)
    dz = float(target_z) - float(current_z)
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    effective_step_mm = max(step_mm, _adaptive_step_mm(distance))

    if distance < 1e-9:
        collided, penetration, backend_name = _collision_metrics(maxilla_mesh, mandible_mesh, current_x, current_y, current_z)
        return {
            "applied_x": round(float(current_x), 4),
            "applied_y": round(float(current_y), 4),
            "applied_z": round(float(current_z), 4),
            "collided": collided,
            "collision_backend": backend_name,
        }

    steps = max(1, int(math.ceil(distance / effective_step_mm)))
    safe_x = float(current_x)
    safe_y = float(current_y)
    safe_z = float(current_z)
    current_collided, current_penetration, backend_name = _collision_metrics(
        maxilla_mesh, mandible_mesh, current_x, current_y, current_z
    )
    safe_collided = current_collided
    safe_penetration = current_penetration
    found_non_colliding = not current_collided
    backend_name = "unknown"

    for index in range(1, steps + 1):
        ratio = index / steps
        candidate_x = float(current_x) + dx * ratio
        candidate_y = float(current_y) + dy * ratio
        candidate_z = float(current_z) + dz * ratio
        has_hit, penetration, backend_name = _collision_metrics(
            maxilla_mesh, mandible_mesh, candidate_x, candidate_y, candidate_z
        )

        if not has_hit:
            safe_x = candidate_x
            safe_y = candidate_y
            safe_z = candidate_z
            safe_collided = False
            safe_penetration = 0.0
            found_non_colliding = True
            continue

        if found_non_colliding:
            break

        if penetration <= safe_penetration + 1e-6:
            safe_x = candidate_x
            safe_y = candidate_y
            safe_z = candidate_z
            safe_collided = True
            safe_penetration = penetration

    return {
        "applied_x": round(safe_x, 4),
        "applied_y": round(safe_y, 4),
        "applied_z": round(safe_z, 4),
        "collided": safe_collided,
        "collision_backend": backend_name,
    }


def _resolve_occlusion_shift_with_session(
    *,
    session: dict[str, object],
    current_x: float,
    current_y: float,
    current_z: float,
    target_x: float,
    target_y: float,
    target_z: float,
    step_mm: float = 0.1,
) -> dict:
    height_maps = session.get("height_maps")
    if not isinstance(height_maps, dict):
        raise ValueError("Height-map oturumu gecersiz.")

    upper_z_map = height_maps.get("upper_z_map")
    lower_z_map = height_maps.get("lower_z_map")
    resolution_mm = float(height_maps.get("resolution_mm", GRID_RESOLUTION_MM))
    z_offset_calibration = float(height_maps.get("z_offset_calibration", 0.0))
    if not isinstance(upper_z_map, np.ndarray) or not isinstance(lower_z_map, np.ndarray):
        raise ValueError("Height-map verisi bulunamadi.")

    solved_z, max_overlap = _solve_height_map_occlusion(
        upper_z_map=upper_z_map,
        lower_z_map=lower_z_map,
        resolution_mm=resolution_mm,
        delta_x_mm=float(target_x),
        delta_y_mm=float(target_y),
        z_offset_calibration=z_offset_calibration,
    )

    return {
        "applied_x": round(float(target_x), 4),
        "applied_y": round(float(target_y), 4),
        "applied_z": round(float(solved_z), 4),
        "collided": bool(np.isfinite(max_overlap) and (max_overlap - z_offset_calibration) > 0.0),
        "collision_backend": "height_map",
    }


def resolve_occlusion_shift(
    *,
    maxilla_filename: str,
    maxilla_payload: bytes,
    mandible_filename: str,
    mandible_payload: bytes,
    current_x: float,
    current_y: float,
    current_z: float,
    target_x: float,
    target_y: float,
    target_z: float,
    step_mm: float = 0.1,
) -> dict:
    maxilla_mesh = _load_trimesh_from_bytes(maxilla_filename, maxilla_payload)
    mandible_mesh = _load_trimesh_from_bytes(mandible_filename, mandible_payload)
    maxilla_proxy = _build_collision_proxy(maxilla_mesh, reduction=0.9)
    mandible_proxy = _build_collision_proxy(mandible_mesh, reduction=0.9)
    return _resolve_occlusion_shift_with_meshes(
        maxilla_mesh=maxilla_proxy,
        mandible_mesh=mandible_proxy,
        current_x=current_x,
        current_y=current_y,
        current_z=current_z,
        target_x=target_x,
        target_y=target_y,
        target_z=target_z,
        step_mm=step_mm,
    )


def resolve_occlusion_shift_for_session(
    *,
    session_id: str,
    current_x: float,
    current_y: float,
    current_z: float,
    target_x: float,
    target_y: float,
    target_z: float,
    step_mm: float = 0.1,
) -> dict:
    session = _OCCLUSION_SESSIONS.get(session_id)
    if session is None:
        raise ValueError("Kapanis mesh oturumu bulunamadi. STL dosyalarini yeniden yukleyin.")

    maxilla_mesh = session.get("maxilla_mesh")
    mandible_mesh = session.get("mandible_mesh")
    if not isinstance(maxilla_mesh, trimesh.Trimesh) or not isinstance(mandible_mesh, trimesh.Trimesh):
        raise ValueError("Kapanis mesh oturumu gecersiz.")
    return _resolve_occlusion_shift_with_session(
        session=session,
        current_x=current_x,
        current_y=current_y,
        current_z=current_z,
        target_x=target_x,
        target_y=target_y,
        target_z=target_z,
        step_mm=step_mm,
    )
