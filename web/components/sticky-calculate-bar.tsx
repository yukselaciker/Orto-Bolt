import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

interface StickyCalculateBarProps {
  disabled: boolean;
  pending: boolean;
  modeLabel: string;
  onCalculate: () => void;
}

export function StickyCalculateBar({
  disabled,
  pending,
  modeLabel,
  onCalculate,
}: StickyCalculateBarProps) {
  return (
    <div className="sticky bottom-0 z-20 mt-10 border-t border-slate-200/80 bg-white/90 backdrop-blur" data-selcukbolt-panel>
      <div className="container flex items-center justify-between gap-4 py-4">
        <div>
          <p className="text-sm font-semibold text-slate-900">{modeLabel} analizi icin tum alanlari tamamlayin</p>
          <p className="text-sm text-slate-500">
            Buton ancak gerekli tum dis genislikleri girildiginde aktiflesir.
          </p>
        </div>

        <Button className="min-w-[180px]" disabled={disabled || pending} onClick={onCalculate}>
          {pending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Hesaplaniyor
            </>
          ) : (
            "Hesapla"
          )}
        </Button>
      </div>
    </div>
  );
}
