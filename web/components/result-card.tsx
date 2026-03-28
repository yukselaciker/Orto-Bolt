import { AlertCircle, CheckCircle2, Scale } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AnalysisMode, TOOTH_GROUPS, normalizeAnalysisMode } from "@/lib/tooth-config";
import type { BoltonResult, MeasurementsState } from "@/lib/types";

interface ResultCardProps {
  result: BoltonResult | null;
  mode?: AnalysisMode;
  values?: MeasurementsState;
  showMeasurements?: boolean;
}

export function ResultCard({ result, mode = "anterior", values = {}, showMeasurements = true }: ResultCardProps) {
  const isOk = result?.within_normal ?? false;
  const safeMode = normalizeAnalysisMode(mode);
  const discrepancyLabel =
    result?.discrepancy_arch === "mandibular"
      ? "Mandibuler fazlalik"
      : result?.discrepancy_arch === "maxillary"
        ? "Maksiller fazlalik"
        : "Dengeli";
  const discrepancyDetail =
    result?.discrepancy_arch === "mandibular"
      ? `Alt arkta yaklasik ${result.discrepancy_mm.toFixed(2)} mm fazlalik gorunuyor.`
      : result?.discrepancy_arch === "maxillary"
        ? `Ust arkta yaklasik ${result.discrepancy_mm.toFixed(2)} mm fazlalik gorunuyor.`
        : "Bolton oranina gore belirgin ark fazlaligi izlenmiyor.";

  return (
    <Card className="flex h-full max-h-full flex-col overflow-hidden shadow-sm" data-selcukbolt-card>
      <CardHeader className="flex-none pb-4">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Scale className="h-5 w-5 text-blue-600" />
          Analiz Sonucu
        </CardTitle>
        <CardDescription>Eski Python motorundan donen klinik oran ve uyumsuzluk bilgisi.</CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-2">
        {result ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-2">
            <Metric label="Oran" value={`%${result.ratio.toFixed(2)}`} tone={isOk ? "success" : "danger"} />
            <Metric label="Referans" value={`%${result.ideal_ratio.toFixed(1)}`} />
            <Metric label="Fark" value={`${result.difference > 0 ? "+" : ""}${result.difference.toFixed(2)}`} />
            <Metric label="Uyumsuzluk" value={`${result.discrepancy_mm.toFixed(2)} mm`} />
            <Metric label="Fazlalik Arki" value={discrepancyLabel} tone={isOk ? "default" : "danger"} />
            <Metric
              label="Klinik Yorum"
              value={result.discrepancy_arch === "mandibular" ? "Alt disler goreceli buyuk" : result.discrepancy_arch === "maxillary" ? "Ust disler goreceli buyuk" : "Boyut dengesi iyi"}
            />

            <div className="sm:col-span-2 xl:col-span-2 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                {isOk ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                ) : (
                  <AlertCircle className="h-4 w-4 text-orange-500" />
                )}
                <span className={isOk ? "text-emerald-700" : "text-orange-700"}>
                  {isOk ? "Normal aralikta" : "Klinik yorum gerekli"}
                </span>
              </div>
              <p className="mt-2 text-sm font-medium text-slate-700">{discrepancyDetail}</p>
              <p className="mt-2 text-sm leading-6 text-slate-600">{result.interpretation}</p>
            </div>

            {showMeasurements ? (
              <>
                <MeasurementPanel
                  title="Maksilla Dis Olculeri"
                  teeth={TOOTH_GROUPS[safeMode].maxillary}
                  values={values}
                />
                <MeasurementPanel
                  title="Mandibula Dis Olculeri"
                  teeth={TOOTH_GROUPS[safeMode].mandibular}
                  values={values}
                />
              </>
            ) : null}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">
            Olcumleri tamamladiginizda oran, fark ve uyumsuzluk burada gorunecek.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MeasurementPanel({
  title,
  teeth,
  values,
}: {
  title: string;
  teeth: number[];
  values: MeasurementsState;
}) {
  return (
    <div className="sm:col-span-2 xl:col-span-1 rounded-2xl border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">{title}</p>
      <div className="mt-3 space-y-2">
        {teeth.map((tooth) => (
          <div key={tooth} className="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2 text-sm">
            <span className="font-semibold text-slate-900">{tooth}</span>
            <span className="text-slate-600">{values[tooth] ?? "--"} mm</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "success" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "bg-emerald-50 text-emerald-700"
      : tone === "danger"
        ? "bg-rose-50 text-rose-700"
        : "bg-white text-slate-900";

  return (
    <div className={`rounded-2xl border border-slate-200 p-4 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">{label}</p>
      <p className="mt-3 text-2xl font-semibold">{value}</p>
    </div>
  );
}
