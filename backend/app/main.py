from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask

from core.stl_loader import STLLoadError

from .schemas import (
    AnalysisMetadataResponse,
    AnalysisRequest,
    ApiErrorResponse,
    CombinedAnalysisResponse,
    ExportRequest,
    HealthResponse,
    BoltonResultResponse,
    MeshInfoResponse,
    OcclusionSessionResponse,
    OcclusionResolveResponse,
    PatientCreateRequest,
    PatientResponse,
    RecordResponse,
    RecordSaveRequest,
)
from .storage import (
    create_patient,
    create_record,
    delete_record,
    get_record,
    init_storage,
    list_patients,
    list_records,
    update_record,
)
from .services import (
    analyze_anterior_measurements,
    analyze_combined_measurements,
    analyze_overall_measurements,
    build_metadata,
    build_export_payload,
    create_occlusion_session,
    inspect_uploaded_mesh,
    resolve_occlusion_shift,
    resolve_occlusion_shift_for_session,
    render_excel_report,
    render_pdf_report,
)


app = FastAPI(
    title="SelcukBolt API",
    version="1.0.0",
    summary="SelcukBolt klinik Bolton analiz mantigini web istemcilere acan API.",
)
init_storage()
WEB_APP_URL = os.environ.get("SELCUKBOLT_WEB_URL", "http://127.0.0.1:3000").rstrip("/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url=WEB_APP_URL or "http://127.0.0.1:3000", status_code=307)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def healthcheck() -> HealthResponse:
    return HealthResponse()


@app.get("/api/v1/patients", response_model=list[PatientResponse], tags=["records"])
def patients_endpoint(q: str = "") -> list[PatientResponse]:
    return [PatientResponse(**patient) for patient in list_patients(q)]


@app.post("/api/v1/patients", response_model=PatientResponse, tags=["records"])
def create_patient_endpoint(payload: PatientCreateRequest) -> PatientResponse:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Hasta adi zorunludur.")
    return PatientResponse(**create_patient(name=payload.name, patient_code=payload.patient_code, notes=payload.notes))


@app.get("/api/v1/records", response_model=list[RecordResponse], tags=["records"])
def records_endpoint(patient_id: int | None = None, q: str = "") -> list[RecordResponse]:
    return [RecordResponse(**record) for record in list_records(patient_id, q)]


@app.get("/api/v1/records/{record_id}", response_model=RecordResponse, tags=["records"])
def record_detail_endpoint(record_id: int) -> RecordResponse:
    try:
        return RecordResponse(**get_record(record_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Kayit bulunamadi.") from exc


@app.post("/api/v1/records", response_model=RecordResponse, tags=["records"])
def save_record_endpoint(payload: RecordSaveRequest) -> RecordResponse:
    try:
        if payload.record_id is not None:
            return RecordResponse(
                **update_record(
                    record_id=payload.record_id,
                    title=payload.title,
                    analysis_mode=payload.analysis_mode,
                    payload=payload.payload,
                )
            )
        return RecordResponse(
            **create_record(
                patient_id=payload.patient_id,
                title=payload.title,
                analysis_mode=payload.analysis_mode,
                payload=payload.payload,
            )
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz hasta secimi.") from exc


@app.delete("/api/v1/records/{record_id}", tags=["records"])
def delete_record_endpoint(record_id: int) -> dict:
    if not delete_record(record_id):
        raise HTTPException(status_code=404, detail="Kayit bulunamadi.")
    return {"deleted": True, "record_id": record_id}


@app.get("/api/v1/metadata", response_model=AnalysisMetadataResponse, tags=["analysis"])
def analysis_metadata() -> AnalysisMetadataResponse:
    return AnalysisMetadataResponse(**build_metadata())


@app.post(
    "/api/v1/analysis/anterior",
    response_model=BoltonResultResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["analysis"],
)
def analyze_anterior_endpoint(payload: AnalysisRequest) -> BoltonResultResponse:
    try:
        return BoltonResultResponse(**analyze_anterior_measurements(payload.measurements))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post(
    "/api/v1/analysis/overall",
    response_model=BoltonResultResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["analysis"],
)
def analyze_overall_endpoint(payload: AnalysisRequest) -> BoltonResultResponse:
    try:
        return BoltonResultResponse(**analyze_overall_measurements(payload.measurements))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post(
    "/api/v1/analysis/combined",
    response_model=CombinedAnalysisResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["analysis"],
)
def analyze_combined_endpoint(payload: AnalysisRequest) -> CombinedAnalysisResponse:
    try:
        return CombinedAnalysisResponse(**analyze_combined_measurements(payload.measurements))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post(
    "/api/v1/mesh/info",
    response_model=MeshInfoResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["mesh"],
)
async def mesh_info_endpoint(file: UploadFile = File(...)) -> MeshInfoResponse:
    try:
        return MeshInfoResponse(**(await inspect_uploaded_mesh(file)))
    except STLLoadError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post(
    "/api/v1/mesh/occlusion-session",
    response_model=OcclusionSessionResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["mesh"],
)
async def create_occlusion_session_endpoint(
    maxilla_file: UploadFile = File(...),
    mandible_file: UploadFile = File(...),
) -> OcclusionSessionResponse:
    try:
        return OcclusionSessionResponse(
            **create_occlusion_session(
                maxilla_filename=maxilla_file.filename or "maxilla.stl",
                maxilla_payload=await maxilla_file.read(),
                mandible_filename=mandible_file.filename or "mandible.stl",
                mandible_payload=await mandible_file.read(),
            )
        )
    except (ValueError, STLLoadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/v1/mesh/resolve-occlusion",
    response_model=OcclusionResolveResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["mesh"],
)
async def resolve_occlusion_endpoint(
    maxilla_file: UploadFile = File(...),
    mandible_file: UploadFile = File(...),
    current_x: float = Form(0.0),
    current_y: float = Form(0.0),
    current_z: float = Form(0.0),
    target_x: float = Form(0.0),
    target_y: float = Form(0.0),
    target_z: float = Form(0.0),
    step_mm: float = Form(0.1),
) -> OcclusionResolveResponse:
    try:
        return OcclusionResolveResponse(
            **resolve_occlusion_shift(
                maxilla_filename=maxilla_file.filename or "maxilla.stl",
                maxilla_payload=await maxilla_file.read(),
                mandible_filename=mandible_file.filename or "mandible.stl",
                mandible_payload=await mandible_file.read(),
                current_x=current_x,
                current_y=current_y,
                current_z=current_z,
                target_x=target_x,
                target_y=target_y,
                target_z=target_z,
                step_mm=step_mm,
            )
        )
    except (ValueError, STLLoadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/v1/mesh/resolve-occlusion-session",
    response_model=OcclusionResolveResponse,
    responses={400: {"model": ApiErrorResponse}},
    tags=["mesh"],
)
def resolve_occlusion_session_endpoint(
    session_id: str = Form(...),
    current_x: float = Form(0.0),
    current_y: float = Form(0.0),
    current_z: float = Form(0.0),
    target_x: float = Form(0.0),
    target_y: float = Form(0.0),
    target_z: float = Form(0.0),
    step_mm: float = Form(0.1),
) -> OcclusionResolveResponse:
    try:
        return OcclusionResolveResponse(
            **resolve_occlusion_shift_for_session(
                session_id=session_id,
                current_x=current_x,
                current_y=current_y,
                current_z=current_z,
                target_x=target_x,
                target_y=target_y,
                target_z=target_z,
                step_mm=step_mm,
            )
        )
    except (ValueError, STLLoadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/export/json", tags=["export"])
def export_json_endpoint(payload: ExportRequest):
    try:
        export_payload = build_export_payload(
            measurements=payload.measurements,
            patient_id=payload.patient_id,
            report_date=payload.report_date,
            maxilla_filename=payload.maxilla_filename,
            mandible_filename=payload.mandible_filename,
            treatment_notes=payload.treatment_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    export_payload["measurement_rows"] = export_payload["dataframe"].to_dict(orient="records")
    export_payload.pop("dataframe", None)
    return JSONResponse(export_payload)


@app.post("/api/v1/export/csv", tags=["export"])
def export_csv_endpoint(payload: ExportRequest):
    try:
        export_payload = build_export_payload(
            measurements=payload.measurements,
            patient_id=payload.patient_id,
            report_date=payload.report_date,
            maxilla_filename=payload.maxilla_filename,
            mandible_filename=payload.mandible_filename,
            treatment_notes=payload.treatment_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    temp = NamedTemporaryFile(delete=False, suffix=".csv")
    temp.close()
    export_payload["dataframe"].to_csv(temp.name, index=False, encoding="utf-8-sig")
    filename = f"selcukbolt_{Path(temp.name).stem}.csv"
    return FileResponse(
        temp.name,
        media_type="text/csv",
        filename=filename,
        background=BackgroundTask(lambda p=temp.name: Path(p).unlink(missing_ok=True)),
    )


@app.post("/api/v1/export/pdf", tags=["export"])
def export_pdf_endpoint(payload: ExportRequest):
    try:
        temp = NamedTemporaryFile(delete=False, suffix=".pdf")
        temp.close()
        output_path = render_pdf_report(
            output_path=temp.name,
            measurements=payload.measurements,
            patient_id=payload.patient_id,
            report_date=payload.report_date,
            maxilla_filename=payload.maxilla_filename,
            mandible_filename=payload.mandible_filename,
            treatment_notes=payload.treatment_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    safe_name = payload.patient_id.strip().replace(" ", "_") or "hasta"
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"selcukbolt_{safe_name}.pdf",
        background=BackgroundTask(lambda p=output_path: Path(p).unlink(missing_ok=True)),
    )


@app.post("/api/v1/export/excel", tags=["export"])
def export_excel_endpoint(payload: ExportRequest):
    try:
        temp = NamedTemporaryFile(delete=False, suffix=".xlsx")
        temp.close()
        output_path = render_excel_report(
            output_path=temp.name,
            measurements=payload.measurements,
            patient_id=payload.patient_id,
            report_date=payload.report_date,
            treatment_notes=payload.treatment_notes,
            template_path=payload.template_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    safe_name = payload.patient_id.strip().replace(" ", "_") or "hasta"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"selcukbolt_{safe_name}.xlsx",
        background=BackgroundTask(lambda p=output_path: Path(p).unlink(missing_ok=True)),
    )
