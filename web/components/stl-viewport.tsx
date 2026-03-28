"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Box, Camera, Layers3, Orbit, Pin, RotateCcw, Undo2 } from "lucide-react";
import { Canvas, ThreeEvent, useThree } from "@react-three/fiber";
import { Bounds, Html, Line, OrbitControls } from "@react-three/drei";
import { BufferGeometry, DoubleSide, MOUSE, Matrix4, MeshPhysicalMaterial, TOUCH, Vector3 } from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { LandmarkPoint, MeshInfo } from "@/lib/types";

type ViewerMode = "maxillary" | "mandibular" | "occlusion";
type CameraPreset = "occlusal" | "frontal" | "lateral";

interface StlViewportProps {
  mode: ViewerMode;
  maxillaFile: File | null;
  mandibleFile: File | null;
  maxillaInfo?: MeshInfo | null;
  mandibleInfo?: MeshInfo | null;
  landmarks: LandmarkPoint[];
  landmarkDraft?: LandmarkPoint | null;
  onAddLandmark: (jaw: "maxillary" | "mandibular", point: [number, number, number]) => void;
  onConfirmLandmark: () => void;
  onUndoLandmark: () => void;
  onClearLandmarks: () => void;
  cameraPreset: CameraPreset;
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
  landmarks,
  landmarkDraft,
  onAddLandmark,
  onConfirmLandmark,
  onUndoLandmark,
  onClearLandmarks,
  cameraPreset,
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
  const landmarkEnabled = mode !== "occlusion";
  const occlusionOffsets = useMemo(() => {
    return {
      maxillary: [0, 0, 0] as [number, number, number],
      mandibular: [occlusionShiftX, occlusionShiftY, occlusionShiftZ] as [number, number, number],
    };
  }, [occlusionShiftX, occlusionShiftY, occlusionShiftZ]);
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
  const measurementPairs = useMemo(() => {
    const grouped = new Map<string, LandmarkPoint[]>();
    for (const landmark of renderedLandmarks) {
      const toothKey = landmark.label.split(" ")[0];
      const bucket = grouped.get(toothKey) ?? [];
      bucket.push(landmark);
      grouped.set(toothKey, bucket);
    }
    return Array.from(grouped.entries())
      .map(([tooth, points]) => ({ tooth, points }))
      .filter((item) => item.points.length >= 2);
  }, [renderedLandmarks]);
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
      <CardContent className="p-0">
        <div className="relative h-[520px] bg-[#f7fafc]" data-selcukbolt-viewport>
          {hasAnyModel ? (
            <Canvas shadows camera={{ position: [0, 0, 120], fov: 30 }} dpr={[1, 1.75]}>
              <color attach="background" args={["#f8fafc"]} />
              <ambientLight intensity={0.24} />
              <hemisphereLight args={["#fff7ed", "#cbd5e1", 0.56]} />
              <directionalLight
                position={[42, 54, 82]}
                intensity={1.45}
                castShadow
                shadow-mapSize-width={2048}
                shadow-mapSize-height={2048}
                shadow-bias={-0.00008}
              />
              <directionalLight position={[-36, 24, 54]} intensity={0.7} color="#dbeafe" />
              <directionalLight position={[0, -36, 32]} intensity={0.46} color="#e2e8f0" />
              <directionalLight position={[0, 22, -70]} intensity={0.52} color="#f8fafc" />
              <Suspense fallback={null}>
                <Bounds fit clip observe margin={1.08}>
                  {mode !== "mandibular" && maxillaFile ? (
                    <SingleStlMesh
                      file={maxillaFile}
                      material={maxillaMaterial}
                      jaw="maxillary"
                      translation={mode === "occlusion" ? occlusionOffsets.maxillary : [0, 0, 0]}
                      landmarkEnabled={landmarkEnabled}
                      onAddLandmark={onAddLandmark}
                    />
                  ) : null}
                  {mode !== "maxillary" && mandibleFile ? (
                    <SingleStlMesh
                      file={mandibleFile}
                      material={mandibleMaterial}
                      jaw="mandibular"
                      translation={mode === "occlusion" ? occlusionOffsets.mandibular : [0, 0, 0]}
                      landmarkEnabled={landmarkEnabled}
                      onAddLandmark={onAddLandmark}
                    />
                  ) : null}
                  {landmarkEnabled ? renderedLandmarks.map((landmark) => (
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
                  {landmarkEnabled && landmarkDraft ? (
                    <group position={landmarkDraft.position}>
                      <mesh>
                        <sphereGeometry args={[0.28, 20, 20]} />
                        <meshStandardMaterial
                          color={landmarkDraft.jaw === "maxillary" ? "#60a5fa" : "#4ade80"}
                          emissive={landmarkDraft.jaw === "maxillary" ? "#1d4ed8" : "#15803d"}
                          emissiveIntensity={0.16}
                          roughness={0.28}
                        />
                      </mesh>
                      <Html distanceFactor={12}>
                        <div className="rounded-md border border-blue-200 bg-white/95 px-1.5 py-0.5 text-[8px] font-semibold text-blue-700 shadow-sm">
                          {landmarkDraft.label}
                        </div>
                      </Html>
                    </group>
                  ) : null}
                  {landmarkEnabled ? measurementPairs.map(({ tooth, points }) => (
                    <Line key={`line-${tooth}`} points={[points[0].position, points[1].position]} color="#f97316" lineWidth={2} />
                  )) : null}
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

          <div className="pointer-events-none absolute left-4 top-4 max-w-[220px] rounded-2xl border border-white/70 bg-white/85 px-4 py-3 shadow-sm backdrop-blur">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">
              <Layers3 className="h-3.5 w-3.5 text-blue-600" />
              Aktif gorunum
            </div>
            <p className="mt-2 text-sm font-semibold text-slate-900">
              {mode === "occlusion" ? "Maksilla + Mandibula" : mode === "maxillary" ? "Maksilla" : "Mandibula"}
            </p>
          </div>

          {landmarkEnabled ? (
          <div className="absolute right-4 top-4 flex w-[248px] max-w-[calc(100%-2rem)] flex-col gap-2 rounded-2xl border border-white/70 bg-white/90 p-3 shadow-sm backdrop-blur">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">
              <Pin className="h-3.5 w-3.5 text-blue-600" />
              Landmark
            </div>
            <p className="text-sm font-semibold text-slate-900">{renderedLandmarks.length} nokta</p>
            <p className="text-xs leading-5 text-slate-500">
              Aktif adim: {landmarkPhase === "mesial" ? "Mesial" : "Distal"}
              <br />
              Tik ile noktayi hazirlayin, sonra onaylayin.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="default"
                onClick={onConfirmLandmark}
                disabled={!landmarkDraft}
                className="min-w-0 flex-1"
              >
                Onayla
              </Button>
              <Button size="sm" variant="outline" onClick={onUndoLandmark} className="min-w-0 flex-1">
                <Undo2 className="mr-1 h-3.5 w-3.5" />
                Geri Al
              </Button>
              <Button size="sm" variant="outline" onClick={onClearLandmarks} className="w-full">
                Temizle
              </Button>
            </div>
          </div>
          ) : null}

          <div className="absolute bottom-4 left-4 rounded-2xl border border-white/70 bg-white/90 px-4 py-3 shadow-sm backdrop-blur">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">
              <Camera className="h-3.5 w-3.5 text-blue-600" />
              Kamera
            </div>
            <p className="mt-2 text-sm font-semibold text-slate-900">
              {cameraPreset === "occlusal" ? "Okluzal" : cameraPreset === "frontal" ? "Frontal" : "Lateral"}
            </p>
            <div className="mt-2 text-[11px] leading-5 text-slate-500">
              Sol tik surukle: {navigationMode === "pan" ? "Tasi" : "Dondur"}
              <br />
              Sag tik surukle: Tasi
              <br />
              Tekerlek: Zoom
            </div>
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                variant={navigationMode === "rotate" ? "default" : "outline"}
                className="flex-1"
                onClick={() => setNavigationMode("rotate")}
              >
                Dondur
              </Button>
              <Button
                size="sm"
                variant={navigationMode === "pan" ? "default" : "outline"}
                className="flex-1"
                onClick={() => setNavigationMode("pan")}
              >
                Tasi
              </Button>
            </div>
            <Button size="sm" variant="outline" className="mt-3 w-full" onClick={() => setResetKey((current) => current + 1)}>
              <RotateCcw className="mr-2 h-3.5 w-3.5" />
              Gorunumu Sifirla
            </Button>
          </div>

          {mode === "occlusion" ? (
            <div className="absolute right-4 top-1/2 flex w-[240px] -translate-y-1/2 flex-col gap-3 rounded-2xl border border-white/70 bg-white/92 px-4 py-4 shadow-sm backdrop-blur">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.26em] text-slate-500">Mandibula Konumu</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">X / Y / Z eksenlerinde manuel konumlandir</p>
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
      </CardContent>
    </Card>
  );
}

function SingleStlMesh({
  file,
  material,
  jaw,
  translation,
  landmarkEnabled,
  onAddLandmark,
}: {
  file: File;
  material: MeshPhysicalMaterial;
  jaw: "maxillary" | "mandibular";
  translation: [number, number, number];
  landmarkEnabled: boolean;
  onAddLandmark: (jaw: "maxillary" | "mandibular", point: [number, number, number]) => void;
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
    if (!landmarkEnabled) {
      dragStateRef.current = null;
      return;
    }
    const state = dragStateRef.current;
    dragStateRef.current = null;
    if (!state || state.moved) {
      return;
    }
    event.stopPropagation();
    onAddLandmark(jaw, [event.point.x, event.point.y, event.point.z]);
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
