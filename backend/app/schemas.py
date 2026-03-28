from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "SelcukBolt API"


class AnalysisRequest(BaseModel):
    measurements: dict[int, float] = Field(
        ...,
        description="FDI dis numarasina gore meziodistal genislikler (mm).",
        examples=[{11: 8.6, 12: 6.9, 13: 7.8}],
    )


class ExportRequest(BaseModel):
    measurements: dict[int, float] = Field(
        ...,
        description="FDI dis numarasina gore meziodistal genislikler (mm).",
    )
    patient_id: str = "Bilinmeyen Hasta"
    report_date: str = ""
    maxilla_filename: str = ""
    mandible_filename: str = ""
    treatment_notes: str = ""
    template_path: str = ""


class BoltonResultResponse(BaseModel):
    analysis_type: str
    mandibular_sum: float
    maxillary_sum: float
    ratio: float
    ideal_ratio: float
    difference: float
    discrepancy_mm: float
    discrepancy_arch: str
    within_normal: bool
    interpretation: str


class CombinedAnalysisResponse(BaseModel):
    anterior: BoltonResultResponse
    overall: BoltonResultResponse


class AnalysisModeMetadata(BaseModel):
    maxillary_teeth: list[int]
    mandibular_teeth: list[int]


class AnalysisMetadataResponse(BaseModel):
    app_name: str
    modes: dict[str, AnalysisModeMetadata]
    tooth_names: dict[int, str]
    references: dict[str, float]


class MeshInfoResponse(BaseModel):
    file_name: str
    point_count: int
    face_count: int
    width_mm: float
    height_mm: float
    depth_mm: float
    center: list[float]


class OcclusionSessionResponse(BaseModel):
    session_id: str
    collision_backend: str


class OcclusionResolveResponse(BaseModel):
    applied_x: float
    applied_y: float
    applied_z: float
    collided: bool
    collision_backend: str


class PatientCreateRequest(BaseModel):
    name: str
    patient_code: str = ""
    notes: str = ""


class PatientResponse(BaseModel):
    id: int
    name: str
    patient_code: str = ""
    notes: str = ""
    created_at: str


class RecordSaveRequest(BaseModel):
    patient_id: int
    title: str
    analysis_mode: str
    payload: dict
    record_id: int | None = None


class RecordResponse(BaseModel):
    id: int
    patient_id: int
    patient_name: str
    patient_code: str | None = ""
    title: str
    analysis_mode: str
    payload: dict
    created_at: str
    updated_at: str


class ApiErrorResponse(BaseModel):
    detail: str
    code: Literal["validation_error", "mesh_error", "internal_error"] = "validation_error"
