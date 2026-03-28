"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Box, Layers3, Orbit, Pin, Trash2 } from "lucide-react";
import { Canvas, ThreeEvent, useThree } from "@react-three/fiber";
import { Bounds, Html, Line, OrbitControls } from "@react-three/drei";
import { BufferGeometry, DoubleSide, MOUSE, Matrix4, MeshPhysicalMaterial, TOUCH, Vector3 } from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { LandmarkPoint, MeasurementsState, MeshInfo } from "@/lib/types";

type ViewerMode = "maxillary" | "mandibular" | "occlusion";
type CameraPreset = "occlusal" | "frontal" | "lateral";

interface StlViewportProps {
  mode: ViewerMode;
  maxillaFile: File | null;
  mandibleFile: File | null;
  maxillaInfo?: MeshInfo | null;
  mandibleInfo?: MeshInfo | null;
  currentJawTeeth: number[];
  measurementValues: MeasurementsState;
  activeTooth?: number | null;
  onActivateTooth: (tooth: number) => void;
  onClearTooth: (tooth: number) => void;
  onViewerModeChange: (mode: ViewerMode) => void;
  onCameraPresetChange: (preset: CameraPreset) => void;
  focusMode?: boolean;
  measurementStage: "landmarks" | "arch";
  landmarks: LandmarkPoint[];
  landmarkDraft?: LandmarkPoint | null;
  onAddLandmark: (jaw: "maxillary" | "mandibular", point: [number, number, number]) => void;
  onConfirmLandmark: () => void;
  onUndoLandmark: () => void;
  onClearLandmarks: () => void;
  archModeJaw: "maxillary" | "mandibular";
  archPoints: Record<"maxillary" | "mandibular", LandmarkPoint[]>;
  archDraft?: LandmarkPoint | null;
  archLengths: Record<"maxillary" | "mandibular", number | null>;
  onAddArchPoint: (jaw: "maxillary" | "mandibular", point: [number, number, number]) => void;
  onConfirmArchPoint: () => void;
  onUndoArchPoint: () => void;
  onClearArchPoints: () => void;
  onCompleteArchMeasurement: () => void;
  onArchJawChange: (jaw: "maxillary" | "mandibular") => void;
  cameraPreset: CameraPreset;
  jawGap: number;
  occlusionShiftX: number;
  occlusionShiftY: number;
  occlusionShiftZ: number;
  occlusionControlX: number;
  occlusionControlY: number;
  occlusionControlZ: number;
  onOcclusionShiftXChange: (value: number) => void;
  onOcclusionShiftYChange: (value: number) => void;
  onOcclusionShiftZChange: (value: number) => void;
  onOcclusionShiftCommit: () => void;
  isResolvingOcclusion?: boolean;
  landmarkPhase: "mesial" | "distal";
}

const maxillaMaterial = new MeshPhysicalMaterial({
  color: "#f5efe6",
  roughness: 0.62,
  metalness: 0.01,
  clearcoat: 0.04,
  reflectivity: 0.03,
  sheen: 0.1,
  side: DoubleSide,
});

const mandibleMaterial = new MeshPhysicalMaterial({
  color: "#ece0d1",
  roughness: 0.66,
  metalness: 0.01,
  clearcoat: 0.04,
  reflectivity: 0.03,
  sheen: 0.1,
  side: DoubleSide,
});

function transformMeshPointToWorld(
  point: [number, number, number],
  _meshInfo: MeshInfo | null | undefined,
  offset: [number, number, number],
): [number, number, number] {
  return [
    point[0] + offset[0],
    point[1] + offset[1],
    point[2] + offset[2],
  ];
}

export function StlViewport({
  mode,
  maxillaFile,
  mandibleFile,
  maxillaInfo,
  mandibleInfo,
  currentJawTeeth,
  measurementValues,
  activeTooth,
  onActivateTooth,
  onClearTooth,
  onViewerModeChange,
  onCameraPresetChange,
  focusMode = false,
  measurementStage,
  landmarks,
  landmarkDraft,
  onAddLandmark,
  onConfirmLandmark,
  onUndoLandmark,
  onClearLandmarks,
  archModeJaw,
  archPoints,
  archDraft,
  archLengths,
  onAddArchPoint,
  onConfirmArchPoint,
  onUndoArchPoint,
  onClearArchPoints,
  onCompleteArchMeasurement,
  onArchJawChange,
  cameraPreset,
  jawGap,
  occlusionShiftX,
  occlusionShiftY,
  occlusionShiftZ,
  occlusionControlX,
  occlusionControlY,
  occlusionControlZ,
  onOcclusionShiftXChange,
  onOcclusionShiftYChange,
  onOcclusionShiftZChange,
  onOcclusionShiftCommit,
  isResolvingOcclusion = false,
  landmarkPhase,
}: StlViewportProps) {
  const [resetKey, setResetKey] = useState(0);
  const [navigationMode, setNavigationMode] = useState<"rotate" | "pan">("rotate");
  const hasAnyModel = Boolean(maxillaFile || mandibleFile);
  const landmarkEnabled = measurementStage === "landmarks" && mode !== "occlusion";
  const archEnabled = measurementStage === "arch" && mode !== "occlusion" && mode === archModeJaw;
  const occlusionOffsets = useMemo(() => {
    return {
      maxillary: [0, 0, 0] as [number, number, number],
      mandibular: [occlusionShiftX, occlusionShiftZ - jawGap, occlusionShiftY] as [number, number, number],
    };
  }, [jawGap, occlusionShiftX, occlusionShiftY, occlusionShiftZ]);
  const renderedLandmarks = useMemo(
    () =>
      landmarks.map((landmark) => ({
        ...landmark,
        position:
          landmark.coordinateSpace === "mesh"
            ? transformMeshPointToWorld(
                landmark.position,
                landmark.jaw === "maxillary" ? maxillaInfo : mandibleInfo,
                landmark.jaw === "maxillary"
                  ? mode === "occlusion"
                    ? occlusionOffsets.maxillary
                    : [0, 0, 0]
                  : mode === "occlusion"
                    ? occlusionOffsets.mandibular
                    : [0, 0, 0],
              )
            : landmark.position,
      })),
    [landmarks, mandibleInfo, maxillaInfo, mode, occlusionOffsets],
  );
  const visibleLandmarks = useMemo(
    () => renderedLandmarks.filter((landmark) => mode === "occlusion" || landmark.jaw === mode),
    [mode, renderedLandmarks],
  );
  const visibleLandmarkDraft = useMemo(() => {
    if (!landmarkDraft) {
      return null;
    }
    if (mode !== "occlusion" && landmarkDraft.jaw !== mode) {
      return null;
    }
    return landmarkDraft;
  }, [landmarkDraft, mode]);
  const measurementPairs = useMemo(() => {
    const grouped = new Map<string, LandmarkPoint[]>();
    for (const landmark of visibleLandmarks) {
      const toothKey = landmark.label.split(" ")[0];
      const bucket = grouped.get(toothKey) ?? [];
      bucket.push(landmark);
      grouped.set(toothKey, bucket);
    }
    return Array.from(grouped.entries())
      .map(([tooth, points]) => ({ tooth, points }))
      .filter((item) => item.points.length >= 2);
  }, [visibleLandmarks]);
  const renderedArchPoints = useMemo(
    () =>
      archPoints[mode === "mandibular" ? "mandibular" : "maxillary"]?.map((point) => ({
        ...point,
        position:
          point.coordinateSpace === "mesh"
            ? transformMeshPointToWorld(
                point.position,
                point.jaw === "maxillary" ? maxillaInfo : mandibleInfo,
                point.jaw === "maxillary"
                  ? mode === "occlusion"
                    ? occlusionOffsets.maxillary
                    : [0, 0, 0]
                  : mode === "occlusion"
                    ? occlusionOffsets.mandibular
                    : [0, 0, 0],
              )
            : point.position,
      })) ?? [],
    [archPoints, mandibleInfo, maxillaInfo, mode, occlusionOffsets],
  );
  const activeArchLength = archLengths[archModeJaw];
  const stageInstruction =
    measurementStage === "landmarks"
      ? `Dis ${activeTooth ?? "-"} icin ${landmarkPhase === "mesial" ? "mesial" : "distal"} noktayi secin ve onaylayin.`
      : `${archModeJaw === "maxillary" ? "Maksilla" : "Mandibula"} ark boyunca noktalar yerlestirin. En az 2 nokta ile ark boyunu kaydedin.`;
  const mouseButtons =
    navigationMode === "pan"
      ? {
          LEFT: MOUSE.PAN,
          MIDDLE: MOUSE.DOLLY,
          RIGHT: MOUSE.PAN,
        }
      : {
          LEFT: MOUSE.ROTATE,
          MIDDLE: MOUSE.DOLLY,
          RIGHT: MOUSE.PAN,
        };

  const viewportBody = (
    <div
      className={`relative bg-[#edf1f4] ${
        focusMode
          ? "h-full min-h-0 overflow-hidden rounded-[28px] border border-white/60 shadow-[0_30px_80px_rgba(15,23,42,0.12)]"
          : "h-[520px]"
      }`}
      data-selcukbolt-viewport
    >
          {hasAnyModel ? (
            <Canvas shadows camera={{ position: [0, 0, 120], fov: 30 }} dpr={[1, 1.75]}>
              <color attach="background" args={["#edf1f4"]} />
              <ambientLight intensity={0.24} />
              <hemisphereLight args={["#f3f4f6", "#cbd5db", 0.56]} />
              <directionalLight
                position={[42, 54, 82]}
                intensity={1.45}
                castShadow
                shadow-mapSize-width={2048}
                shadow-mapSize-height={2048}
                shadow-bias={-0.00008}
              />
              <directionalLight position={[-36, 24, 54]} intensity={0.7} color="#dde4ea" />
              <directionalLight position={[0, -36, 32]} intensity={0.46} color="#d7dee5" />
              <directionalLight position={[0, 22, -70]} intensity={0.52} color="#f1f4f6" />
              <Suspense fallback={null}>
                <Bounds fit clip observe margin={1.08}>
                  {mode !== "mandibular" && maxillaFile ? (
                    <SingleStlMesh
                      file={maxillaFile}
                      material={maxillaMaterial}
                      jaw="maxillary"
                      translation={mode === "occlusion" ? occlusionOffsets.maxillary : [0, 0, 0]}
                      pointPickingEnabled={landmarkEnabled || archEnabled}
                      onAddPoint={measurementStage === "landmarks" ? onAddLandmark : onAddArchPoint}
                    />
                  ) : null}
                  {mode !== "maxillary" && mandibleFile ? (
                    <SingleStlMesh
                      file={mandibleFile}
                      material={mandibleMaterial}
                      jaw="mandibular"
                      translation={mode === "occlusion" ? occlusionOffsets.mandibular : [0, 0, 0]}
                      pointPickingEnabled={landmarkEnabled || archEnabled}
                      onAddPoint={measurementStage === "landmarks" ? onAddLandmark : onAddArchPoint}
                    />
                  ) : null}
                  {landmarkEnabled ? visibleLandmarks.map((landmark) => (
                    <group key={landmark.id} position={landmark.position}>
                      <mesh>
                        <sphereGeometry args={[0.22, 18, 18]} />
                        <meshStandardMaterial
                          color={landmark.jaw === "maxillary" ? "#2563eb" : "#16a34a"}
                          roughness={0.35}
                          metalness={0.05}
                        />
                      </mesh>
                      <Html distanceFactor={12}>
                        <div className="rounded-md bg-slate-900/85 px-1.5 py-0.5 text-[8px] font-semibold text-white shadow-sm">
                          {landmark.label}
                        </div>
                      </Html>
                    </group>
                  )) : null}
                  {landmarkEnabled && visibleLandmarkDraft ? (
                    <group position={visibleLandmarkDraft.position}>
                      <mesh>
                        <sphereGeometry args={[0.28, 20, 20]} />
                        <meshStandardMaterial
                          color={visibleLandmarkDraft.jaw === "maxillary" ? "#60a5fa" : "#4ade80"}
                          emissive={visibleLandmarkDraft.jaw === "maxillary" ? "#1d4ed8" : "#15803d"}
                          emissiveIntensity={0.16}
                          roughness={0.28}
                        />
                      </mesh>
                      <Html distanceFactor={12}>
                        <div className="rounded-md border border-blue-200 bg-white/95 px-1.5 py-0.5 text-[8px] font-semibold text-blue-700 shadow-sm">
                          {visibleLandmarkDraft.label}
                        </div>
                      </Html>
                    </group>
                  ) : null}
                  {landmarkEnabled ? measurementPairs.map(({ tooth, points }) => (
                    <Line key={`line-${tooth}`} points={[points[0].position, points[1].position]} color="#f97316" lineWidth={2} />
                  )) : null}
                  {archEnabled ? renderedArchPoints.map((point) => (
                    <group key={point.id} position={point.position}>
                      <mesh>
                        <sphereGeometry args={[0.24, 18, 18]} />
                        <meshStandardMaterial color="#0f766e" roughness={0.3} metalness={0.04} />
                      </mesh>
                      <Html distanceFactor={12}>
                        <div className="rounded-md bg-emerald-900/85 px-1.5 py-0.5 text-[8px] font-semibold text-white shadow-sm">
                          {point.label}
                        </div>
                      </Html>
                    </group>
                  )) : null}
                  {archEnabled && archDraft ? (
                    <group position={archDraft.position}>
                      <mesh>
                        <sphereGeometry args={[0.28, 20, 20]} />
                        <meshStandardMaterial color="#2dd4bf" emissive="#115e59" emissiveIntensity={0.2} roughness={0.26} />
                      </mesh>
                      <Html distanceFactor={12}>
                        <div className="rounded-md border border-emerald-200 bg-white/95 px-1.5 py-0.5 text-[8px] font-semibold text-emerald-700 shadow-sm">
                          {archDraft.label}
                        </div>
                      </Html>
                    </group>
                  ) : null}
                  {archEnabled && renderedArchPoints.length >= 2 ? (
                    <Line points={renderedArchPoints.map((point) => point.position)} color="#14b8a6" lineWidth={2} />
                  ) : null}
                </Bounds>
              </Suspense>
              <CameraDamping preset={cameraPreset} resetKey={resetKey} />
              <OrbitControls
                key={`${cameraPreset}-${resetKey}`}
                makeDefault
                enablePan
                enableRotate
                enableZoom
                enableDamping
                dampingFactor={0.08}
                rotateSpeed={0.72}
                panSpeed={0.9}
                zoomSpeed={0.82}
                minDistance={24}
                maxDistance={260}
                screenSpacePanning
                mouseButtons={mouseButtons}
                touches={{
                  ONE: TOUCH.ROTATE,
                  TWO: TOUCH.DOLLY_PAN,
                }}
              />
            </Canvas>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="rounded-3xl border border-dashed border-slate-300 bg-white/80 px-8 py-10 text-center shadow-sm">
                <Box className="mx-auto h-8 w-8 text-slate-400" />
                <p className="mt-4 text-sm font-semibold text-slate-700">Goruntulemek icin STL yukleyin</p>
                <p className="mt-2 text-sm text-slate-500">Yuklenen maksilla ve mandibula burada interaktif olarak gorunecek.</p>
              </div>
            </div>
          )}

          <div className={`${focusMode ? "pointer-events-auto" : "pointer-events-none"} absolute left-4 top-4 max-w-[280px] rounded-2xl border border-white/70 bg-white/60 px-4 py-3 shadow-sm backdrop-blur-xl`}>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">
              <Layers3 className="h-3.5 w-3.5 text-blue-600" />
              {measurementStage === "landmarks" ? "Dis Olcumu" : "Ark Boyu"}
            </div>
            <p className="mt-2 text-sm font-semibold text-slate-900">
              {mode === "occlusion" ? "Maksilla + Mandibula" : mode === "maxillary" ? "Maksilla" : "Mandibula"}
            </p>
            <div className="mt-3 space-y-2 text-xs leading-5 text-slate-600">
              {measurementStage === "landmarks" ? (
                <>
                  <p>
                    Aktif dis: <span className="font-semibold text-slate-900">{activeTooth ?? "-"}</span>
                  </p>
                  <p>
                    Aktif adim: <span className="font-semibold text-slate-900">{landmarkPhase === "mesial" ? "Mesial" : "Distal"}</span>
                  </p>
                  <p>
                    Tamamlanan nokta: <span className="font-semibold text-slate-900">{visibleLandmarks.length}</span>
                  </p>
                </>
              ) : (
                <>
                  <p>
                    Aktif ark: <span className="font-semibold text-slate-900">{archModeJaw === "maxillary" ? "Maksilla" : "Mandibula"}</span>
                  </p>
                  <p>
                    Nokta sayisi: <span className="font-semibold text-slate-900">{renderedArchPoints.length}</span>
                  </p>
                  <p>
                    Kayitli boy:{" "}
                    <span className="font-semibold text-slate-900">
                      {activeArchLength !== null ? `${activeArchLength.toFixed(2)} mm` : "Henuz yok"}
                    </span>
                  </p>
                </>
              )}
            </div>
          </div>

          {landmarkEnabled ? (
          <div className="absolute right-4 top-4 flex w-[300px] max-w-[calc(100%-2rem)] flex-col gap-2 rounded-2xl border border-white/70 bg-white/60 p-3 shadow-sm backdrop-blur-xl">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">
              <Pin className="h-3.5 w-3.5 text-blue-600" />
              Canli Dis Boyutlari
            </div>
            <p className="text-sm font-semibold text-slate-900">{mode === "maxillary" ? "Maksilla" : "Mandibula"}</p>
            <p className="text-xs leading-5 text-slate-500">
              Aktif adim: {landmarkPhase === "mesial" ? "Mesial" : "Distal"}.
              Olcumu sifirlamak icin ilgili dis satirindaki sil butonunu kullanin.
            </p>
            <div className="mt-1 rounded-xl bg-white/55 p-2">
              <div className="max-h-[220px] space-y-1 overflow-y-auto pr-1">
                {currentJawTeeth.map((tooth) => (
                  <div key={tooth} className={`flex items-center gap-2 rounded-xl px-2 py-1.5 ${activeTooth === tooth ? "bg-blue-50/80" : "bg-white/70"}`}>
                    <button type="button" className="min-w-0 flex-1 text-left text-xs font-medium text-slate-700" onClick={() => onActivateTooth(tooth)}>
                      <span className="mr-2 font-semibold text-slate-900">{tooth}</span>
                      <span>{measurementValues[tooth] || "--"}</span>
                    </button>
                    {measurementValues[tooth] ? (
                      <button type="button" className="rounded-lg p-1 text-slate-500 transition hover:bg-rose-50 hover:text-rose-600" onClick={() => onClearTooth(tooth)} aria-label={`${tooth} olcumunu temizle`}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          </div>
          ) : null}

          {archEnabled ? (
            <div className="absolute right-4 top-4 flex w-[300px] max-w-[calc(100%-2rem)] flex-col gap-2 rounded-2xl border border-white/70 bg-white/60 p-3 shadow-sm backdrop-blur-xl">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">
                <Pin className="h-3.5 w-3.5 text-emerald-600" />
                Ark ve Dis Ozetleri
              </div>
              <p className="text-sm font-semibold text-slate-900">
                {archModeJaw === "maxillary" ? "Maksilla" : "Mandibula"} ark olcumu
              </p>
              <p className="text-xs leading-5 text-slate-500">
                Ark boyunca noktalar yerlestirin. Kaydetme ve duzenleme aksiyonlari ust navbar uzerinden devam eder.
              </p>
              <div className="rounded-xl bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                <div className="flex items-center justify-between">
                  <span>Nokta Sayisi</span>
                  <span className="font-semibold text-slate-900">{renderedArchPoints.length}</span>
                </div>
                <div className="mt-1 flex items-center justify-between">
                  <span>Kayitli Ark Boyu</span>
                  <span className="font-semibold text-slate-900">
                    {activeArchLength !== null ? `${activeArchLength.toFixed(2)} mm` : "Henuz yok"}
                  </span>
                </div>
              </div>
              <div className="mt-1 rounded-xl bg-white/55 p-2">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Olculen Disler</p>
                <div className="max-h-[180px] space-y-1 overflow-y-auto pr-1">
                  {currentJawTeeth.map((tooth) => (
                    <div key={tooth} className="flex items-center gap-2 rounded-xl bg-white/70 px-2 py-1.5 text-xs font-medium text-slate-700">
                      <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onActivateTooth(tooth)}>
                        <span className="mr-2 font-semibold text-slate-900">{tooth}</span>
                        <span>{measurementValues[tooth] || "--"}</span>
                      </button>
                      {measurementValues[tooth] ? (
                        <button type="button" className="rounded-lg p-1 text-slate-500 transition hover:bg-rose-50 hover:text-rose-600" onClick={() => onClearTooth(tooth)} aria-label={`${tooth} olcumunu temizle`}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          {focusMode ? (
            <div className="absolute bottom-4 left-1/2 w-[min(640px,calc(100%-2rem))] -translate-x-1/2 rounded-2xl border border-white/70 bg-white/55 px-4 py-3 shadow-sm backdrop-blur-xl">
              <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-500">Akis Bilgisi</p>
              <p className="mt-1 text-sm font-medium text-slate-800">{stageInstruction}</p>
              <p className="mt-2 text-xs leading-5 text-slate-500">
                Sol tik ile nokta taslagi olusturun. Onay, geri al, temizle ve kamera secimleri ust navbar uzerinden yonetilir.
              </p>
            </div>
          ) : null}

          {mode === "occlusion" ? (
            <div className="absolute right-4 top-1/2 flex w-[240px] -translate-y-1/2 flex-col gap-3 rounded-2xl border border-white/70 bg-white/92 px-4 py-4 shadow-sm backdrop-blur">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.26em] text-slate-500">Mandibula Konumu</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">X / Y / Z eksenlerinde manuel konumlandir</p>
              </div>
              <div className="rounded-xl bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                <div className="flex items-center justify-between">
                  <span>Gorunumsel Cene Araligi</span>
                  <span className="font-semibold text-slate-900">{jawGap.toFixed(1)} mm</span>
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px] font-medium text-slate-600">
                  <span>Sag-Sol (X)</span>
                  <span className="font-semibold text-slate-900">{occlusionShiftX.toFixed(1)} mm</span>
                </div>
                <input
                  type="range"
                  min="-10"
                  max="10"
                  step="0.1"
                  value={occlusionControlX}
                  onChange={(event) => onOcclusionShiftXChange(Number(event.target.value))}
                  onMouseUp={onOcclusionShiftCommit}
                  onTouchEnd={onOcclusionShiftCommit}
                  onKeyUp={(event) => {
                    if (event.key.startsWith("Arrow") || event.key === "Home" || event.key === "End") {
                      onOcclusionShiftCommit();
                    }
                  }}
                  className="w-full accent-blue-600"
                  aria-label="Mandibula sag-sol kaydirma"
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px] font-medium text-slate-600">
                  <span>On-Arka (Y)</span>
                  <span className="font-semibold text-slate-900">{occlusionShiftY.toFixed(1)} mm</span>
                </div>
                <input
                  type="range"
                  min="-10"
                  max="10"
                  step="0.1"
                  value={occlusionControlY}
                  onChange={(event) => onOcclusionShiftYChange(Number(event.target.value))}
                  onMouseUp={onOcclusionShiftCommit}
                  onTouchEnd={onOcclusionShiftCommit}
                  onKeyUp={(event) => {
                    if (event.key.startsWith("Arrow") || event.key === "Home" || event.key === "End") {
                      onOcclusionShiftCommit();
                    }
                  }}
                  className="w-full accent-blue-600"
                  aria-label="Mandibula on-arka kaydirma"
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px] font-medium text-slate-600">
                  <span>Ust-Alt (Z)</span>
                  <span className="font-semibold text-slate-900">{occlusionShiftZ.toFixed(1)} mm</span>
                </div>
                <input
                  type="range"
                  min="-10"
                  max="10"
                  step="0.1"
                  value={occlusionControlZ}
                  onChange={(event) => onOcclusionShiftZChange(Number(event.target.value))}
                  onMouseUp={onOcclusionShiftCommit}
                  onTouchEnd={onOcclusionShiftCommit}
                  onKeyUp={(event) => {
                    if (event.key.startsWith("Arrow") || event.key === "Home" || event.key === "End") {
                      onOcclusionShiftCommit();
                    }
                  }}
                  className="w-full accent-blue-600"
                  aria-label="Mandibula ust-alt kaydirma"
                />
              </div>
              <div className="rounded-xl bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                <div className="flex items-center justify-between">
                  <span>Manuel Z Konumu</span>
                  <span className="font-semibold text-slate-900">Acik</span>
                </div>
              </div>
              <p className="text-[11px] leading-5 text-slate-500">
                {isResolvingOcclusion
                  ? "Kapanis konumu hesaplaniyor..."
                  : "Bu modda mandibula X, Y ve Z eksenlerinde tamamen manuel olarak kaydirilir."}
              </p>
            </div>
          ) : null}
    </div>
  );

  if (focusMode) {
    return viewportBody;
  }

  return (
    <Card className="overflow-hidden" data-selcukbolt-card>
      <CardHeader className="border-b border-slate-100 bg-white/80 pb-4 backdrop-blur">
        <div className="flex items-center justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Orbit className="h-5 w-5 text-blue-600" />
              3D STL Goruntuleyici
            </CardTitle>
            <CardDescription>Maksilla, mandibula veya kapanis gorunumu icin modeli tarayicida inceleyin.</CardDescription>
          </div>
          <div className="rounded-full bg-slate-100 px-4 py-2 text-xs font-semibold uppercase tracking-[0.28em] text-slate-600">
            {mode === "occlusion" ? "Kapanis" : mode === "maxillary" ? "Maksilla" : "Mandibula"}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">{viewportBody}</CardContent>
    </Card>
  );
}

function SingleStlMesh({
  file,
  material,
  jaw,
  translation,
  pointPickingEnabled,
  onAddPoint,
}: {
  file: File;
  material: MeshPhysicalMaterial;
  jaw: "maxillary" | "mandibular";
  translation: [number, number, number];
  pointPickingEnabled: boolean;
  onAddPoint: (jaw: "maxillary" | "mandibular", point: [number, number, number]) => void;
}) {
  const [geometry, setGeometry] = useState<BufferGeometry | null>(null);
  const dragStateRef = useRef<{ startX: number; startY: number; moved: boolean } | null>(null);
  const transformMatrix = useMemo(
    () => new Matrix4().makeTranslation(translation[0], translation[1], translation[2]),
    [translation],
  );

  useEffect(() => {
    let cancelled = false;
    const loader = new STLLoader();
    let parsedGeometry: BufferGeometry | null = null;

    file
      .arrayBuffer()
      .then((buffer) => {
        if (cancelled) {
          return;
        }
        parsedGeometry = loader.parse(buffer.slice(0));
        parsedGeometry.computeVertexNormals();
        setGeometry(parsedGeometry);
      })
      .catch(() => {
        if (!cancelled) {
          setGeometry(null);
        }
      });

    return () => {
      cancelled = true;
      parsedGeometry?.dispose();
    };
  }, [file]);

  const handlePointerDown = (event: ThreeEvent<PointerEvent>) => {
    dragStateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
  };

  const handlePointerMove = (event: ThreeEvent<PointerEvent>) => {
    const state = dragStateRef.current;
    if (!state) {
      return;
    }
    const distance = Math.hypot(event.clientX - state.startX, event.clientY - state.startY);
    if (distance > 5) {
      state.moved = true;
    }
  };

  const handlePointerUp = (event: ThreeEvent<PointerEvent>) => {
    if (!pointPickingEnabled) {
      dragStateRef.current = null;
      return;
    }
    const state = dragStateRef.current;
    dragStateRef.current = null;
    if (!state || state.moved) {
      return;
    }
    event.stopPropagation();
    onAddPoint(jaw, [event.point.x, event.point.y, event.point.z]);
  };

  if (!geometry) {
    return null;
  }

  return (
    <group matrixAutoUpdate={false} matrix={transformMatrix}>
      <mesh
        castShadow
        receiveShadow
        geometry={geometry}
        material={material}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      />
    </group>
  );
}

function CameraDamping({ preset, resetKey }: { preset: CameraPreset; resetKey: number }) {
  const { camera } = useThree();

  useEffect(() => {
    if (preset === "occlusal") {
      camera.position.set(0, 118, 0);
      camera.up.set(0, 0, -1);
    } else if (preset === "frontal") {
      camera.position.set(0, 18, 118);
      camera.up.set(0, 1, 0);
    } else {
      camera.position.set(118, 12, 0);
      camera.up.set(0, 1, 0);
    }
    camera.lookAt(new Vector3(0, 0, 0));
    camera.updateProjectionMatrix();
  }, [camera, preset, resetKey]);

  return (
    <Html position={[0, 0, 0]} center style={{ pointerEvents: "none" }}>
      <></>
    </Html>
  );
}
