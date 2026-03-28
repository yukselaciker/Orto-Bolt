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
    <div className="flex items-center gap-1.5 rounded-2xl border border-white/70 bg-white/70 p-1.5 shadow-sm backdrop-blur-xl" data-selcukbolt-toolbar>
      <div className="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          onClick={onLoadSession}
          className="h-10 w-10 rounded-xl p-0"
          title="Oturum yukle"
        >
          <FolderOpen className="h-4 w-4" />
          <span className="sr-only">Oturum Yukle</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onSaveSession}
          className="h-10 w-10 rounded-xl p-0"
          title="Oturum kaydet"
        >
          <Save className="h-4 w-4" />
          <span className="sr-only">Oturum Kaydet</span>
        </Button>
      </div>

      <div className="relative" ref={exportRef}>
        <Button
          variant="secondary"
          size="sm"
          disabled={exportDisabled}
          onClick={() => setExportOpen((current) => !current)}
          className="h-10 w-10 rounded-xl p-0"
          title="Disa aktar"
        >
          <Download className="h-4 w-4" />
          <ChevronDown className="absolute bottom-1.5 right-1.5 h-3 w-3 opacity-70" />
          <span className="sr-only">Disa Aktar</span>
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
