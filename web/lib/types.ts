import type { AnalysisMode, JawKey } from "@/lib/tooth-config";

export type MeasurementsState = Record<number, string>;

export interface BoltonResult {
  analysis_type: string;
  mandibular_sum: number;
  maxillary_sum: number;
  ratio: number;
  ideal_ratio: number;
  difference: number;
  discrepancy_mm: number;
  discrepancy_arch: string;
  within_normal: boolean;
  interpretation: string;
}

export interface CombinedAnalysis {
  anterior: BoltonResult;
  overall: BoltonResult;
}

export interface MeshInfo {
  file_name: string;
  point_count: number;
  face_count: number;
  width_mm: number;
  height_mm: number;
  depth_mm: number;
  center: number[];
}

export interface SessionEmbeddedFile {
  name: string;
  type: string;
  dataUrl: string;
}

export interface LandmarkPoint {
  id: string;
  jaw: "maxillary" | "mandibular";
  label: string;
  position: [number, number, number];
  coordinateSpace?: "world" | "mesh";
}

export interface SessionPayload {
  saved_at: string;
  mode: AnalysisMode;
  values: MeasurementsState;
  result: BoltonResult | null;
  maxillaInfo: MeshInfo | null;
  mandibleInfo: MeshInfo | null;
  activeViewerJaw: "maxillary" | "mandibular" | "occlusion";
  maxillaFile: SessionEmbeddedFile | null;
  mandibleFile: SessionEmbeddedFile | null;
  landmarks: LandmarkPoint[];
  landmarkDraft?: LandmarkPoint | null;
  landmarkPhase?: "mesial" | "distal";
  cameraPreset?: "occlusal" | "frontal" | "lateral";
  jawGap?: number;
  occlusionShiftX?: number;
  occlusionShiftY?: number;
  occlusionShiftZ?: number;
  activeToothIndex?: number;
  measurementStage?: "landmarks" | "arch";
  archModeJaw?: JawKey;
  archPoints?: Partial<Record<JawKey, LandmarkPoint[]>>;
  archDraft?: LandmarkPoint | null;
  archLengths?: Partial<Record<JawKey, number | null>>;
}

export interface AnalyzePayload {
  mode: AnalysisMode;
  measurements: Record<number, number>;
}
