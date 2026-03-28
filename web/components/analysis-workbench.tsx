"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Calculator, ChevronRight, Search, SmilePlus, Trash2 } from "lucide-react";

import { ArchCard } from "@/components/arch-card";
import { MeshUploadCard } from "@/components/mesh-upload-card";
import { ResultCard } from "@/components/result-card";
import { SessionToolbar } from "@/components/session-toolbar";
import { StlViewport } from "@/components/stl-viewport";
import { StickyCalculateBar } from "@/components/sticky-calculate-bar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { analyzeBolton, checkApiHealth, createOcclusionSession, createPatient, deleteRecord, downloadExport, inspectMesh, listPatients, listRecords, resolveOcclusionShift, saveRecord } from "@/lib/api";
import { AnalysisMode, JawKey, TOOTH_GROUPS, normalizeAnalysisMode, visibleTeethFor } from "@/lib/tooth-config";
import { BoltonResult, LandmarkPoint, MeasurementsState, MeshInfo, SessionEmbeddedFile, SessionPayload } from "@/lib/types";

const INITIAL_VALUES: MeasurementsState = {};
const SESSION_STORAGE_KEY = "selcukbolt-web-session";
type LandmarkPhase = "mesial" | "distal";

function sanitizeMeasurementInput(rawValue: string) {
  let normalized = rawValue.replace(",", ".").replace(/[^0-9.]/g, "");
  const firstDot = normalized.indexOf(".");
  if (firstDot !== -1) {
    normalized =
      normalized.slice(0, firstDot + 1) + normalized.slice(firstDot + 1).replace(/\./g, "");
  }
  return normalized;
}

function toNumericMeasurements(mode: AnalysisMode, values: MeasurementsState): Record<number, number> {
  return visibleTeethFor(normalizeAnalysisMode(mode)).reduce<Record<number, number>>((accumulator, tooth) => {
    const numericValue = Number.parseFloat(values[tooth]?.replace(",", ".") ?? "");
    if (Number.isFinite(numericValue)) {
      accumulator[tooth] = numericValue;
    }
    return accumulator;
  }, {});
}

function fallbackMeshInfo(file: File): MeshInfo {
  return {
    file_name: file.name,
    point_count: 0,
    face_count: 0,
    width_mm: 0,
    height_mm: 0,
    depth_mm: 0,
    center: [0, 0, 0],
  };
}

function fallbackMeshInfoFromName(fileName: string): MeshInfo {
  return {
    file_name: fileName,
    point_count: 0,
    face_count: 0,
    width_mm: 0,
    height_mm: 0,
    depth_mm: 0,
    center: [0, 0, 0],
  };
}

export function AnalysisWorkbench() {
  const [mode, setMode] = useState<AnalysisMode>("anterior");
  const [values, setValues] = useState<MeasurementsState>(INITIAL_VALUES);
  const [result, setResult] = useState<BoltonResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [maxillaInfo, setMaxillaInfo] = useState<MeshInfo | null>(null);
  const [mandibleInfo, setMandibleInfo] = useState<MeshInfo | null>(null);
  const [loadingJaw, setLoadingJaw] = useState<JawKey | null>(null);
  const [maxillaFile, setMaxillaFile] = useState<File | null>(null);
  const [mandibleFile, setMandibleFile] = useState<File | null>(null);
  const [activeViewerJaw, setActiveViewerJaw] = useState<"maxillary" | "mandibular" | "occlusion">("maxillary");
  const [landmarks, setLandmarks] = useState<LandmarkPoint[]>([]);
  const [landmarkDraft, setLandmarkDraft] = useState<LandmarkPoint | null>(null);
  const [landmarkPhase, setLandmarkPhase] = useState<LandmarkPhase>("mesial");
  const [patients, setPatients] = useState<Array<{ id: number; name: string; patient_code?: string }>>([]);
  const [records, setRecords] = useState<Array<{ id: number; title: string; patient_name: string; payload: SessionPayload }>>([]);
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [recordTitle, setRecordTitle] = useState("Yeni Bolton Kaydi");
  const [patientName, setPatientName] = useState("");
  const [patientSearch, setPatientSearch] = useState("");
  const [recordSearch, setRecordSearch] = useState("");
  const [cameraPreset, setCameraPreset] = useState<"occlusal" | "frontal" | "lateral">("occlusal");
  const [jawGap, setJawGap] = useState(0);
  const [occlusionShiftX, setOcclusionShiftX] = useState(0);
  const [occlusionShiftY, setOcclusionShiftY] = useState(0);
  const [occlusionShiftZ, setOcclusionShiftZ] = useState(0);
  const [occlusionControlX, setOcclusionControlX] = useState(0);
  const [occlusionControlY, setOcclusionControlY] = useState(0);
  const [occlusionControlZ, setOcclusionControlZ] = useState(0);
  const [isResolvingOcclusion, setIsResolvingOcclusion] = useState(false);
  const [activeToothIndex, setActiveToothIndex] = useState(0);
  const [editingRecordId, setEditingRecordId] = useState<number | null>(null);
  const [backendAvailable, setBackendAvailable] = useState<boolean | null>(null);

  const inputRefs = useRef<Record<number, HTMLInputElement | null>>({});
  const loadSessionInputRef = useRef<HTMLInputElement | null>(null);
  const safeOcclusionShiftRef = useRef({ x: 0, y: 0, z: 0 });
  const occlusionSessionIdRef = useRef<string | null>(null);
  const occlusionSessionSignatureRef = useRef<string>("");
  const safeMode = useMemo(() => normalizeAnalysisMode(mode), [mode]);
  const orderedTeeth = useMemo(() => visibleTeethFor(safeMode), [safeMode]);

  useEffect(() => {
    setResult(null);
    setErrorMessage(null);
  }, [safeMode]);

  useEffect(() => {
    let cancelled = false;
    void checkApiHealth().then((healthy) => {
      if (!cancelled) {
        setBackendAvailable(healthy);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const draft = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!draft) {
      return;
    }
    try {
      applySession(JSON.parse(draft));
    } catch {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    const payload: SessionPayload = {
      saved_at: new Date().toISOString(),
      mode: safeMode,
      values,
      result,
      maxillaInfo,
      mandibleInfo,
      activeViewerJaw,
      maxillaFile: null,
      mandibleFile: null,
      landmarks,
      landmarkDraft,
      landmarkPhase,
      cameraPreset,
      jawGap,
      occlusionShiftX,
      occlusionShiftY,
      occlusionShiftZ,
      activeToothIndex,
    };
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(payload));
  }, [activeToothIndex, activeViewerJaw, cameraPreset, jawGap, landmarkDraft, landmarkPhase, landmarks, mandibleInfo, maxillaInfo, occlusionShiftX, occlusionShiftY, occlusionShiftZ, result, safeMode, values]);

  const isComplete = orderedTeeth.every((tooth) => {
    const parsed = Number.parseFloat(values[tooth]?.replace(",", ".") ?? "");
    return Number.isFinite(parsed) && parsed > 0;
  });

  const handleValueChange = (tooth: number, rawValue: string) => {
    const nextValue = sanitizeMeasurementInput(rawValue);
    setValues((current) => ({ ...current, [tooth]: nextValue }));
    const toothIndex = orderedTeeth.indexOf(tooth);
    if (toothIndex >= 0) {
      setActiveToothIndex(toothIndex);
    }
  };

  const handleAdvance = (tooth: number) => {
    const currentIndex = orderedTeeth.indexOf(tooth);
    const nextTooth = orderedTeeth[currentIndex + 1];
    if (nextTooth) {
      inputRefs.current[nextTooth]?.focus();
      inputRefs.current[nextTooth]?.select();
    }
  };

  const handleCalculate = async () => {
    if (backendAvailable === false) {
      setErrorMessage("Backend baglantisi yok. Hesaplama icin FastAPI servisini baslatin.");
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const analysisResult = await analyzeBolton(safeMode, toNumericMeasurements(safeMode, values));
      setResult(analysisResult);
    } catch (error) {
      setResult(null);
      setErrorMessage(error instanceof Error ? error.message : "Analiz tamamlanamadi.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMeshUpload = async (jaw: JawKey, file: File) => {
    setLoadingJaw(jaw);
    setErrorMessage(null);
    occlusionSessionIdRef.current = null;
    occlusionSessionSignatureRef.current = "";
    if (jaw === "maxillary") {
      setMaxillaFile(file);
      setMaxillaInfo((current) => current ?? fallbackMeshInfo(file));
      setActiveViewerJaw((current) => (current === "mandibular" && mandibleFile ? current : "maxillary"));
    } else {
      setMandibleFile(file);
      setMandibleInfo((current) => current ?? fallbackMeshInfo(file));
      setActiveViewerJaw((current) => (current === "maxillary" && maxillaFile ? current : "mandibular"));
    }
    try {
      if (backendAvailable === false) {
        return;
      }
      const info = await inspectMesh(file);
      if (jaw === "maxillary") {
        setMaxillaInfo(info);
      } else {
        setMandibleInfo(info);
      }
    } catch (error) {
      if (error instanceof TypeError) {
        setBackendAvailable(false);
      }
      setErrorMessage(
        error instanceof Error
          ? `${jaw === "maxillary" ? "Maksilla" : "Mandibula"} yuklendi, ancak mesh analizi su an alinamadi: ${error.message}`
          : "STL yuklendi, ancak mesh bilgisi okunamadi.",
      );
    } finally {
      setLoadingJaw(null);
    }
  };

  const buildSession = (): SessionPayload => ({
    saved_at: new Date().toISOString(),
    mode: safeMode,
    values,
    result,
    maxillaInfo,
    mandibleInfo,
    activeViewerJaw,
    maxillaFile: null,
    mandibleFile: null,
    landmarks,
    landmarkDraft,
    landmarkPhase,
    cameraPreset,
    jawGap,
    occlusionShiftX,
    occlusionShiftY,
    occlusionShiftZ,
    activeToothIndex,
  });

  const resolveOcclusionTarget = useCallback((targetX: number, targetY: number, targetZ: number) => {
    setIsResolvingOcclusion(false);
    setOcclusionShiftX(targetX);
    setOcclusionShiftY(targetY);
    setOcclusionShiftZ(targetZ);
    setOcclusionControlX(targetX);
    setOcclusionControlY(targetY);
    setOcclusionControlZ(targetZ);
    safeOcclusionShiftRef.current = {
      x: targetX,
      y: targetY,
      z: targetZ,
    };
  }, []);

  const ensureOcclusionSession = useCallback(async () => {
    if (!maxillaFile || !mandibleFile || backendAvailable === false) {
      return null;
    }
    const signature = `${maxillaFile.name}:${maxillaFile.size}:${mandibleFile.name}:${mandibleFile.size}`;
    if (occlusionSessionIdRef.current && occlusionSessionSignatureRef.current === signature) {
      return occlusionSessionIdRef.current;
    }
    const session = await createOcclusionSession({ maxillaFile, mandibleFile });
    occlusionSessionIdRef.current = session.session_id;
    occlusionSessionSignatureRef.current = signature;
    return session.session_id;
  }, [backendAvailable, mandibleFile, maxillaFile]);

  const updateOcclusionShift = useCallback(
    (axis: "x" | "y" | "z", nextValue: number) => {
      const targetX = axis === "x" ? nextValue : occlusionControlX;
      const targetY = axis === "y" ? nextValue : occlusionControlY;
      const targetZ = axis === "z" ? nextValue : occlusionControlZ;

      setOcclusionControlX(targetX);
      setOcclusionControlY(targetY);
      setOcclusionControlZ(targetZ);

      setOcclusionShiftX(targetX);
      setOcclusionShiftY(targetY);
      setOcclusionShiftZ(targetZ);
      safeOcclusionShiftRef.current = { x: targetX, y: targetY, z: targetZ };
    },
    [
      occlusionControlX,
      occlusionControlY,
      occlusionControlZ,
    ],
  );

  const commitOcclusionShift = useCallback(async () => {
    if (!maxillaFile || !mandibleFile || backendAvailable === false) {
      resolveOcclusionTarget(occlusionControlX, occlusionControlY, occlusionControlZ);
      return;
    }

    setIsResolvingOcclusion(true);
    try {
      const sessionId = await ensureOcclusionSession();
      if (!sessionId) {
        resolveOcclusionTarget(occlusionControlX, occlusionControlY, occlusionControlZ);
        return;
      }

      const current = safeOcclusionShiftRef.current;
      const response = await resolveOcclusionShift({
        sessionId,
        currentX: current.x,
        currentY: current.y,
        currentZ: current.z,
        targetX: occlusionControlX,
        targetY: occlusionControlY,
        targetZ: occlusionControlZ,
      });
      resolveOcclusionTarget(response.applied_x, response.applied_y, occlusionControlZ + response.applied_z);
    } catch (error) {
      if (error instanceof TypeError) {
        setBackendAvailable(false);
      }
      setErrorMessage(error instanceof Error ? error.message : "Kapanis duzeltmesi tamamlanamadi.");
      resolveOcclusionTarget(occlusionControlX, occlusionControlY, occlusionControlZ);
    } finally {
      setIsResolvingOcclusion(false);
    }
  }, [
    backendAvailable,
    ensureOcclusionSession,
    mandibleFile,
    maxillaFile,
    occlusionControlX,
    occlusionControlY,
    occlusionControlZ,
    resolveOcclusionTarget,
  ]);

  const applySession = (rawSession: unknown) => {
    const session = normalizeSessionPayload(rawSession);
    setMode(session.mode);
    setValues(session.values);
    setResult(session.result);
    setMaxillaInfo(session.maxillaInfo);
    setMandibleInfo(session.mandibleInfo);
    setActiveViewerJaw(session.activeViewerJaw);
    setLandmarks(session.landmarks);
    setLandmarkDraft(session.landmarkDraft ?? null);
    setLandmarkPhase(session.landmarkPhase ?? "mesial");
    setCameraPreset(session.cameraPreset ?? "occlusal");
    setJawGap(session.jawGap ?? 0);
    setOcclusionShiftX(session.occlusionShiftX ?? 0);
    setOcclusionShiftY(session.occlusionShiftY ?? 0);
    setOcclusionShiftZ(0);
    setOcclusionControlX(session.occlusionShiftX ?? 0);
    setOcclusionControlY(session.occlusionShiftY ?? 0);
    setOcclusionControlZ(session.occlusionShiftZ ?? 0);
    safeOcclusionShiftRef.current = {
      x: session.occlusionShiftX ?? 0,
      y: session.occlusionShiftY ?? 0,
      z: session.occlusionShiftZ ?? 0,
    };
    setActiveToothIndex(session.activeToothIndex ?? 0);
    setErrorMessage(null);
    if (session.maxillaFile) {
      void restoreFileFromEmbedded(session.maxillaFile).then(setMaxillaFile);
    } else {
      setMaxillaFile(null);
    }
    if (session.mandibleFile) {
      void restoreFileFromEmbedded(session.mandibleFile).then(setMandibleFile);
    } else {
      setMandibleFile(null);
    }
    occlusionSessionIdRef.current = null;
    occlusionSessionSignatureRef.current = "";
  };

  const saveSessionToDisk = async () => {
    const blob = new Blob([JSON.stringify(await buildSessionWithEmbeddedFiles(), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `selcukbolt_session_${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const loadSessionFromDisk = () => {
    loadSessionInputRef.current?.click();
  };

  const onSessionFilePicked = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as Record<string, unknown>;
      applySession(parsed);
      const hasEmbeddedStl = Boolean(
        (parsed.maxillaFile || parsed.maxilla_file) &&
        (parsed.mandibleFile || parsed.mandible_file),
      );
      const hasDesktopPaths = typeof parsed.maxilla_path === "string" || typeof parsed.mandible_path === "string";
      if (!hasEmbeddedStl && hasDesktopPaths) {
        setErrorMessage("Oturum olcumleri yuklendi. STL dosyalari guvenlik nedeniyle otomatik acilamadi; maksilla ve mandibula STL dosyalarini yeniden secin.");
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? `Oturum dosyasi okunamadi: ${error.message}` : "Oturum dosyasi okunamadi.");
    } finally {
      event.target.value = "";
    }
  };

  const triggerExport = async (format: "csv" | "json" | "pdf" | "excel") => {
    if (backendAvailable === false) {
      setErrorMessage("Disa aktarma icin backend servisi gerekli.");
      return;
    }
    try {
      const blob = await downloadExport(format, {
        measurements: toNumericMeasurements(safeMode, values),
        patient_id: "Web Hasta",
        report_date: new Date().toLocaleDateString("tr-TR"),
        maxilla_filename: maxillaInfo?.file_name ?? "",
        mandible_filename: mandibleInfo?.file_name ?? "",
        treatment_notes: "SelcukBolt web arayuzunden olusturuldu.",
        template_path: "",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `selcukbolt_export.${format === "excel" ? "xlsx" : format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Disa aktarma tamamlanamadi.");
    }
  };

  const registerInputRef = (tooth: number, element: HTMLInputElement | null) => {
    inputRefs.current[tooth] = element;
  };

  const setActiveTooth = (tooth: number) => {
    const toothIndex = orderedTeeth.indexOf(tooth);
    if (toothIndex >= 0) {
      setActiveToothIndex(toothIndex);
    }
  };

  const syncMeasurementFromLandmarks = (tooth: number, nextLandmarks: LandmarkPoint[]) => {
    const toothPoints = nextLandmarks.filter((item) => item.label.startsWith(`${tooth} `));
    if (toothPoints.length >= 2) {
      const distance = euclideanDistance(toothPoints[0].position, toothPoints[1].position);
      const normalized = distance.toFixed(2);
      setValues((current) => ({ ...current, [tooth]: normalized }));
    } else {
      setValues((current) => {
        const next = { ...current };
        delete next[tooth];
        return next;
      });
    }
  };

  const confirmLandmark = useCallback(() => {
    if (!landmarkDraft) {
      return;
    }

    const confirmedLandmark: LandmarkPoint = {
      ...landmarkDraft,
      id: `${landmarkDraft.id}-confirmed`,
    };

    setLandmarks((current) => {
      const next = [...current, confirmedLandmark];
      const tooth = Number.parseInt(confirmedLandmark.label.split(" ")[0] ?? "", 10);
      if (Number.isFinite(tooth)) {
        syncMeasurementFromLandmarks(tooth, next);
      }
      return next;
    });

    setLandmarkDraft(null);
    setLandmarkPhase((currentPhase) => {
      if (currentPhase === "mesial") {
        return "distal";
      }
      setActiveToothIndex((currentIndex) =>
        currentIndex < orderedTeeth.length - 1 ? currentIndex + 1 : currentIndex,
      );
      return "mesial";
    });
  }, [landmarkDraft, orderedTeeth.length]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!landmarkDraft) {
        return;
      }
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        confirmLandmark();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [confirmLandmark, landmarkDraft]);

  const addLandmark = (jaw: "maxillary" | "mandibular", point: [number, number, number]) => {
    const targetTooth = orderedTeeth[Math.min(activeToothIndex, orderedTeeth.length - 1)] ?? orderedTeeth[0];
    const pointLabel = landmarkPhase === "mesial" ? "M" : "D";
    setLandmarkDraft({
      id: `${jaw}-${targetTooth}-${landmarkPhase}-${Date.now()}`,
      jaw,
      label: `${targetTooth} ${pointLabel}`,
      position: point,
      coordinateSpace: "world",
    });
  };

  const undoLandmark = () => {
    if (landmarkDraft) {
      setLandmarkDraft(null);
      return;
    }

    setLandmarks((current) => {
      const removed = current[current.length - 1];
      const next = current.slice(0, -1);
      if (removed) {
        const tooth = Number.parseInt(removed.label.split(" ")[0] ?? "", 10);
        if (Number.isFinite(tooth)) {
          syncMeasurementFromLandmarks(tooth, next);
          const toothIndex = orderedTeeth.indexOf(tooth);
          if (toothIndex >= 0) {
            setActiveToothIndex(toothIndex);
          }
          setLandmarkPhase(removed.label.endsWith("M") ? "mesial" : "distal");
        }
      }
      return next;
    });
  };

  const clearLandmarks = () => {
    setLandmarks([]);
    setLandmarkDraft(null);
    setLandmarkPhase("mesial");
    setValues((current) => {
      const next = { ...current };
      for (const tooth of orderedTeeth) {
        delete next[tooth];
      }
      return next;
    });
    setActiveToothIndex(0);
  };

  const refreshPatients = useCallback(async () => {
    if (backendAvailable === false) {
      setPatients([]);
      return;
    }
    try {
      const payload = await listPatients(patientSearch);
      setPatients(payload);
      if (!selectedPatientId && payload.length > 0) {
        setSelectedPatientId(payload[0].id);
      }
    } catch (error) {
      if (error instanceof TypeError) {
        setBackendAvailable(false);
      }
    }
  }, [backendAvailable, patientSearch, selectedPatientId]);

  const refreshRecords = useCallback(async (patientId?: number) => {
    if (backendAvailable === false) {
      setRecords([]);
      return;
    }
    try {
      const payload = await listRecords(patientId, recordSearch);
      setRecords(payload);
    } catch (error) {
      if (error instanceof TypeError) {
        setBackendAvailable(false);
      }
    }
  }, [backendAvailable, recordSearch]);

  useEffect(() => {
    if (backendAvailable === null) {
      return;
    }
    void refreshPatients();
    void refreshRecords();
  }, [backendAvailable, refreshPatients, refreshRecords]);

  const handleCreatePatient = async () => {
    if (backendAvailable === false) {
      setErrorMessage("Hasta kaydi icin backend baglantisi gerekli.");
      return;
    }
    if (!patientName.trim()) {
      setErrorMessage("Hasta adi gerekli.");
      return;
    }
    try {
      const patient = await createPatient({ name: patientName });
      setPatientName("");
      setSelectedPatientId(patient.id);
      await refreshPatients();
      await refreshRecords(patient.id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Hasta olusturulamadi.");
    }
  };

  const handleSaveRecord = async () => {
    if (backendAvailable === false) {
      setErrorMessage("Kayit saklamak icin backend baglantisi gerekli.");
      return;
    }
    if (!selectedPatientId) {
      setErrorMessage("Kayit icin once hasta secin.");
      return;
    }
    try {
      await saveRecord({
        patient_id: selectedPatientId,
        title: recordTitle,
        analysis_mode: mode,
        payload: await buildSessionWithEmbeddedFiles(),
        record_id: editingRecordId,
      });
      setEditingRecordId(null);
      await refreshRecords(selectedPatientId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Kayit saklanamadi.");
    }
  };

  const handleLoadRecord = (payload: SessionPayload, recordId?: number, title?: string) => {
    applySession(payload);
    setEditingRecordId(recordId ?? null);
    if (title) {
      setRecordTitle(title);
    }
  };

  const handleDeleteRecord = async (recordId: number) => {
    if (backendAvailable === false) {
      setErrorMessage("Kayit silmek icin backend baglantisi gerekli.");
      return;
    }
    try {
      await deleteRecord(recordId);
      await refreshRecords(selectedPatientId ?? undefined);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Kayit silinemedi.");
    }
  };

  const buildSessionWithEmbeddedFiles = async (): Promise<SessionPayload> => ({
    ...buildSession(),
    maxillaFile: await fileToEmbeddedPayload(maxillaFile),
    mandibleFile: await fileToEmbeddedPayload(mandibleFile),
  });

  const renderArchCard = (jaw: JawKey) => (
    <ArchCard
      jaw={jaw}
      teeth={TOOTH_GROUPS[safeMode][jaw]}
      values={values}
      onValueChange={handleValueChange}
      onFieldEnter={handleAdvance}
      registerInputRef={registerInputRef}
      activeTooth={orderedTeeth[Math.min(activeToothIndex, orderedTeeth.length - 1)] ?? null}
      onActivateTooth={setActiveTooth}
    />
  );

  return (
    <div className="pb-28" data-selcukbolt-shell>
      <div className="container py-4 xl:py-6">
        <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.55fr)_400px]" data-selcukbolt-grid>
          <div className="space-y-6">
            <Card className="overflow-hidden" data-selcukbolt-card>
              <CardHeader className="gap-3 border-b border-slate-100 bg-white/80 pb-4 backdrop-blur">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.28em] text-blue-600">
                        <SmilePlus className="h-3.5 w-3.5" />
                        SelcukBolt
                      </div>
                      <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600">
                        <Activity className="h-3.5 w-3.5 text-blue-600" />
                        {backendAvailable === false ? "Local Mod" : "Canli Baglanti"}
                      </div>
                    </div>
                    <CardTitle className="text-xl md:text-2xl">Bolton analizi</CardTitle>
                    <CardDescription className="max-w-2xl text-sm leading-6">
                      STL yukle, noktayi isaretle, olcumleri kontrol et ve sonucu kaydet.
                    </CardDescription>
                  </div>

                  <SessionToolbar
                    onLoadSession={loadSessionFromDisk}
                    onSaveSession={saveSessionToDisk}
                    onExportCsv={() => triggerExport("csv")}
                    onExportJson={() => triggerExport("json")}
                    onExportExcel={() => triggerExport("excel")}
                    onExportPdf={() => triggerExport("pdf")}
                    exportDisabled={!isComplete || backendAvailable === false}
                  />
                </div>

                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <Tabs value={safeMode} onValueChange={(nextValue) => setMode(normalizeAnalysisMode(nextValue))}>
                    <TabsList>
                      <TabsTrigger value="anterior">Anterior (6 Dis)</TabsTrigger>
                      <TabsTrigger value="overall">Total (12 Dis)</TabsTrigger>
                    </TabsList>
                    <TabsContent value={safeMode} className="mt-0" />
                  </Tabs>

                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    {backendAvailable === false
                      ? "Lokal goruntuleme acik. Hesaplama ve kayit icin backend gerekli."
                      : "Backend hazir. STL analizi ve kayit islemleri aktif."}
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-5 pt-5">
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
                  <div className="space-y-4">
                    <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 shadow-sm lg:grid-cols-[auto_auto_minmax(180px,220px)_1fr] lg:items-center" data-selcukbolt-panel>
                      <div className="space-y-1">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-500">Gorunum</p>
                        <div className="flex flex-wrap gap-2">
                          <Button variant={activeViewerJaw === "maxillary" ? "default" : "outline"} size="sm" onClick={() => setActiveViewerJaw("maxillary")}>
                            Maksilla
                          </Button>
                          <Button variant={activeViewerJaw === "mandibular" ? "default" : "outline"} size="sm" onClick={() => setActiveViewerJaw("mandibular")}>
                            Mandibula
                          </Button>
                          <Button variant={activeViewerJaw === "occlusion" ? "default" : "outline"} size="sm" onClick={() => setActiveViewerJaw("occlusion")}>
                            Kapanis
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-1">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-500">Kamera</p>
                        <div className="flex flex-wrap gap-2">
                          <Button variant={cameraPreset === "occlusal" ? "default" : "outline"} size="sm" onClick={() => setCameraPreset("occlusal")}>
                            Okluzal
                          </Button>
                          <Button variant={cameraPreset === "frontal" ? "default" : "outline"} size="sm" onClick={() => setCameraPreset("frontal")}>
                            Frontal
                          </Button>
                          <Button variant={cameraPreset === "lateral" ? "default" : "outline"} size="sm" onClick={() => setCameraPreset("lateral")}>
                            Lateral
                          </Button>
                        </div>
                      </div>

                      {activeViewerJaw !== "occlusion" ? (
                        <>
                          <div>
                            <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-500">Aktif Landmark</p>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-700">
                              <span>
                                Dis <span className="font-semibold">{orderedTeeth[Math.min(activeToothIndex, orderedTeeth.length - 1)] ?? "—"}</span>
                              </span>
                              <span className="rounded-full bg-blue-100 px-2 py-1 text-xs font-medium text-blue-700">
                                {landmarkPhase === "mesial" ? "Mesial" : "Distal"}
                              </span>
                            </div>
                          </div>

                          <div className="lg:col-span-4 flex justify-end">
                            <Button size="sm" variant="outline" onClick={confirmLandmark} disabled={!landmarkDraft} className="min-w-[132px]">
                              Noktayi Onayla
                            </Button>
                          </div>
                        </>
                      ) : null}
                    </div>

                    <StlViewport
                      mode={activeViewerJaw}
                      maxillaFile={maxillaFile}
                      mandibleFile={mandibleFile}
                      maxillaInfo={maxillaInfo}
                      mandibleInfo={mandibleInfo}
                      landmarks={landmarks}
                      landmarkDraft={landmarkDraft}
                      onAddLandmark={addLandmark}
                      onConfirmLandmark={confirmLandmark}
                      onUndoLandmark={undoLandmark}
                      onClearLandmarks={clearLandmarks}
                      cameraPreset={cameraPreset}
                      occlusionShiftX={occlusionShiftX}
                      occlusionShiftY={occlusionShiftY}
                      occlusionShiftZ={occlusionShiftZ}
                      occlusionControlX={occlusionControlX}
                      occlusionControlY={occlusionControlY}
                      occlusionControlZ={occlusionControlZ}
                      onOcclusionShiftXChange={(value) => void updateOcclusionShift("x", value)}
                      onOcclusionShiftYChange={(value) => void updateOcclusionShift("y", value)}
                      onOcclusionShiftZChange={(value) => void updateOcclusionShift("z", value)}
                      onOcclusionShiftCommit={commitOcclusionShift}
                      isResolvingOcclusion={isResolvingOcclusion}
                      landmarkPhase={landmarkPhase}
                    />
                  </div>

                  <div className="space-y-4">
                    <MeshUploadCard
                      title="Maksilla STL"
                      info={maxillaInfo}
                      isLoading={loadingJaw === "maxillary"}
                      onFileSelected={(file) => handleMeshUpload("maxillary", file)}
                    />
                    <MeshUploadCard
                      title="Mandibula STL"
                      info={mandibleInfo}
                      isLoading={loadingJaw === "mandibular"}
                      onFileSelected={(file) => handleMeshUpload("mandibular", file)}
                    />
                  </div>
                </div>

                <div className="grid gap-5 xl:grid-cols-2" data-selcukbolt-grid>
                  {renderArchCard("maxillary")}
                  {renderArchCard("mandibular")}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-5 xl:sticky xl:top-6 xl:self-start">
            <Card className="shadow-sm" data-selcukbolt-card>
              <CardHeader className="pb-4">
                <CardTitle className="text-lg">Hasta ve Kayitlar</CardTitle>
                <CardDescription>
                  Calisma sirasinda hastayi secin, kaydi adlandirin ve tek yerden yukleyip saklayin.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-2">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      className="w-full rounded-xl border border-slate-200 px-9 py-2 text-sm"
                      placeholder="Hasta ara"
                      value={patientSearch}
                      onChange={(event) => setPatientSearch(event.target.value)}
                    />
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    <input
                      className="w-full rounded-xl border border-slate-200 px-4 py-2 text-sm"
                      placeholder="Yeni hasta adi"
                      value={patientName}
                      onChange={(event) => setPatientName(event.target.value)}
                    />
                    <Button variant="outline" onClick={handleCreatePatient} className="sm:min-w-[110px]" disabled={backendAvailable === false}>
                      Hasta Ekle
                    </Button>
                  </div>
                </div>
                <div className="grid gap-2">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      className="w-full rounded-xl border border-slate-200 px-9 py-2 text-sm"
                      placeholder="Kayit ara"
                      value={recordSearch}
                      onChange={(event) => {
                        setRecordSearch(event.target.value);
                        void refreshRecords(selectedPatientId ?? undefined);
                      }}
                    />
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    <select
                      className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm"
                      value={selectedPatientId ?? ""}
                      onChange={(event) => {
                        const nextId = Number(event.target.value);
                        setSelectedPatientId(nextId);
                        void refreshRecords(nextId);
                      }}
                    >
                      <option value="">Hasta sec</option>
                      {patients.map((patient) => (
                        <option key={patient.id} value={patient.id}>
                          {patient.name}
                        </option>
                      ))}
                    </select>
                    <Button onClick={handleSaveRecord} className="sm:min-w-[110px]" disabled={backendAvailable === false}>
                      Kaydi Sakla
                    </Button>
                  </div>
                </div>
                <input
                  className="w-full rounded-xl border border-slate-200 px-4 py-2 text-sm"
                  value={recordTitle}
                  onChange={(event) => setRecordTitle(event.target.value)}
                  placeholder="Kayit basligi"
                />
                {editingRecordId ? (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                    Duzenleme modu aktif. Kaydet butonu mevcut kaydi gunceller.
                  </div>
                ) : null}
                <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                  {records.length === 0 ? (
                    <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-500">Kayit bulunmuyor.</div>
                  ) : (
                    records.map((record) => (
                      <div
                        key={record.id}
                        className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm hover:border-blue-300"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <button type="button" onClick={() => handleLoadRecord(record.payload, record.id, record.title)} className="min-w-0 flex-1 text-left">
                            <div className="text-sm font-semibold text-slate-900">{record.title}</div>
                            <div className="mt-1 text-xs text-slate-500">{record.patient_name}</div>
                          </button>
                          <Button variant="outline" size="sm" onClick={() => handleDeleteRecord(record.id)} disabled={backendAvailable === false}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>

            <div data-selcukbolt-card>
              <ResultCard result={result} />
            </div>

            <Card data-selcukbolt-card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Calculator className="h-5 w-5 text-blue-600" />
                  Klinik Kontrol Listesi
                </CardTitle>
                <CardDescription>Yeni web akisi mevcut masaustu mantigiyla ayni sonucu uretmelidir.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 text-sm text-slate-600">
                <ChecklistItem text="Sadece rakam ve ondalik ayirici kabul edilir." />
                <ChecklistItem text="Enter ile bir sonraki anatomik alana odak gecilir." />
                <ChecklistItem text="Kart altinda jaw toplam genisligi canli guncellenir." />
                <ChecklistItem text="Hesapla butonu tum zorunlu disler dolmadan aktif olmaz." />
                <ChecklistItem text="Arka planda eski Python Bolton formulleri kullanilir." />
              </CardContent>
            </Card>

            {errorMessage ? (
              <Card className="border-rose-200 bg-rose-50" data-selcukbolt-card>
                <CardContent className="pt-6">
                  <p className="text-sm font-medium text-rose-700">{errorMessage}</p>
                </CardContent>
              </Card>
            ) : null}
          </div>
        </div>
      </div>

      <StickyCalculateBar
        disabled={!isComplete || backendAvailable === false}
        pending={isSubmitting}
        modeLabel={safeMode === "anterior" ? "Anterior" : "Total"}
        onCalculate={handleCalculate}
      />

      <input
        ref={loadSessionInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={onSessionFilePicked}
      />
    </div>
  );
}

async function fileToEmbeddedPayload(file: File | null): Promise<SessionEmbeddedFile | null> {
  if (!file) {
    return null;
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  return {
    name: file.name,
    type: file.type || "model/stl",
    dataUrl,
  };
}

function normalizeEmbeddedFile(rawFile: unknown): SessionEmbeddedFile | null {
  if (!rawFile || typeof rawFile !== "object") {
    return null;
  }

  const candidate = rawFile as {
    name?: unknown;
    type?: unknown;
    dataUrl?: unknown;
    data_url?: unknown;
  };
  const dataUrl = candidate.dataUrl ?? candidate.data_url;
  if (typeof candidate.name !== "string" || typeof dataUrl !== "string") {
    return null;
  }

  return {
    name: candidate.name,
    type: typeof candidate.type === "string" ? candidate.type : "model/stl",
    dataUrl,
  };
}

function normalizeLandmarks(rawLandmarks: unknown): LandmarkPoint[] {
  if (!Array.isArray(rawLandmarks)) {
    return [];
  }

  return rawLandmarks.flatMap((item, index) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const candidate = item as {
      id?: unknown;
      jaw?: unknown;
      label?: unknown;
      position?: unknown;
      coordinateSpace?: unknown;
    };
    if (
      (candidate.jaw !== "maxillary" && candidate.jaw !== "mandibular") ||
      typeof candidate.label !== "string" ||
      !Array.isArray(candidate.position) ||
      candidate.position.length !== 3
    ) {
      return [];
    }

    const numericPosition = candidate.position.map((value) => Number(value));
    if (numericPosition.some((value) => !Number.isFinite(value))) {
      return [];
    }

    return [
      {
        id: typeof candidate.id === "string" ? candidate.id : `restored-${index}`,
        jaw: candidate.jaw,
        label: candidate.label,
        position: numericPosition as [number, number, number],
        coordinateSpace: candidate.coordinateSpace === "mesh" ? "mesh" : "world",
      },
    ];
  });
}

function normalizeLandmarkDraft(rawDraft: unknown): LandmarkPoint | null {
  const normalized = normalizeLandmarks(Array.isArray(rawDraft) ? rawDraft : rawDraft ? [rawDraft] : []);
  return normalized[0] ?? null;
}

function normalizeDesktopMeasurementRows(rawRows: unknown): {
  values: MeasurementsState;
  landmarks: LandmarkPoint[];
  mode: AnalysisMode;
} {
  if (!Array.isArray(rawRows)) {
    return { values: {}, landmarks: [], mode: "anterior" };
  }

  const values: MeasurementsState = {};
  const landmarks: LandmarkPoint[] = [];

  rawRows.forEach((item, index) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const row = item as {
      tooth_fdi?: unknown;
      jaw?: unknown;
      mesial_xyz?: unknown;
      distal_xyz?: unknown;
      width_mm?: unknown;
    };
    const tooth = Number(row.tooth_fdi);
    const width = Number(row.width_mm);
    const jaw = row.jaw === "maxillary" || row.jaw === "mandibular" ? row.jaw : null;

    if (Number.isFinite(tooth) && Number.isFinite(width)) {
      values[tooth] = width.toFixed(2);
    }

    if (jaw && Array.isArray(row.mesial_xyz) && row.mesial_xyz.length === 3) {
      const mesial = row.mesial_xyz.map((value) => Number(value));
      if (mesial.every((value) => Number.isFinite(value))) {
        landmarks.push({
          id: `desktop-${index}-mesial`,
          jaw,
          label: `${tooth} M`,
          position: mesial as [number, number, number],
          coordinateSpace: "mesh",
        });
      }
    }

    if (jaw && Array.isArray(row.distal_xyz) && row.distal_xyz.length === 3) {
      const distal = row.distal_xyz.map((value) => Number(value));
      if (distal.every((value) => Number.isFinite(value))) {
        landmarks.push({
          id: `desktop-${index}-distal`,
          jaw,
          label: `${tooth} D`,
          position: distal as [number, number, number],
          coordinateSpace: "mesh",
        });
      }
    }
  });

  const mode: AnalysisMode = rawRows.length > 12 ? "overall" : "anterior";
  return { values, landmarks, mode };
}

function normalizeSessionPayload(rawSession: unknown): SessionPayload {
  const candidate = (rawSession && typeof rawSession === "object" ? rawSession : {}) as Record<string, unknown>;
  const desktopRows = normalizeDesktopMeasurementRows(candidate.measurement_rows);
  const activeViewerJaw =
    candidate.activeViewerJaw === "maxillary" ||
    candidate.activeViewerJaw === "mandibular" ||
    candidate.activeViewerJaw === "occlusion"
      ? candidate.activeViewerJaw
      : "maxillary";
  const cameraPreset =
    candidate.cameraPreset === "occlusal" ||
    candidate.cameraPreset === "frontal" ||
    candidate.cameraPreset === "lateral"
      ? candidate.cameraPreset
      : "occlusal";
  const activeToothIndex = Number(candidate.activeToothIndex);
  const jawGap = Number(candidate.jawGap);
  const occlusionShiftX = Number(candidate.occlusionShiftX ?? candidate.occlusion_shift_x);
  const occlusionShiftY = Number(candidate.occlusionShiftY ?? candidate.occlusion_shift_y);
  const occlusionShiftZ = Number(candidate.occlusionShiftZ ?? candidate.occlusion_shift_z ?? candidate.occlusionShiftY ?? candidate.occlusion_shift_y);

  return {
    saved_at: typeof candidate.saved_at === "string" ? candidate.saved_at : new Date().toISOString(),
    mode: normalizeAnalysisMode(
      typeof candidate.mode === "string"
        ? candidate.mode
        : typeof candidate.analysis_mode === "string"
          ? candidate.analysis_mode
          : desktopRows.mode,
    ),
    values:
      candidate.values && typeof candidate.values === "object"
        ? (candidate.values as MeasurementsState)
        : desktopRows.values,
    result: candidate.result && typeof candidate.result === "object" ? (candidate.result as BoltonResult) : null,
    maxillaInfo:
      candidate.maxillaInfo && typeof candidate.maxillaInfo === "object"
        ? (candidate.maxillaInfo as MeshInfo)
        : typeof candidate.maxilla_filename === "string"
          ? fallbackMeshInfoFromName(candidate.maxilla_filename)
          : null,
    mandibleInfo:
      candidate.mandibleInfo && typeof candidate.mandibleInfo === "object"
        ? (candidate.mandibleInfo as MeshInfo)
        : typeof candidate.mandible_filename === "string"
          ? fallbackMeshInfoFromName(candidate.mandible_filename)
          : null,
    activeViewerJaw,
    maxillaFile: normalizeEmbeddedFile(candidate.maxillaFile ?? candidate.maxilla_file),
    mandibleFile: normalizeEmbeddedFile(candidate.mandibleFile ?? candidate.mandible_file),
    landmarks:
      Array.isArray(candidate.landmarks) && candidate.landmarks.length > 0
        ? normalizeLandmarks(candidate.landmarks)
        : desktopRows.landmarks,
    landmarkDraft: normalizeLandmarkDraft(candidate.landmarkDraft ?? candidate.landmark_draft),
    landmarkPhase:
      candidate.landmarkPhase === "mesial" || candidate.landmarkPhase === "distal"
        ? candidate.landmarkPhase
        : candidate.guided_step === "distal"
          ? "distal"
          : "mesial",
    cameraPreset,
    jawGap: Number.isFinite(jawGap) ? jawGap : 0,
    occlusionShiftX: Number.isFinite(occlusionShiftX) ? occlusionShiftX : 0,
    occlusionShiftY: Number.isFinite(occlusionShiftY) ? occlusionShiftY : 0,
    occlusionShiftZ: Number.isFinite(occlusionShiftZ) ? occlusionShiftZ : 0,
    activeToothIndex: Number.isFinite(activeToothIndex) ? activeToothIndex : 0,
  };
}

async function restoreFileFromEmbedded(file: SessionEmbeddedFile): Promise<File> {
  const response = await fetch(file.dataUrl);
  const blob = await response.blob();
  return new File([blob], file.name, { type: file.type || blob.type });
}

function euclideanDistance(pointA: [number, number, number], pointB: [number, number, number]) {
  const dx = pointB[0] - pointA[0];
  const dy = pointB[1] - pointA[1];
  const dz = pointB[2] - pointA[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function ChecklistItem({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl bg-slate-50 p-3">
      <ChevronRight className="mt-0.5 h-4 w-4 text-blue-600" />
      <span>{text}</span>
    </div>
  );
}
