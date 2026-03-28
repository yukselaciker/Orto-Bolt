"use client";

import { useEffect, useRef, useState } from "react";

import { Download, FolderOpen, Save, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";

interface SessionToolbarProps {
  onSaveSession: () => void;
  onLoadSession: () => void;
  onExportJson: () => void;
  onExportCsv: () => void;
  onExportPdf: () => void;
  onExportExcel: () => void;
  exportDisabled: boolean;
}

export function SessionToolbar({
  onSaveSession,
  onLoadSession,
  onExportJson,
  onExportCsv,
  onExportPdf,
  onExportExcel,
  exportDisabled,
}: SessionToolbarProps) {
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!exportRef.current?.contains(event.target as Node)) {
        setExportOpen(false);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    return () => window.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50/80 p-1.5" data-selcukbolt-toolbar>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onLoadSession} className="h-9 min-w-[118px] justify-start px-3">
          <FolderOpen className="mr-2 h-4 w-4" />
          Oturum Yukle
        </Button>
        <Button variant="outline" size="sm" onClick={onSaveSession} className="h-9 min-w-[118px] justify-start px-3">
          <Save className="mr-2 h-4 w-4" />
          Oturum Kaydet
        </Button>
      </div>

      <div className="relative ml-auto" ref={exportRef}>
        <Button
          variant="secondary"
          size="sm"
          disabled={exportDisabled}
          onClick={() => setExportOpen((current) => !current)}
          className="h-9 min-w-[122px] justify-between px-3"
        >
          <span className="flex items-center">
            <Download className="mr-2 h-4 w-4" />
            Disa Aktar
          </span>
          <ChevronDown className="ml-2 h-4 w-4 opacity-70" />
        </Button>

        {exportOpen ? (
          <div className="absolute right-0 top-[calc(100%+0.5rem)] z-20 min-w-[176px] overflow-hidden rounded-2xl border border-slate-200 bg-white p-1 shadow-xl">
            {[
              { label: "CSV", action: onExportCsv },
              { label: "JSON", action: onExportJson },
              { label: "Excel", action: onExportExcel },
              { label: "PDF", action: onExportPdf },
            ].map((item) => (
              <button
                key={item.label}
                type="button"
                disabled={exportDisabled}
                onClick={() => {
                  item.action();
                  setExportOpen(false);
                }}
                className="flex w-full items-center rounded-xl px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Download className="mr-2 h-4 w-4 text-blue-600" />
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
