"use client";

import { ChangeEvent } from "react";
import { FileUp, ScanFace } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { MeshInfo } from "@/lib/types";

interface MeshUploadCardProps {
  title: string;
  info: MeshInfo | null;
  onFileSelected: (file: File) => void;
  isLoading: boolean;
}

export function MeshUploadCard({
  title,
  info,
  onFileSelected,
  isLoading,
}: MeshUploadCardProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      onFileSelected(file);
    }
    event.target.value = "";
  };

  return (
    <Card className="shadow-sm" data-selcukbolt-card>
      <CardHeader className="space-y-2 pb-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <ScanFace className="h-4 w-4 text-blue-600" />
          {title}
        </CardTitle>
        <CardDescription>STL dosyasini yukleyin; backend mesh butunlugunu ve temel boyutlari dogrulasin.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label className="block cursor-pointer rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5 text-center transition hover:border-blue-300 hover:bg-blue-50/50">
          <input type="file" accept=".stl" className="hidden" onChange={handleChange} />
          <div className="flex flex-col items-center gap-3">
            <div className="rounded-full bg-white p-3 shadow-sm">
              <FileUp className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">{isLoading ? "Yukleniyor..." : "STL dosyasi sec"}</p>
              <p className="text-xs text-slate-500">.stl uzantili tarama dosyalari desteklenir</p>
            </div>
          </div>
        </label>

        {info ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Metric label="Dosya" value={info.file_name} />
            <Metric label="Nokta" value={String(info.point_count)} />
            <Metric label="Yuzey" value={String(info.face_count)} />
            <Metric label="Genislik" value={`${info.width_mm.toFixed(2)} mm`} />
          </div>
        ) : (
          <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-500">
            Henuz STL yuklenmedi.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm font-medium text-slate-900 break-all">{value}</p>
    </div>
  );
}
