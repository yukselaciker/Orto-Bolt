"""
ai/preprocessor.py — STL → Point Cloud Ön İşleme
===================================================
Faz 3: STL mesh'i AI modeli için uygun formata dönüştürür.

Tasarım Kararı:
    CrossTooth modeli N×6 boyutunda nokta bulutu bekler:
    [x, y, z, nx, ny, nz] — koordinat + yüzey normali.

    Klinik mesh'ler genellikle 200K–500K yüzey içerir.
    Model performansı için ~16K–32K noktaya alt-örnekleme yapılır.
    PyVista'nın decimate + sample filtrelerini kullanıyoruz.
"""

from typing import Tuple, Optional
import numpy as np
import pyvista as pv


# ──────────────────────────────────────────────────
# SABİTLER
# ──────────────────────────────────────────────────

DEFAULT_N_POINTS = 24000  # Alt-örnekleme hedefi
MIN_POINTS = 1000          # Minimum kabul edilebilir nokta sayısı


def prepare_point_cloud(
    mesh: pv.PolyData,
    n_points: int = DEFAULT_N_POINTS,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    PyVista mesh'i AI modeli için nokta bulutuna dönüştürür.

    İş Akışı:
        1. Mesh yüzeyinden noktaları çıkar
        2. Yüzey normallerini hesapla
        3. Hedef sayıya alt-örnekle
        4. Koordinatları normalize et

    Args:
        mesh: PyVista PolyData nesnesi (STL'den yüklenen).
        n_points: Hedef nokta sayısı.

    Returns:
        Tuple[points, normals]:
            - points: (N, 3) normalize edilmiş koordinatlar
            - normals: (N, 3) birim yüzey normalleri

    Raises:
        ValueError: Mesh geçersiz veya çok küçükse.
    """
    if mesh is None or mesh.n_points == 0:
        raise ValueError("Geçersiz mesh: boş veya None")

    # ── Normalleri hesapla ──
    mesh = mesh.compute_normals(
        cell_normals=False,
        point_normals=True,
        auto_orient_normals=True,
        inplace=False,
    )

    # ── Alt-örnekleme ──
    if mesh.n_points > n_points:
        # Uniform alt-örnekleme — rastgele indeksler
        indices = np.random.choice(
            mesh.n_points, size=n_points, replace=False
        )
        points = np.asarray(mesh.points[indices], dtype=np.float64)
        normals = np.asarray(mesh.point_normals[indices], dtype=np.float64)
    else:
        points = np.asarray(mesh.points, dtype=np.float64)
        normals = np.asarray(mesh.point_normals, dtype=np.float64)

    if len(points) < MIN_POINTS:
        raise ValueError(
            f"Mesh çok küçük: {len(points)} nokta "
            f"(minimum {MIN_POINTS} gerekli)"
        )

    return points, normals


def normalize_coords(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Nokta bulutunu merkeze al ve birim küreye ölçekle.

    Klinik Not:
        Normalizasyon modelin farklı boyutlardaki çene modellerinde
        tutarlı çalışmasını sağlar. Orijinal ölçek bilgisi korunur
        çünkü ölçüm değerlerini mm cinsine geri dönüştürmemiz gerekir.

    Args:
        points: (N, 3) ham koordinatlar.

    Returns:
        Tuple[normalized, centroid, scale]:
            - normalized: (N, 3) normalize edilmiş koordinatlar
            - centroid: (3,) orijinal merkez noktası
            - scale: float, ölçekleme faktörü (mm'ye geri dönüşüm için)
    """
    centroid = points.mean(axis=0)
    centered = points - centroid

    # Maksimum mesafe = ölçek faktörü
    scale = np.max(np.linalg.norm(centered, axis=1))
    if scale < 1e-8:
        scale = 1.0  # Dejenere durum koruması

    normalized = centered / scale

    return normalized, centroid, scale


def denormalize_coords(
    normalized: np.ndarray,
    centroid: np.ndarray,
    scale: float
) -> np.ndarray:
    """
    Normalize edilmiş koordinatları orijinal mm uzayına geri dönüştürür.

    Args:
        normalized: (N, 3) normalize koordinatlar.
        centroid: (3,) orijinal merkez.
        scale: float, ölçekleme faktörü.

    Returns:
        (N, 3) orijinal mm koordinatları.
    """
    return normalized * scale + centroid


def mesh_to_feature_tensor(
    mesh: pv.PolyData,
    n_points: int = DEFAULT_N_POINTS,
) -> Tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """
    Tam ön işleme boru hattı: STL mesh → model girdi tensörü.

    Args:
        mesh: PyVista PolyData.
        n_points: Hedef nokta sayısı.

    Returns:
        Tuple[features, centroid, scale, raw_points]:
            - features: (N, 6) [x,y,z,nx,ny,nz] normalize edilmiş
            - centroid: (3,) orijinal merkez
            - scale: float, mm geri dönüşüm faktörü
            - raw_points: (N, 3) normalize ÖNCESİ koordinatlar (ölçüm için)
    """
    points, normals = prepare_point_cloud(mesh, n_points)

    # Ham noktaları sakla (mm cinsinde ölçüm için gerekli)
    raw_points = points.copy()

    # Normalize et
    norm_points, centroid, scale = normalize_coords(points)

    # Normalleri de normalize et (birim vektör olmalı)
    norms_magnitude = np.linalg.norm(normals, axis=1, keepdims=True)
    norms_magnitude = np.where(norms_magnitude < 1e-8, 1.0, norms_magnitude)
    normals = normals / norms_magnitude

    # Birleştir: [x, y, z, nx, ny, nz]
    features = np.hstack([norm_points, normals]).astype(np.float32)

    return features, centroid, scale, raw_points
