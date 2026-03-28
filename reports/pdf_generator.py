"""
reports/pdf_generator.py — Klinik PDF Rapor Oluşturucu
=======================================================
Faz 4: ReportLab kullanarak Bolton Analizi klinik raporunu PDF olarak
dışa aktarır.

Rapor İçeriği:
    1. Klinik bilgiler (hasta ID, tarih, STL dosya adları)
    2. Tam ölçüm tablosu (FDI, diş adı, çene, genişlik mm)
    3. Anterior Bolton oranı — referans aralık + uyumsuzluk
    4. Overall Bolton oranı — referans aralık + uyumsuzluk
    5. Klinik yorum ve tedavi notu alanı
"""

from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from core.bolton_logic import (
    TOOTH_NAMES, BoltonResult, BOLTON_REF,
    MAXILLARY_ANTERIOR, MANDIBULAR_ANTERIOR,
    MAXILLARY_OVERALL, MANDIBULAR_OVERALL,
    analyze_anterior, analyze_overall,
)


# ──────────────────────────────────────────────────
# SABİTLER
# ──────────────────────────────────────────────────

# Rapor renkleri
COLOR_PRIMARY = colors.HexColor("#1B2838")
COLOR_ACCENT = colors.HexColor("#2A5F8F")
COLOR_GREEN = colors.HexColor("#06D6A0")
COLOR_RED = colors.HexColor("#E63946")
COLOR_LIGHT_BG = colors.HexColor("#F0F4F8")
COLOR_DARK_TEXT = colors.HexColor("#1B1B2F")
COLOR_GRAY = colors.HexColor("#6C6F93")

PAGE_WIDTH, PAGE_HEIGHT = A4
REPORT_FONT_REGULAR = "Helvetica"
REPORT_FONT_BOLD = "Helvetica-Bold"


def _register_report_fonts() -> tuple[str, str]:
    """Türkçe karakterleri güvenli biçimde gömülü fontlarla üret."""
    regular_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]
    bold_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]

    regular_name = REPORT_FONT_REGULAR
    bold_name = REPORT_FONT_BOLD

    try:
        registered_fonts = set(pdfmetrics.getRegisteredFontNames())
        for candidate in regular_candidates:
            if candidate.exists():
                regular_name = "SelcukBoltUnicode"
                if regular_name not in registered_fonts:
                    pdfmetrics.registerFont(TTFont(regular_name, str(candidate)))
                break

        for candidate in bold_candidates:
            if candidate.exists():
                bold_name = "SelcukBoltUnicodeBold"
                if bold_name not in registered_fonts:
                    pdfmetrics.registerFont(TTFont(bold_name, str(candidate)))
                break
    except Exception:
        return REPORT_FONT_REGULAR, REPORT_FONT_BOLD

    return regular_name, bold_name


def generate_bolton_report(
    output_path: str,
    patient_id: str,
    report_date: str,
    maxilla_filename: str,
    mandible_filename: str,
    measurements_df: pd.DataFrame,
    treatment_notes: str = "",
) -> str:
    """
    Bolton Analizi klinik PDF raporunu oluşturur.

    Args:
        output_path: PDF dosyasının kaydedileceği tam yol.
        patient_id: Hasta kimlik numarası / adı.
        report_date: Rapor tarihi (string).
        maxilla_filename: Üst çene STL dosya adı.
        mandible_filename: Alt çene STL dosya adı.
        measurements_df: Ölçüm DataFrame'i
            (tooth_fdi, jaw, width_mm sütunları gerekli).
        treatment_notes: Tedavi notu (opsiyonel).

    Returns:
        str: Oluşturulan PDF dosyasının tam yolu.

    Raises:
        ValueError: Zorunlu veriler eksikse.
    """
    if measurements_df.empty:
        raise ValueError("Ölçüm verisi boş — rapor oluşturulamaz.")

    report_font_regular, report_font_bold = _register_report_fonts()

    # ── Stilleri hazırla ──
    styles = _create_styles(report_font_regular, report_font_bold)

    # ── PDF belgesini oluştur ──
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Bolton Analizi - {patient_id}",
        author="SelçukBolt",
    )

    story = []

    # ═══════════════════════════════════════════
    # 1. BAŞLIK
    # ═══════════════════════════════════════════
    story.append(Paragraph("Bolton Analizi Klinik Raporu", styles["Title"]))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(
        width="100%", thickness=2,
        color=COLOR_ACCENT, spaceAfter=8
    ))
    story.append(Spacer(1, 2 * mm))

    # ═══════════════════════════════════════════
    # 2. HASTA BİLGİLERİ
    # ═══════════════════════════════════════════
    info_data = [
        ["Hasta ID / Ad:", patient_id, "Rapor Tarihi:", report_date],
        ["Üst Çene STL:", maxilla_filename, "Alt Çene STL:", mandible_filename],
    ]

    info_table = Table(info_data, colWidths=[30 * mm, 55 * mm, 30 * mm, 55 * mm])
    info_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), COLOR_GRAY),
        ("TEXTCOLOR", (2, 0), (2, -1), COLOR_GRAY),
        ("TEXTCOLOR", (1, 0), (1, -1), COLOR_DARK_TEXT),
        ("TEXTCOLOR", (3, 0), (3, -1), COLOR_DARK_TEXT),
        ("FONTNAME", (0, 0), (0, -1), report_font_regular),
        ("FONTNAME", (2, 0), (2, -1), report_font_regular),
        ("FONTNAME", (1, 0), (1, -1), report_font_bold),
        ("FONTNAME", (3, 0), (3, -1), report_font_bold),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5 * mm))

    # ═══════════════════════════════════════════
    # 3. ÖLÇÜM TABLOSU
    # ═══════════════════════════════════════════
    story.append(Paragraph("Meziodisal Genişlik Ölçümleri", styles["Heading2"]))
    story.append(Spacer(1, 2 * mm))

    # Ölçüm sırasına göre sortla
    measurement_order = (
        MAXILLARY_OVERALL + MANDIBULAR_OVERALL
    )
    sort_map = {fdi: i for i, fdi in enumerate(measurement_order)}

    sorted_df = measurements_df.copy()
    sorted_df["_sort"] = sorted_df["tooth_fdi"].map(
        lambda x: sort_map.get(int(x), 999)
    )
    sorted_df = sorted_df.sort_values("_sort").drop(columns=["_sort"])

    # Tablo başlıkları
    table_data = [["FDI", "Diş Adı", "Çene", "Genişlik (mm)"]]

    for _, row in sorted_df.iterrows():
        fdi = int(row["tooth_fdi"])
        jaw_label = "Üst" if row["jaw"] == "maxillary" else "Alt"
        tooth_name = TOOTH_NAMES.get(fdi, f"Diş {fdi}")
        width = f'{row["width_mm"]:.2f}'
        table_data.append([str(fdi), tooth_name, jaw_label, width])

    col_widths = [18 * mm, 60 * mm, 18 * mm, 30 * mm]
    meas_table = Table(table_data, colWidths=col_widths)

    # Tablo stili
    table_style = [
        # Başlık satırı
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), report_font_bold),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGNMENT", (0, 0), (-1, 0), "CENTER"),
        # Veri satırları
        ("FONTNAME", (0, 1), (-1, -1), report_font_regular),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGNMENT", (0, 1), (0, -1), "CENTER"),
        ("ALIGNMENT", (2, 1), (2, -1), "CENTER"),
        ("ALIGNMENT", (3, 1), (3, -1), "CENTER"),
        # Genel
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

    # Zebra çizgisi
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            table_style.append(
                ("BACKGROUND", (0, i), (-1, i), COLOR_LIGHT_BG)
            )

    meas_table.setStyle(TableStyle(table_style))
    story.append(meas_table)
    story.append(Spacer(1, 6 * mm))

    # ═══════════════════════════════════════════
    # 4. BOLTON ANALİZ SONUÇLARI
    # ═══════════════════════════════════════════
    story.append(Paragraph("Bolton Analiz Sonuçları", styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))

    # Ölçüm dict'i oluştur
    meas_dict = {}
    for _, row in measurements_df.iterrows():
        meas_dict[int(row["tooth_fdi"])] = float(row["width_mm"])

    # ── Anterior Analiz ──
    ant_result = _try_analysis(analyze_anterior, meas_dict, "Anterior (3-3)")
    if ant_result:
        story.extend(_build_ratio_card(ant_result, styles))
    else:
        story.append(Paragraph(
            "Anterior Analiz: Tüm anterior dişler ölçülmemiş.",
            styles["BodyGray"]
        ))

    story.append(Spacer(1, 4 * mm))

    # ── Overall Analiz ──
    ovr_result = _try_analysis(analyze_overall, meas_dict, "Overall (6-6)")
    if ovr_result:
        story.extend(_build_ratio_card(ovr_result, styles))
    else:
        story.append(Paragraph(
            "Overall Analiz: Tüm dişler ölçülmemiş.",
            styles["BodyGray"]
        ))

    story.append(Spacer(1, 4 * mm))

    # ── Referans Değerleri Tablosu ──
    story.append(Paragraph("Bolton Referans Değerleri (Bolton, 1958)", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))

    ref_data = [
        ["Analiz", "İdeal Oran (%)", "SD", "Normal Aralık (%)"],
        [
            "Anterior (3-3)",
            f"%{BOLTON_REF.ANTERIOR_MEAN}",
            f"±{BOLTON_REF.ANTERIOR_SD}",
            f"%{BOLTON_REF.ANTERIOR_MIN} – %{BOLTON_REF.ANTERIOR_MAX}"
        ],
        [
            "Overall (6-6)",
            f"%{BOLTON_REF.OVERALL_MEAN}",
            f"±{BOLTON_REF.OVERALL_SD}",
            f"%{BOLTON_REF.OVERALL_MIN} – %{BOLTON_REF.OVERALL_MAX}"
        ],
    ]

    ref_table = Table(ref_data, colWidths=[35 * mm, 30 * mm, 20 * mm, 40 * mm])
    ref_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), report_font_bold),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGNMENT", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
    ]))
    story.append(ref_table)
    story.append(Spacer(1, 6 * mm))

    # ═══════════════════════════════════════════
    # 5. TEDAVİ NOTU
    # ═══════════════════════════════════════════
    if treatment_notes.strip():
        story.append(Paragraph("Tedavi Notları", styles["Heading2"]))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(treatment_notes, styles["Body"]))
        story.append(Spacer(1, 4 * mm))

    # ═══════════════════════════════════════════
    # 6. ALTBILGI
    # ═══════════════════════════════════════════
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=COLOR_GRAY, spaceAfter=4
    ))
    story.append(Paragraph(
        f"Bu rapor SelçukBolt yazılımı tarafından {report_date} tarihinde "
        f"otomatik olarak oluşturulmuştur. Klinik karar verme süreçlerinde "
        f"yardımcı araç olarak kullanılmalıdır.",
        styles["Footer"]
    ))

    # ── PDF'i kaydet ──
    doc.build(story)

    return output_path


# ──────────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ──────────────────────────────────────────────────

def _create_styles(font_regular: str, font_bold: str) -> dict:
    """Rapor stillerini oluşturur."""
    styles = getSampleStyleSheet()

    styles["Normal"].fontName = font_regular
    styles["Title"].fontName = font_bold
    styles["Heading1"].fontName = font_bold
    styles["Heading2"].fontName = font_bold
    styles["Heading3"].fontName = font_bold

    styles.add(ParagraphStyle(
        name="Heading2Custom",
        parent=styles["Heading2"],
        fontName=font_bold,
        fontSize=13,
        textColor=COLOR_PRIMARY,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name="Heading3Custom",
        parent=styles["Heading3"],
        fontName=font_bold,
        fontSize=10,
        textColor=COLOR_ACCENT,
        spaceAfter=2,
    ))

    styles.add(ParagraphStyle(
        name="Body",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=9,
        textColor=COLOR_DARK_TEXT,
        leading=14,
    ))

    styles.add(ParagraphStyle(
        name="BodyGray",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=9,
        textColor=COLOR_GRAY,
        leading=14,
    ))

    styles.add(ParagraphStyle(
        name="Footer",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=7,
        textColor=COLOR_GRAY,
        alignment=TA_CENTER,
        leading=10,
    ))

    # Title doğrudan modifiye edilebilir (mevcut stil objesi)
    styles["Title"].fontSize = 16
    styles["Title"].textColor = COLOR_PRIMARY

    # Heading2/3 dict wrapper olarak dön — kullanım noktaları custom isimleri kullanacak
    result = {}
    for name in styles.byName:
        result[name] = styles[name]
    # Kolaylık kısayolları
    result["Heading2"] = styles["Heading2Custom"]
    result["Heading3"] = styles["Heading3Custom"]

    return result


def _try_analysis(analyze_fn, meas_dict, label) -> Optional[BoltonResult]:
    """Bolton analizini çalıştırır, hata varsa None döner."""
    try:
        return analyze_fn(meas_dict)
    except ValueError:
        return None


def _build_ratio_card(
    result: BoltonResult,
    styles: dict
) -> list:
    """
    Bolton sonucu için kart tarzı tablo oluşturur.

    Returns:
        list: story elemanları
    """
    elements = []

    type_label = "Anterior Oran (3-3)" if result.analysis_type == "anterior" else "Overall Oran (6-6)"
    status_color = COLOR_GREEN if result.within_normal else COLOR_RED
    status_text = "NORMAL" if result.within_normal else "UYUMSUZLUK"

    # Uyumsuzluk detayı
    abs_disc = abs(result.discrepancy_mm)
    if result.discrepancy_arch == "mandibular":
        disc_text = f"Mandibüler fazlalık: {abs_disc:.1f} mm"
    elif result.discrepancy_arch == "maxillary":
        disc_text = f"Maksiller fazlalık: {abs_disc:.1f} mm"
    else:
        disc_text = "Mükemmel uyum"

    formula_text = (
        f"Formül: ({result.mandibular_sum:.1f} / {result.maxillary_sum:.1f}) × 100 = %{result.ratio:.1f}"
    )

    card_data = [
        [type_label, "", "", status_text],
        [
            f"Maksiller Σ: {result.maxillary_sum:.1f} mm",
            f"Mandibüler Σ: {result.mandibular_sum:.1f} mm",
            f"Oran: %{result.ratio:.1f}",
            f"İdeal: %{result.ideal_ratio}",
        ],
        [
            f"Fark: {result.difference:+.1f}%",
            disc_text,
            f"Uyumsuzluk: {result.discrepancy_mm:+.1f} mm",
            "",
        ],
        [formula_text, "", "", ""],
    ]

    card_table = Table(card_data, colWidths=[42 * mm, 42 * mm, 35 * mm, 30 * mm])
    card_table.setStyle(TableStyle([
        # Başlık satırı
        ("FONTNAME", (0, 0), (0, 0), styles["Heading2"].fontName),
        ("FONTSIZE", (0, 0), (0, 0), 11),
        ("TEXTCOLOR", (0, 0), (0, 0), COLOR_PRIMARY),
        ("SPAN", (0, 0), (2, 0)),  # Başlık genişlet
        # Durum etiketi
        ("FONTNAME", (3, 0), (3, 0), styles["Heading2"].fontName),
        ("FONTSIZE", (3, 0), (3, 0), 9),
        ("TEXTCOLOR", (3, 0), (3, 0), status_color),
        ("ALIGNMENT", (3, 0), (3, 0), "RIGHT"),
        # Veri satırları
        ("FONTNAME", (0, 1), (-1, -1), styles["Body"].fontName),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_DARK_TEXT),
        ("SPAN", (0, 3), (3, 3)),
        ("TEXTCOLOR", (0, 3), (3, 3), COLOR_GRAY),
        # Genel
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 1, status_color),
        ("LINEBELOW", (0, 0), (-1, 0), 1, status_color),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))

    elements.append(card_table)

    # Klinik yorum
    if result.interpretation:
        elements.append(Spacer(1, 2 * mm))
        elements.append(Paragraph(result.interpretation, styles["Body"]))

    return elements
