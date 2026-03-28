import type { AnalysisMode } from "@/lib/tooth-config";
import type { BoltonResult, MeshInfo, SessionPayload } from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export async function checkApiHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function analyzeBolton(
  mode: AnalysisMode,
  measurements: Record<number, number>,
): Promise<BoltonResult> {
  const endpoint = mode === "anterior" ? "anterior" : "overall";

  const response = await fetch(`${API_BASE_URL}/api/v1/analysis/${endpoint}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ measurements }),
    cache: "no-store",
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? "Analiz tamamlanamadi.");
  }
  return payload as BoltonResult;
}

export async function inspectMesh(file: File): Promise<MeshInfo> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/v1/mesh/info`, {
    method: "POST",
    body: formData,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? "STL bilgisi okunamadi.");
  }
  return payload as MeshInfo;
}

export async function createOcclusionSession(payload: {
  maxillaFile: File;
  mandibleFile: File;
}): Promise<{
  session_id: string;
  collision_backend: string;
}> {
  const formData = new FormData();
  formData.append("maxilla_file", payload.maxillaFile);
  formData.append("mandible_file", payload.mandibleFile);

  const response = await fetch(`${API_BASE_URL}/api/v1/mesh/occlusion-session`, {
    method: "POST",
    body: formData,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? "Kapanis mesh oturumu olusturulamadi.");
  }
  return body as {
    session_id: string;
    collision_backend: string;
  };
}

export async function resolveOcclusionShift(payload: {
  sessionId: string;
  currentX: number;
  currentY: number;
  currentZ: number;
  targetX: number;
  targetY: number;
  targetZ: number;
  stepMm?: number;
}): Promise<{
  applied_x: number;
  applied_y: number;
  applied_z: number;
  collided: boolean;
  collision_backend: string;
}> {
  const formData = new FormData();
  formData.append("session_id", payload.sessionId);
  formData.append("current_x", String(payload.currentX));
  formData.append("current_y", String(payload.currentY));
  formData.append("current_z", String(payload.currentZ));
  formData.append("target_x", String(payload.targetX));
  formData.append("target_y", String(payload.targetY));
  formData.append("target_z", String(payload.targetZ));
  formData.append("step_mm", String(payload.stepMm ?? 0.1));

  const response = await fetch(`${API_BASE_URL}/api/v1/mesh/resolve-occlusion-session`, {
    method: "POST",
    body: formData,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? "Kapanis kaydirma hesabi tamamlanamadi.");
  }
  return body as {
    applied_x: number;
    applied_y: number;
    applied_z: number;
    collided: boolean;
    collision_backend: string;
  };
}

interface ExportPayload {
  measurements: Record<number, number>;
  patient_id: string;
  report_date: string;
  maxilla_filename: string;
  mandible_filename: string;
  treatment_notes: string;
  template_path?: string;
}

export async function downloadExport(
  format: "csv" | "json" | "pdf" | "excel",
  payload: ExportPayload,
): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/v1/export/${format}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorPayload = await response.json();
    throw new Error(errorPayload.detail ?? "Disa aktarma tamamlanamadi.");
  }

  return response.blob();
}

export async function listPatients(search = "") {
  const query = search ? `?q=${encodeURIComponent(search)}` : "";
  const response = await fetch(`${API_BASE_URL}/api/v1/patients${query}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Hasta listesi alinamadi.");
  }
  return response.json();
}

export async function createPatient(payload: { name: string; patient_code?: string; notes?: string }) {
  const response = await fetch(`${API_BASE_URL}/api/v1/patients`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? "Hasta olusturulamadi.");
  }
  return body;
}

export async function listRecords(patientId?: number, search = "") {
  const params = new URLSearchParams();
  if (patientId) {
    params.set("patient_id", String(patientId));
  }
  if (search) {
    params.set("q", search);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE_URL}/api/v1/records${query}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Kayit listesi alinamadi.");
  }
  return response.json();
}

export async function saveRecord(payload: {
  patient_id: number;
  title: string;
  analysis_mode: AnalysisMode;
  payload: SessionPayload;
  record_id?: number | null;
}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? "Kayit saklanamadi.");
  }
  return body;
}

export async function deleteRecord(recordId: number) {
  const response = await fetch(`${API_BASE_URL}/api/v1/records/${recordId}`, {
    method: "DELETE",
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? "Kayit silinemedi.");
  }
  return body;
}
