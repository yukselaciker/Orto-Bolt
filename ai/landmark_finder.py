"""
ai/landmark_finder.py — Otomatik Landmark Tespiti
===================================================
Faz 3: Segmente edilmiş diş noktalarından mezial/distal
landmark noktalarını ve meziodisal genişliği hesaplar.

Tasarım Kararı:
    PCA (Principal Component Analysis) kullanarak her dişin
    ana eksenini buluyoruz. Bu eksen meziodisal yönle hizalanır.
    Eksen üzerindeki en uç iki nokta = mezial ve distal landmark.

    Klinik Doğrulama:
        Hesaplanan genişlikler 2–15 mm aralığında olmalıdır.
        Bu aralık dışındaki değerler segmentasyon hatasına işaret eder.
"""

from typing import Dict, Tuple, Optional, List, NamedTuple
import numpy as np

from core.measurements import validate_measurement
from core.bolton_logic import TOOTH_NAMES


class ToothLandmark(NamedTuple):
    """Bir dişin landmark bilgisi."""
    fdi: int                    # FDI diş numarası
    mesial: np.ndarray         # Mezial temas noktası (x, y, z)
    distal: np.ndarray         # Distal temas noktası (x, y, z)
    width_mm: float            # Meziodisal genişlik (mm)
    centroid: np.ndarray       # Diş merkez noktası
    principal_axis: np.ndarray # Ana eksen (meziodisal yön)
    n_points: int              # Bu dişe ait nokta sayısı
    valid: bool                # Klinik aralıkta mı?


def find_landmarks(
    tooth_points: Dict[int, np.ndarray],
) -> Dict[int, ToothLandmark]:
    """
    Segmente edilmiş diş nokta gruplarından landmark'ları hesaplar.

    Klinik İş Akışı:
        Segmentor her dişin noktalarını verir → Bu fonksiyon her diş için:
        1. PCA ile ana ekseni bulur (meziodisal yön)
        2. Eksen üzerindeki uç noktaları = mezial/distal belirler
        3. Öklid mesafesini hesaplar = genişlik (mm)

    Args:
        tooth_points: Dict[fdi → (M, 3) koordinat dizisi].
                     Her dişe ait noktaların mm koordinatları.

    Returns:
        Dict[fdi → ToothLandmark]: Her diş için landmark bilgisi.
    """
    results: Dict[int, ToothLandmark] = {}

    for fdi, points in tooth_points.items():
        if len(points) < 10:
            # Çok az nokta — segmentasyon hatası
            continue

        landmark = _compute_tooth_landmark(fdi, points)
        if landmark is not None:
            results[fdi] = landmark

    return results


def _compute_tooth_landmark(
    fdi: int,
    points: np.ndarray,
) -> Optional[ToothLandmark]:
    """
    Tek bir diş için PCA tabanlı landmark hesabı.

    Yöntem:
        1. Noktaları merkeze al
        2. Kovaryans matrisini hesapla
        3. Özdeğer ayrıştırması → principal axis (en büyük özdeğer)
        4. Noktaları ana eksene projeksiyon yap
        5. En uç noktalar = mezial / distal

    Klinik Not:
        Dişler yaklaşık elipsoid şeklindedir. En uzun eksen
        meziodisal yönle (ön-arka) hizalanır. İkinci eksen
        bukkolingual (yanak-dil) yönüdür.

    Args:
        fdi: FDI diş numarası.
        points: (M, 3) diş noktaları (mm koordinatları).

    Returns:
        ToothLandmark veya None (hesaplama başarısızsa).
    """
    try:
        # ── Merkeze al ──
        centroid = points.mean(axis=0)
        centered = points - centroid

        # ── PCA: Kovaryans matrisinden ana eksenleri bul ──
        cov = np.cov(centered.T)  # 3×3 kovaryans
        eigenvalues, eigenvectors = np.linalg.eigh(cov)

        # eigh küçükten büyüğe sıralar → en büyük özdeğer sonda
        principal_axis = eigenvectors[:, -1]  # En uzun eksen
        principal_axis = principal_axis / np.linalg.norm(principal_axis)

        # ── Noktaları ana eksene projeksiyon yap ──
        projections = centered @ principal_axis  # N skaler değer

        # ── Uç noktaları bul — Curvature Snap ile ──
        # Salt projeksiyon uçları yerine, uç bölgede mean curvature
        # minimumunu yakala → gerçek diş köşesi (embrasür bölgesi)
        
        p10 = np.percentile(projections, 10)
        p90 = np.percentile(projections, 90)

        mesial_zone_mask = projections <= p10
        distal_zone_mask = projections >= p90

        # Curvature proxy: komşu noktalardan uzaklık varyansı
        # Gerçek curvature kütüphanesi olmadan yaklaşım:
        # İnterproksimal köşelerde yüzey daha "düz" değil, daha "girintili"
        # → yerel nokta yoğunluğu düşük
        def pick_corner(zone_mask: np.ndarray) -> np.ndarray:
            """Verilen bölgede en izole noktayı döndürür (köşe proxy)."""
            zone_idx = np.where(zone_mask)[0]
            if len(zone_idx) == 0:
                return points[np.argmin(projections) if zone_mask is mesial_zone_mask else np.argmax(projections)]
            zone_pts = points[zone_idx]
            if len(zone_pts) == 1:
                return zone_pts[0]
            # Her noktanın k en yakın komşusuna ortalama mesafe
            k = min(8, len(zone_pts) - 1)
            from sklearn.neighbors import NearestNeighbors
            nbrs = NearestNeighbors(n_neighbors=k + 1).fit(zone_pts)
            distances, _ = nbrs.kneighbors(zone_pts)
            mean_dist = distances[:, 1:].mean(axis=1)  # kendisi hariç
            # En yüksek ortalama mesafe = en izole = embrasür köşesi
            return zone_pts[np.argmax(mean_dist)]

        point_min = pick_corner(mesial_zone_mask)
        point_max = pick_corner(distal_zone_mask)
        width_mm = float(np.linalg.norm(point_max - point_min))

        # ── Mezial/Distal yönü belirle ──
        # FDI numarasına göre mezial yönü belirle:
        # - Üst sağ (11-18) ve alt sağ (41-48): mezial = büyük X yönünde
        # - Üst sol (21-28) ve alt sol (31-38): mezial = küçük X yönünde
        quadrant = fdi // 10  # 1=üst sağ, 2=üst sol, 3=alt sol, 4=alt sağ

        if quadrant in (1, 4):  # Sağ taraf: mezial = merkeze yakın (büyük X)
            if point_max[0] > point_min[0]:
                mesial, distal = point_max, point_min
            else:
                mesial, distal = point_min, point_max
        else:  # Sol taraf: mezial = merkeze yakın (küçük X)
            if point_min[0] < point_max[0]:
                mesial, distal = point_min, point_max
            else:
                mesial, distal = point_max, point_min

        # ── Klinik doğrulama ──
        tooth_label = f"{fdi} ({TOOTH_NAMES.get(fdi, '')})"
        valid, _ = validate_measurement(width_mm, tooth_label)

        return ToothLandmark(
            fdi=fdi,
            mesial=mesial,
            distal=distal,
            width_mm=round(width_mm, 2),
            centroid=centroid,
            principal_axis=principal_axis,
            n_points=len(points),
            valid=valid,
        )

    except Exception:
        return None


def landmarks_to_measurements(
    landmarks: Dict[int, ToothLandmark],
) -> Dict[int, float]:
    """
    Landmark sonuçlarını Bolton ölçüm dict'ine dönüştürür.

    Args:
        landmarks: Dict[fdi → ToothLandmark].

    Returns:
        Dict[fdi → width_mm]: Bolton analiz fonksiyonlarının beklediği format.
    """
    return {fdi: lm.width_mm for fdi, lm in landmarks.items()}


def landmarks_to_dataframe_rows(
    landmarks: Dict[int, ToothLandmark],
) -> list:
    """
    Landmark sonuçlarını MeasurementPanel DataFrame satırlarına dönüştürür.

    Returns:
        List[dict]: Her eleman bir DataFrame satırı.
    """
    rows = []
    for fdi, lm in sorted(landmarks.items()):
        jaw = "maxillary" if fdi < 30 else "mandibular"
        rows.append({
            "tooth_fdi": fdi,
            "jaw": jaw,
            "mesial_xyz": lm.mesial.tolist(),
            "distal_xyz": lm.distal.tolist(),
            "width_mm": lm.width_mm,
        })
    return rows
