export type AnalysisMode = "anterior" | "overall";
export type JawKey = "maxillary" | "mandibular";

export const MAXILLARY_ANTERIOR = [13, 12, 11, 21, 22, 23] as const;
export const MANDIBULAR_ANTERIOR = [43, 42, 41, 31, 32, 33] as const;
export const MAXILLARY_OVERALL = [16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26] as const;
export const MANDIBULAR_OVERALL = [46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36] as const;

export const TOOTH_GROUPS: Record<AnalysisMode, Record<JawKey, number[]>> = {
  anterior: {
    maxillary: [...MAXILLARY_ANTERIOR],
    mandibular: [...MANDIBULAR_ANTERIOR],
  },
  overall: {
    maxillary: [...MAXILLARY_OVERALL],
    mandibular: [...MANDIBULAR_OVERALL],
  },
};

export const TOOTH_NAMES: Record<number, string> = {
  11: "Ust Sag Santral",
  12: "Ust Sag Lateral",
  13: "Ust Sag Kanin",
  14: "Ust Sag 1. Premolar",
  15: "Ust Sag 2. Premolar",
  16: "Ust Sag 1. Molar",
  21: "Ust Sol Santral",
  22: "Ust Sol Lateral",
  23: "Ust Sol Kanin",
  24: "Ust Sol 1. Premolar",
  25: "Ust Sol 2. Premolar",
  26: "Ust Sol 1. Molar",
  31: "Alt Sol Santral",
  32: "Alt Sol Lateral",
  33: "Alt Sol Kanin",
  34: "Alt Sol 1. Premolar",
  35: "Alt Sol 2. Premolar",
  36: "Alt Sol 1. Molar",
  41: "Alt Sag Santral",
  42: "Alt Sag Lateral",
  43: "Alt Sag Kanin",
  44: "Alt Sag 1. Premolar",
  45: "Alt Sag 2. Premolar",
  46: "Alt Sag 1. Molar",
};

export function normalizeAnalysisMode(mode: string | null | undefined): AnalysisMode {
  if (mode === "overall" || mode === "total") {
    return "overall";
  }
  return "anterior";
}

export function visibleTeethFor(mode: AnalysisMode | string): number[] {
  const normalizedMode = normalizeAnalysisMode(mode);
  return [...TOOTH_GROUPS[normalizedMode].maxillary, ...TOOTH_GROUPS[normalizedMode].mandibular];
}

export function splitQuadrants(teeth: number[]) {
  const mid = Math.ceil(teeth.length / 2);
  return {
    right: teeth.slice(0, mid),
    left: teeth.slice(mid),
  };
}
