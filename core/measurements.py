"""
core/measurements.py — 3D Mesafe Ölçüm Araçları
=================================================
Faz 1–2: Nokta tabanlı mesafe hesaplama ve doğrulama.

Klinik Bağlam:
    Meziodisal genişlik, bir dişin en geniş temas noktaları arasındaki
    mesafedir (mezial–distal). Ortodontistler bu değeri kumpas ile ölçer;
    bu modül 3D mesh üzerinde seçilen noktalar arasındaki Öklidyen
    mesafeyi hesaplar.
"""

import numpy as np
from typing import Tuple, Optional


def euclidean_distance_3d(
    point_a: np.ndarray,
    point_b: np.ndarray
) -> float:
    """
    İki 3D nokta arasındaki Öklidyen mesafeyi hesaplar.

    Klinik Not:
        Bu, meziodisal genişlik ölçümünün temel fonksiyonudur.
        Sonuçlar milimetre cinsindendir (STL dosyaları genellikle mm birimindedir).

    Args:
        point_a: İlk noktanın (x, y, z) koordinatları.
        point_b: İkinci noktanın (x, y, z) koordinatları.

    Returns:
        float: İki nokta arasındaki mesafe (mm).

    Raises:
        ValueError: Koordinat dizileri geçersizse.
    """
    a = np.asarray(point_a, dtype=np.float64)
    b = np.asarray(point_b, dtype=np.float64)

    if a.shape != (3,) or b.shape != (3,):
        raise ValueError(
            f"Her iki nokta da 3 boyutlu olmalıdır. "
            f"Alınan: {a.shape} ve {b.shape}"
        )

    return float(np.linalg.norm(a - b))


def validate_measurement(
    width_mm: float,
    tooth_label: str = ""
) -> Tuple[bool, str]:
    """
    Ölçülen meziodisal genişliğin klinik olarak makul olup olmadığını kontrol eder.

    Klinik Not:
        Normal meziodisal genişlikler genellikle şu aralıktadır:
        - Alt kesici dişler: ~5–6 mm
        - Üst merkezi kesici: ~8–9 mm
        - Kaninler: ~7–8 mm
        - Premolarlar: ~6–8 mm
        - Birinci molarlar: ~10–11 mm

        1 mm'den küçük veya 15 mm'den büyük değerler muhtemelen
        hatalı nokta seçiminden kaynaklanır.

    Args:
        width_mm: Ölçülen genişlik değeri (mm).
        tooth_label: Dişin FDI numarası veya adı (hata mesajları için).

    Returns:
        Tuple[bool, str]: (geçerli_mi, uyarı_mesajı)
    """
    # Fiziksel olarak imkansız: negatif veya sıfır mesafe
    if width_mm <= 0:
        return False, f"Geçersiz ölçüm ({tooth_label}): {width_mm:.2f} mm — negatif veya sıfır değer."

    # Klinik olarak mantıksız alt sınır
    MIN_WIDTH_MM = 2.0
    if width_mm < MIN_WIDTH_MM:
        return False, (
            f"⚠ Uyarı ({tooth_label}): {width_mm:.2f} mm — bu değer tipik diş genişliğinin "
            f"altında. Nokta seçimini kontrol edin."
        )

    # Klinik olarak mantıksız üst sınır
    MAX_WIDTH_MM = 15.0
    if width_mm > MAX_WIDTH_MM:
        return False, (
            f"⚠ Uyarı ({tooth_label}): {width_mm:.2f} mm — bu değer tipik diş genişliğinin "
            f"üzerinde. Nokta seçimini kontrol edin."
        )

    return True, ""
