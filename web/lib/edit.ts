// The small editor's settings and colour maths. Keep in sync with editor.py: the preview
// applies the same RGB matrix + contrast that ffmpeg exports.

export interface EditParams {
  start: number;
  end: number | null;
  brightness: number;
  contrast: number;
  saturation: number;
  warmth: number;
  volume: number;
  denoise: boolean;
  normalize: boolean;
  mute: boolean;
}

export const EDIT_DEFAULTS: EditParams = {
  start: 0,
  end: null,
  brightness: 1,
  contrast: 1,
  saturation: 1,
  warmth: 0,
  volume: 1,
  denoise: false,
  normalize: false,
  mute: false,
};

export type ColorKey = "brightness" | "contrast" | "saturation" | "warmth";

export const LOOKS: { id: string; label: string; set: Partial<Record<ColorKey, number>> }[] = [
  { id: "natural", label: "As shot", set: { brightness: 1, contrast: 1, saturation: 1, warmth: 0 } },
  { id: "warm", label: "Warm", set: { brightness: 1.02, contrast: 1, saturation: 1.05, warmth: 0.35 } },
  { id: "cool", label: "Cool", set: { brightness: 1, contrast: 1.02, saturation: 0.95, warmth: -0.3 } },
  { id: "punchy", label: "Punchy", set: { brightness: 1, contrast: 1.15, saturation: 1.2, warmth: 0.05 } },
  { id: "soft", label: "Soft", set: { brightness: 1.04, contrast: 0.9, saturation: 0.9, warmth: 0.1 } },
  { id: "bright", label: "Brighter", set: { brightness: 1.1, contrast: 1, saturation: 1, warmth: 0 } },
];

export const isIdentity = (e: EditParams) => (Object.keys(EDIT_DEFAULTS) as (keyof EditParams)[]).every((k) => e[k] === EDIT_DEFAULTS[k]);

/** Warmth x brightness x saturation (W3C saturate), rows of an RGB matrix. */
export function colorMatrix(e: EditParams): number[][] {
  const { saturation: s, brightness: b, warmth: w } = e;
  const sat = [
    [0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
    [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
    [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s],
  ];
  const warm = [1 + 0.12 * w, 1 + 0.02 * w, 1 - 0.12 * w];
  return sat.map((row, i) => row.map((v) => warm[i] * b * v));
}

/** The 4x5 values of an SVG feColorMatrix for the colour matrix. */
export function feMatrix(e: EditParams): string {
  const m = colorMatrix(e);
  return [...m.map((r) => [...r, 0, 0]), [0, 0, 0, 1, 0]].flat().map((v) => v.toFixed(5)).join(" ");
}
