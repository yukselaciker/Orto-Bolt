"""
reports/export_manager.py — SelçukBolt dışa aktarma yardımcıları
=================================================================
CSV ve JSON gibi hafif veri formatlarını ortak bir merkezden üretir.
Excel ve PDF akışları mevcut özel exporter'larda kalır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def export_measurements_csv(
    *,
    output_path: str | Path,
    measurements_df: pd.DataFrame,
) -> str:
    """Ölçüm tablosunu CSV formatında dışa aktarır."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    measurements_df.to_csv(output, index=False, encoding="utf-8-sig")
    return str(output)


def export_analysis_json(
    *,
    output_path: str | Path,
    payload: dict[str, Any],
) -> str:
    """Analiz durumunu JSON formatında dışa aktarır."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return str(output)
