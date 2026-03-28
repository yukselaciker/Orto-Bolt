"""
reports/excel_template_export.py — Bolton Excel şablonu doldurucu
=================================================================
Mevcut klinik Excel şablonunu bozmadan, diş ölçülerini ilgili
hücrelere yerleştirir ve Excel formüllerinin yeniden hesaplanmasını sağlar.
"""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd


SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

ET.register_namespace("", SHEET_NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
ET.register_namespace("x15", "http://schemas.microsoft.com/office/spreadsheetml/2010/11/main")
ET.register_namespace("xr", "http://schemas.microsoft.com/office/spreadsheetml/2014/revision")
ET.register_namespace("xr6", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision6")
ET.register_namespace("xr10", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision10")
ET.register_namespace("xr2", "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2")

NS = {"a": SHEET_NS}

MAXILLA_WIDTH_CELLS = {
    16: "B9", 15: "C9", 14: "D9", 13: "E9", 12: "F9", 11: "G9",
    21: "H9", 22: "I9", 23: "J9", 24: "K9", 25: "L9", 26: "M9",
}

MANDIBLE_WIDTH_CELLS = {
    46: "B11", 45: "C11", 44: "D11", 43: "E11", 42: "F11", 41: "G11",
    31: "H11", 32: "I11", 33: "J11", 34: "K11", 35: "L11", 36: "M11",
}


class BoltonExcelExportError(Exception):
    """Excel şablonuna veri yazımı sırasında oluşan hata."""


def export_bolton_excel_template(
    *,
    template_path: str | Path,
    output_path: str | Path,
    measurements_df: pd.DataFrame,
    patient_name: str = "",
    report_date: str = "",
    doctor_name: str = "",
    notes: str = "",
) -> str:
    """
    Verilen Bolton Excel şablonunu ölçüm verileriyle doldurur.

    Girdi hücreleri:
    - Üst 12 diş: `B9:M9`
    - Alt 12 diş: `B11:M11`

    Excel şablonundaki Bolton formülleri:
    - `D23 = (D21 / D22) * 100`
    - `M23 = (M21 / M22) * 100`
    """
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise BoltonExcelExportError(f"Excel şablonu bulunamadı: {template_path}")
    if measurements_df.empty:
        raise BoltonExcelExportError("Ölçüm verisi boş olduğu için Excel oluşturulamadı.")

    measurements = {
        int(row["tooth_fdi"]): float(row["width_mm"])
        for _, row in measurements_df.iterrows()
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(template_path, "r") as zin:
        workbook_xml = ET.fromstring(zin.read("xl/workbook.xml"))
        sheet_xml = ET.fromstring(zin.read("xl/worksheets/sheet1.xml"))

        _enable_full_recalc(workbook_xml)
        _fill_sheet(
            sheet_xml,
            measurements=measurements,
            patient_name=patient_name,
            report_date=report_date,
            doctor_name=doctor_name,
            notes=notes,
        )

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "xl/workbook.xml":
                    zout.writestr(item, ET.tostring(workbook_xml, encoding="utf-8", xml_declaration=True))
                elif item.filename == "xl/worksheets/sheet1.xml":
                    zout.writestr(item, ET.tostring(sheet_xml, encoding="utf-8", xml_declaration=True))
                else:
                    zout.writestr(item, zin.read(item.filename))

    return str(output_path)


def _enable_full_recalc(workbook_root: ET.Element) -> None:
    """Excel açıldığında tüm formüllerin yeniden hesaplanmasını zorlar."""
    calc_pr = workbook_root.find("a:calcPr", NS)
    if calc_pr is None:
        calc_pr = ET.SubElement(workbook_root, f"{{{SHEET_NS}}}calcPr")
    calc_pr.set("calcMode", "auto")
    calc_pr.set("fullCalcOnLoad", "1")
    calc_pr.set("forceFullCalc", "1")


def _fill_sheet(
    sheet_root: ET.Element,
    *,
    measurements: dict[int, float],
    patient_name: str,
    report_date: str,
    doctor_name: str,
    notes: str,
) -> None:
    """Tek sayfalı Excel şablonundaki ilgili hücreleri doldurur."""
    row_map = _build_row_map(sheet_root)

    for tooth_fdi, cell_ref in MAXILLA_WIDTH_CELLS.items():
        _set_numeric_cell(row_map, cell_ref, measurements.get(tooth_fdi))

    for tooth_fdi, cell_ref in MANDIBLE_WIDTH_CELLS.items():
        _set_numeric_cell(row_map, cell_ref, measurements.get(tooth_fdi))

    if patient_name:
        _set_string_cell(row_map, "B3", patient_name)
    if report_date:
        _set_string_cell(row_map, "M3", report_date)
    if doctor_name:
        _set_string_cell(row_map, "F3", doctor_name)
    if notes:
        _set_string_cell(row_map, "B58", notes)

    _populate_bolton_cache(row_map, measurements)


def _build_row_map(sheet_root: ET.Element) -> dict[int, ET.Element]:
    sheet_data = sheet_root.find("a:sheetData", NS)
    if sheet_data is None:
        raise BoltonExcelExportError("sheetData bulunamadı.")
    return {
        int(row.attrib["r"]): row
        for row in sheet_data.findall("a:row", NS)
    }


def _cell_ref_parts(cell_ref: str) -> tuple[str, int]:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    digits = "".join(ch for ch in cell_ref if ch.isdigit())
    return letters, int(digits)


def _find_or_create_cell(row_map: dict[int, ET.Element], cell_ref: str) -> ET.Element:
    col_letters, row_number = _cell_ref_parts(cell_ref)
    row = row_map.get(row_number)
    if row is None:
        raise BoltonExcelExportError(f"Şablonda {row_number}. satır bulunamadı.")

    existing = row.find(f"a:c[@r='{cell_ref}']", NS)
    if existing is not None:
        return existing

    cell = ET.Element(f"{{{SHEET_NS}}}c", {"r": cell_ref})
    inserted = False
    for index, current in enumerate(list(row)):
        current_ref = current.attrib.get("r", "")
        current_col, _ = _cell_ref_parts(current_ref)
        if current_col > col_letters:
            row.insert(index, cell)
            inserted = True
            break
    if not inserted:
        row.append(cell)
    return cell


def _clear_value_nodes(cell: ET.Element) -> None:
    for tag in ("f", "v", "is"):
        node = cell.find(f"{{{SHEET_NS}}}{tag}")
        if node is not None:
            cell.remove(node)


def _set_numeric_cell(row_map: dict[int, ET.Element], cell_ref: str, value: float | None) -> None:
    cell = _find_or_create_cell(row_map, cell_ref)
    _clear_value_nodes(cell)
    if value is None:
        cell.set("t", "n")
        value_node = ET.SubElement(cell, f"{{{SHEET_NS}}}v")
        value_node.text = "0"
        return

    cell.attrib.pop("t", None)
    value_node = ET.SubElement(cell, f"{{{SHEET_NS}}}v")
    value_node.text = f"{float(value):.2f}"


def _set_string_cell(row_map: dict[int, ET.Element], cell_ref: str, value: str) -> None:
    cell = _find_or_create_cell(row_map, cell_ref)
    _clear_value_nodes(cell)
    cell.set("t", "inlineStr")
    inline_str = ET.SubElement(cell, f"{{{SHEET_NS}}}is")
    text_node = ET.SubElement(inline_str, f"{{{SHEET_NS}}}t")
    text_node.text = value


def _set_formula_cached_value(row_map: dict[int, ET.Element], cell_ref: str, value) -> None:
    """Formülü bozmadan yalnızca cache değerini günceller."""
    cell = _find_or_create_cell(row_map, cell_ref)
    formula = cell.find(f"{{{SHEET_NS}}}f")
    if formula is None:
        return

    value_node = cell.find(f"{{{SHEET_NS}}}v")
    if value_node is None:
        value_node = ET.SubElement(cell, f"{{{SHEET_NS}}}v")

    if isinstance(value, str):
        cell.set("t", "str")
        value_node.text = value
    else:
        cell.attrib.pop("t", None)
        value_node.text = f"{float(value):.6f}"


def _populate_bolton_cache(row_map: dict[int, ET.Element], measurements: dict[int, float]) -> None:
    """Bolton alanındaki kritik formül hücrelerinin cache değerini günceller."""
    upper_6 = sum(measurements.get(tooth, 0.0) for tooth in (13, 12, 11, 21, 22, 23))
    lower_6 = sum(measurements.get(tooth, 0.0) for tooth in (43, 42, 41, 31, 32, 33))
    upper_12 = sum(measurements.get(tooth, 0.0) for tooth in MAXILLA_WIDTH_CELLS)
    lower_12 = sum(measurements.get(tooth, 0.0) for tooth in MANDIBLE_WIDTH_CELLS)

    anterior_ratio = (lower_6 / upper_6) * 100.0 if upper_6 else 0.0
    overall_ratio = (lower_12 / upper_12) * 100.0 if upper_12 else 0.0

    anterior_disc, anterior_text = _excel_discrepancy_and_text(
        lower_6,
        upper_6,
        ratio=anterior_ratio,
        ideal_ratio=77.2,
    )
    overall_disc, overall_text = _excel_discrepancy_and_text(
        lower_12,
        upper_12,
        ratio=overall_ratio,
        ideal_ratio=91.3,
    )

    _set_formula_cached_value(row_map, "D21", lower_6)
    _set_formula_cached_value(row_map, "D22", upper_6)
    _set_formula_cached_value(row_map, "D23", anterior_ratio)
    _set_formula_cached_value(row_map, "D24", anterior_disc)
    _set_formula_cached_value(row_map, "B24", anterior_text)

    _set_formula_cached_value(row_map, "M21", lower_12)
    _set_formula_cached_value(row_map, "M22", upper_12)
    _set_formula_cached_value(row_map, "M23", overall_ratio)
    _set_formula_cached_value(row_map, "M24", overall_disc)
    _set_formula_cached_value(row_map, "K24", overall_text)


def _excel_discrepancy_and_text(
    mandibular_sum: float,
    maxillary_sum: float,
    *,
    ratio: float,
    ideal_ratio: float,
) -> tuple[float, str]:
    ratio_decimal = ideal_ratio / 100.0
    lower_threshold = ideal_ratio - 0.05
    upper_threshold = ideal_ratio + 0.05

    if ratio < lower_threshold:
        return maxillary_sum - (mandibular_sum / ratio_decimal), "Maxilla'da ve"
    if ratio > upper_threshold:
        return mandibular_sum - (maxillary_sum * ratio_decimal), "Mandibula'da ve"
    return 0.0, "yoktur."
