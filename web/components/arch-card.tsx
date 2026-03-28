"use client";

import { useMemo } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { JawKey, TOOTH_NAMES, splitQuadrants } from "@/lib/tooth-config";
import { MeasurementsState } from "@/lib/types";

interface ArchCardProps {
  jaw: JawKey;
  teeth: number[];
  values: MeasurementsState;
  onValueChange: (tooth: number, value: string) => void;
  onFieldEnter: (tooth: number) => void;
  registerInputRef: (tooth: number, element: HTMLInputElement | null) => void;
  activeTooth?: number | null;
  onActivateTooth?: (tooth: number) => void;
}

const JAW_LABELS: Record<JawKey, string> = {
  maxillary: "Maksilla",
  mandibular: "Mandibula",
};

export function ArchCard({
  jaw,
  teeth,
  values,
  onValueChange,
  onFieldEnter,
  registerInputRef,
  activeTooth,
  onActivateTooth,
}: ArchCardProps) {
  const quadrants = splitQuadrants(teeth);
  const total = useMemo(
    () =>
      teeth.reduce((sum, tooth) => {
        const value = Number.parseFloat(values[tooth]?.replace(",", ".") ?? "");
        return Number.isFinite(value) ? sum + value : sum;
      }, 0),
    [teeth, values],
  );

  return (
    <Card className="min-h-[480px] shadow-sm" data-selcukbolt-card>
      <CardHeader className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-xl">{JAW_LABELS[jaw]}</CardTitle>
            <CardDescription>Meziodistal genislikleri anatomik sirayla girin.</CardDescription>
          </div>
          <div className="rounded-full bg-blue-50 px-4 py-2 text-xs font-semibold uppercase tracking-[0.28em] text-blue-600">
            {teeth.length} Dis
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
          <section className="space-y-3 rounded-2xl border border-slate-200/70 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Sag Kadran</p>
            <div className="space-y-3">
              {quadrants.right.map((tooth) => (
                <label className="block space-y-1.5" key={tooth}>
                  <span className="text-xs font-medium text-slate-500">{TOOTH_NAMES[tooth]}</span>
                  <Input
                    inputMode="decimal"
                    placeholder={String(tooth)}
                    value={values[tooth] ?? ""}
                    className={activeTooth === tooth ? "border-blue-400 ring-2 ring-blue-100" : ""}
                    onChange={(event) => onValueChange(tooth, event.target.value)}
                    onFocus={() => onActivateTooth?.(tooth)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        onFieldEnter(tooth);
                      }
                    }}
                    ref={(node) => registerInputRef(tooth, node)}
                  />
                </label>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-slate-200/70 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Sol Kadran</p>
            <div className="space-y-3">
              {quadrants.left.map((tooth) => (
                <label className="block space-y-1.5" key={tooth}>
                  <span className="text-xs font-medium text-slate-500">{TOOTH_NAMES[tooth]}</span>
                  <Input
                    inputMode="decimal"
                    placeholder={String(tooth)}
                    value={values[tooth] ?? ""}
                    className={activeTooth === tooth ? "border-blue-400 ring-2 ring-blue-100" : ""}
                    onChange={(event) => onValueChange(tooth, event.target.value)}
                    onFocus={() => onActivateTooth?.(tooth)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        onFieldEnter(tooth);
                      }
                    }}
                    ref={(node) => registerInputRef(tooth, node)}
                  />
                </label>
              ))}
            </div>
          </section>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Guncel Toplam</p>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-3xl font-semibold text-slate-900">{total.toFixed(2)}</span>
            <span className="text-sm text-slate-500">mm</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
