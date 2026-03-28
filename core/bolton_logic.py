"""
core/bolton_logic.py — Bolton Analiz Hesaplama Motoru
=====================================================
Faz 1–2: Temel Bolton oran hesaplamaları.

Klinik Bağlam:
    Bolton Analizi (Bolton, 1958), mandibüler ve maksiller diş boyutları
    arasındaki orantıyı değerlendirir. İki temel oran hesaplanır:

    1. ANTERIOR ORAN (Anterior Ratio):
       Mandibüler 3-3 toplamı / Maksiller 3-3 toplamı × 100
       Hedef: %77.2 (±1 SD = %74.5 – %80.4)

    2. GENEL ORAN (Overall Ratio):
       Mandibüler 6-6 toplamı / Maksiller 6-6 toplamı × 100
       Hedef: %91.3 (±1 SD = %87.5 – %94.8)

    Klinik Anlam:
    - Oran yüksekse → Mandibüler diş fazlası var (alt dişler göreceli büyük)
    - Oran düşükse → Maksiller diş fazlası var (üst dişler göreceli büyük)

Referans:
    Bolton WA. Disharmony in tooth size and its relation to the analysis
    and treatment of malocclusion. Angle Orthod. 1958;28:113-130.
"""

from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass, field

import numpy as np


# ──────────────────────────────────────────────────
# FDI Diş Numaralama Sistemi (ISO 3950)
# ──────────────────────────────────────────────────
# Üst sağ: 11-18 | Üst sol: 21-28
# Alt sol: 31-38 | Alt sağ: 41-48

# Bolton analizinde kullanılan dişler (FDI numaraları):
# Anterior analiz: Kanin-kanin arası (3-3)
# Overall analiz: Birinci molar-birinci molar arası (6-6)

# Maksiller (üst çene) anterior dişler: sağ kaninden sol kanine
MAXILLARY_ANTERIOR = [13, 12, 11, 21, 22, 23]

# Mandibüler (alt çene) anterior dişler: sağ kaninden sol kanine
MANDIBULAR_ANTERIOR = [43, 42, 41, 31, 32, 33]

# Maksiller (üst çene) overall dişler: sağ 1. molardan sol 1. molara
MAXILLARY_OVERALL = [16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26]

# Mandibüler (alt çene) overall dişler: sağ 1. molardan sol 1. molara
MANDIBULAR_OVERALL = [46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36]

# FDI numaralarına karşılık gelen Türkçe diş adları
TOOTH_NAMES = {
    # Üst sağ çeyrek
    11: "Üst Sağ Santral Kesici",
    12: "Üst Sağ Lateral Kesici",
    13: "Üst Sağ Kanin",
    14: "Üst Sağ 1. Premolar",
    15: "Üst Sağ 2. Premolar",
    16: "Üst Sağ 1. Molar",
    # Üst sol çeyrek
    21: "Üst Sol Santral Kesici",
    22: "Üst Sol Lateral Kesici",
    23: "Üst Sol Kanin",
    24: "Üst Sol 1. Premolar",
    25: "Üst Sol 2. Premolar",
    26: "Üst Sol 1. Molar",
    # Alt sol çeyrek
    31: "Alt Sol Santral Kesici",
    32: "Alt Sol Lateral Kesici",
    33: "Alt Sol Kanin",
    34: "Alt Sol 1. Premolar",
    35: "Alt Sol 2. Premolar",
    36: "Alt Sol 1. Molar",
    # Alt sağ çeyrek
    41: "Alt Sağ Santral Kesici",
    42: "Alt Sağ Lateral Kesici",
    43: "Alt Sağ Kanin",
    44: "Alt Sağ 1. Premolar",
    45: "Alt Sağ 2. Premolar",
    46: "Alt Sağ 1. Molar",
}


# ──────────────────────────────────────────────────
# Bolton Referans Değerleri (Bolton, 1958)
# ──────────────────────────────────────────────────

@dataclass(frozen=True)
class BoltonReference:
    """Bolton normatif değerleri — değiştirilemez."""
    # Anterior oran referans değerleri
    ANTERIOR_MEAN: float = 77.2      # %
    ANTERIOR_SD: float = 1.65        # Standart sapma
    ANTERIOR_MIN: float = 74.5       # Alt sınır (mean - 1 SD ≈ aralık)
    ANTERIOR_MAX: float = 80.4       # Üst sınır (mean + 1 SD ≈ aralık)

    # Overall oran referans değerleri
    OVERALL_MEAN: float = 91.3       # %
    OVERALL_SD: float = 1.91         # Standart sapma
    OVERALL_MIN: float = 87.5        # Alt sınır
    OVERALL_MAX: float = 94.8        # Üst sınır


BOLTON_REF = BoltonReference()


# ──────────────────────────────────────────────────
# Analiz Sonuç Veri Yapısı
# ──────────────────────────────────────────────────

@dataclass
class BoltonResult:
    """Tek bir Bolton analizi sonucunu temsil eder."""
    analysis_type: str                # "anterior" veya "overall"
    mandibular_sum: float             # Mandibüler toplamı (mm)
    maxillary_sum: float              # Maksiller toplamı (mm)
    ratio: float                      # Hesaplanan oran (%)
    ideal_ratio: float                # Referans oran (%)
    difference: float                 # Fark (hesaplanan - ideal) (%)
    discrepancy_mm: float             # Diş boyutu uyumsuzluğu (mm)
    discrepancy_arch: str             # "mandibular" veya "maxillary" fazlası
    within_normal: bool               # Normal aralıkta mı?
    interpretation: str               # Klinik yorum


# ──────────────────────────────────────────────────
# Bolton Hesaplama Fonksiyonları
# ──────────────────────────────────────────────────

def calculate_bolton_ratio(
    mandibular_sum: float,
    maxillary_sum: float
) -> float:
    """
    Bolton oranını hesaplar: (mandibüler / maksiller) × 100

    Args:
        mandibular_sum: Mandibüler diş genişlikleri toplamı (mm).
        maxillary_sum: Maksiller diş genişlikleri toplamı (mm).

    Returns:
        float: Bolton oranı (%).

    Raises:
        ValueError: Toplam değerler sıfır veya negatifse.
    """
    if maxillary_sum <= 0:
        raise ValueError("Maksiller toplam sıfır veya negatif olamaz.")
    if mandibular_sum <= 0:
        raise ValueError("Mandibüler toplam sıfır veya negatif olamaz.")

    return (mandibular_sum / maxillary_sum) * 100.0


def calculate_discrepancy(
    mandibular_sum: float,
    maxillary_sum: float,
    ideal_ratio: float
) -> Tuple[float, str]:
    """
    Diş boyutu uyumsuzluğunu milimetre cinsinden hesaplar.

    Klinik Not:
        Bu değer, IPR (İnterproksimal Redüksiyon) veya protez
        genişletme planlamasında doğrudan kullanılır.

        Formül:
        - Beklenen mandibüler toplam = maksiller toplam × (ideal_ratio / 100)
        - Uyumsuzluk = gerçek mandibüler toplam - beklenen mandibüler toplam
        - Pozitif → Mandibüler fazlası (alt dişler göreceli büyük)
        - Negatif → Maksiller fazlası (üst dişler göreceli büyük)

    Args:
        mandibular_sum: Gerçek mandibüler toplam (mm).
        maxillary_sum: Gerçek maksiller toplam (mm).
        ideal_ratio: İdeal Bolton oranı (% cinsinden, ör. 77.2).

    Returns:
        Tuple[float, str]: (uyumsuzluk_mm, hangi_arkta_fazlalık)
    """
    ratio = calculate_bolton_ratio(mandibular_sum, maxillary_sum)
    ratio_decimal = ideal_ratio / 100.0
    lower_threshold = ideal_ratio - 0.05
    upper_threshold = ideal_ratio + 0.05

    if ratio < lower_threshold:
        discrepancy = maxillary_sum - (mandibular_sum / ratio_decimal)
        return discrepancy, "maxillary"

    if ratio >= upper_threshold:
        discrepancy = mandibular_sum - (maxillary_sum * ratio_decimal)
        return discrepancy, "mandibular"

    return 0.0, "none"


def _validate_and_sum_teeth(
    measurements: Dict[int, float],
    maxillary_teeth: List[int],
    mandibular_teeth: List[int],
    analysis_label: str,
) -> Tuple[float, float]:
    """
    Bolton analizinde kullanılacak üst/alt diş setlerini doğrular ve toplar.

    Formül:
        Oran = (Alt toplam / Üst toplam) × 100

    Args:
        measurements: {FDI: width_mm}
        maxillary_teeth: Analizde kullanılacak üst diş listesi.
        mandibular_teeth: Analizde kullanılacak alt diş listesi.
        analysis_label: Hata metni için analiz adı.

    Returns:
        Tuple[float, float]: (maxillary_sum, mandibular_sum)
    """
    missing_max = [t for t in maxillary_teeth if t not in measurements]
    missing_mand = [t for t in mandibular_teeth if t not in measurements]

    if missing_max:
        names = [f"{t} ({TOOTH_NAMES.get(t, '?')})" for t in missing_max]
        raise ValueError(f"Eksik maksiller {analysis_label} ölçümler: {', '.join(names)}")

    if missing_mand:
        names = [f"{t} ({TOOTH_NAMES.get(t, '?')})" for t in missing_mand]
        raise ValueError(f"Eksik mandibüler {analysis_label} ölçümler: {', '.join(names)}")

    maxillary_sum = sum(float(measurements[t]) for t in maxillary_teeth)
    mandibular_sum = sum(float(measurements[t]) for t in mandibular_teeth)
    return maxillary_sum, mandibular_sum


def _analyze_bolton_group(
    *,
    measurements: Dict[int, float],
    analysis_type: str,
    analysis_label: str,
    maxillary_teeth: List[int],
    mandibular_teeth: List[int],
    ideal_ratio: float,
    normal_min: float,
    normal_max: float,
) -> BoltonResult:
    """
    Bolton analizini doğrudan klasik formülle hesaplar.

    Anterior Oran:
        (Alt 6 anterior toplamı / Üst 6 anterior toplamı) × 100

    Overall Oran:
        (Alt 12 diş toplamı / Üst 12 diş toplamı) × 100
    """
    maxillary_sum, mandibular_sum = _validate_and_sum_teeth(
        measurements,
        maxillary_teeth,
        mandibular_teeth,
        analysis_label,
    )

    ratio = calculate_bolton_ratio(mandibular_sum, maxillary_sum)
    discrepancy_mm, disc_arch = calculate_discrepancy(
        mandibular_sum,
        maxillary_sum,
        ideal_ratio,
    )
    within_normal = normal_min <= ratio <= normal_max
    interpretation = _generate_interpretation(
        analysis_label.capitalize(),
        ratio,
        ideal_ratio,
        discrepancy_mm,
        disc_arch,
        within_normal,
    )

    return BoltonResult(
        analysis_type=analysis_type,
        mandibular_sum=round(mandibular_sum, 2),
        maxillary_sum=round(maxillary_sum, 2),
        ratio=round(ratio, 2),
        ideal_ratio=ideal_ratio,
        difference=round(ratio - ideal_ratio, 2),
        discrepancy_mm=round(discrepancy_mm, 2),
        discrepancy_arch=disc_arch,
        within_normal=within_normal,
        interpretation=interpretation,
    )


def analyze_anterior(
    measurements: Dict[int, float]
) -> BoltonResult:
    """
    Anterior Bolton analizi: Kanin–kanin arası (3-3).

    Klinik Not:
        6 üst + 6 alt = toplam 12 anterior diş ölçümü gereklidir.
        Eksik ölçümler analizi geçersiz kılar.

    Args:
        measurements: {FDI_numarası: meziodisal_genişlik_mm} sözlüğü.

    Returns:
        BoltonResult: Anterior analiz sonucu.

    Raises:
        ValueError: Gerekli dişlerin ölçümleri eksikse.
    """
    return _analyze_bolton_group(
        measurements=measurements,
        analysis_type="anterior",
        analysis_label="anterior",
        maxillary_teeth=MAXILLARY_ANTERIOR,
        mandibular_teeth=MANDIBULAR_ANTERIOR,
        ideal_ratio=BOLTON_REF.ANTERIOR_MEAN,
        normal_min=BOLTON_REF.ANTERIOR_MIN,
        normal_max=BOLTON_REF.ANTERIOR_MAX,
    )


def analyze_overall(
    measurements: Dict[int, float]
) -> BoltonResult:
    """
    Overall Bolton analizi: Birinci molar–birinci molar arası (6-6).

    Klinik Not:
        12 üst + 12 alt = toplam 24 diş ölçümü gereklidir.

    Args:
        measurements: {FDI_numarası: meziodisal_genişlik_mm} sözlüğü.

    Returns:
        BoltonResult: Overall analiz sonucu.

    Raises:
        ValueError: Gerekli dişlerin ölçümleri eksikse.
    """
    return _analyze_bolton_group(
        measurements=measurements,
        analysis_type="overall",
        analysis_label="overall",
        maxillary_teeth=MAXILLARY_OVERALL,
        mandibular_teeth=MANDIBULAR_OVERALL,
        ideal_ratio=BOLTON_REF.OVERALL_MEAN,
        normal_min=BOLTON_REF.OVERALL_MIN,
        normal_max=BOLTON_REF.OVERALL_MAX,
    )


def _generate_interpretation(
    analysis_name: str,
    ratio: float,
    ideal: float,
    discrepancy_mm: float,
    disc_arch: str,
    within_normal: bool
) -> str:
    """
    Klinik yorum metni oluşturur.

    Args:
        analysis_name: "Anterior" veya "Overall".
        ratio: Hesaplanan oran (%).
        ideal: İdeal oran (%).
        discrepancy_mm: Uyumsuzluk (mm).
        disc_arch: Fazlalığın olduğu ark.
        within_normal: Normal aralıkta mı?

    Returns:
        str: Klinik yorum metni (Türkçe).
    """
    if within_normal:
        return (
            f"✅ {analysis_name} oran (%{ratio:.1f}) normal sınırlar içindedir. "
            f"Diş boyutu uyumu yeterlidir."
        )

    abs_disc = abs(discrepancy_mm)

    if disc_arch == "mandibular":
        return (
            f"⚠ {analysis_name} oran (%{ratio:.1f}) normalden yüksektir "
            f"(ideal: %{ideal:.1f}). "
            f"Mandibüler diş fazlası: {abs_disc:.1f} mm. "
            f"Alt dişlerde IPR (İnterproksimal Redüksiyon) veya "
            f"üst arkta protetik genişletme düşünülebilir."
        )
    else:
        return (
            f"⚠ {analysis_name} oran (%{ratio:.1f}) normalden düşüktür "
            f"(ideal: %{ideal:.1f}). "
            f"Maksiller diş fazlası: {abs_disc:.1f} mm. "
            f"Üst dişlerde IPR veya alt arkta protetik genişletme düşünülebilir."
        )
