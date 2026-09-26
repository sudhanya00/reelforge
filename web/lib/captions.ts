// Caption types and grouping. Keep chunk() in sync with captions.chunk (the export uses that).
import { useEffect } from "react";
import { API } from "./api";

export type Animation = "none" | "fade" | "pop" | "highlight" | "highlight_pop" | "word_by_word";

export interface CaptionStyle {
  font: string;
  size: number;
  uppercase: boolean;
  color: string;
  highlight: string;
  outline_color: string;
  outline: number;
  shadow: number;
  box: boolean;
  box_color: string;
  box_opacity: number;
  position: number;
  words: number;
  lines: number;
  animation: Animation;
}

export interface CaptionWord {
  text: string;
  start: number;
  end: number;
  seg: number;
  br: boolean;
}

export interface CaptionState {
  enabled: boolean;
  style: CaptionStyle;
  words: CaptionWord[];
  synced: "estimate" | "voice";
  differences: { at: number; expected: string; heard: string }[];
  script_key: string;
  synced_at: number | null;
}

export interface CaptionFont {
  id: string;
  label: string;
  file: string;
  em_scale: number;
}

export interface CaptionCatalog {
  fonts: CaptionFont[];
  animations: { id: Animation; label: string }[];
  defaults: CaptionStyle;
  presets: { id: string; name: string; style: CaptionStyle; builtin: boolean }[];
}

export interface Chunk {
  start: number;
  end: number;
  words: number[];
}

export function chunk(words: CaptionWord[], style: CaptionStyle): Chunk[] {
  const n = style.words;
  const groups: number[][] = [];
  let cur: number[] = [];
  words.forEach((w, i) => {
    cur.push(i);
    const nxt = words[i + 1];
    let endHere = cur.length >= n || !nxt || w.br || /[.!?]$/.test(w.text) || (n >= 3 && /,$/.test(w.text));
    if (nxt && nxt.start - w.end > 0.6) endHere = true;
    if (endHere) {
      groups.push(cur);
      cur = [];
    }
  });
  return groups.map((idx, k) => {
    const start = words[idx[0]].start;
    let end = words[idx[idx.length - 1]].end;
    const nextStart = k + 1 < groups.length ? words[groups[k + 1][0]].start : null;
    if (nextStart !== null && nextStart - end < 0.35) end = nextStart;
    return { start, end: Math.max(end, start + 0.25), words: idx };
  });
}

/** Load the caption fonts once, as "cap-<id>" families. */
export function useCaptionFonts(fonts: CaptionFont[] | undefined) {
  useEffect(() => {
    if (!fonts?.length || document.getElementById("caption-fonts")) return;
    const el = document.createElement("style");
    el.id = "caption-fonts";
    el.textContent = fonts.map((f) => `@font-face{font-family:"cap-${f.id}";src:url("${API}/fonts/${f.file}");font-display:block}`).join("\n");
    document.head.appendChild(el);
  }, [fonts]);
}

/** Replace a caption's words with edited text, keeping times where the word count matches. */
export function editChunk(words: CaptionWord[], c: Chunk, text: string): CaptionWord[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  const old = c.words.map((i) => words[i]);
  let fresh: CaptionWord[];
  if (tokens.length === old.length) fresh = old.map((w, k) => ({ ...w, text: tokens[k] }));
  else {
    const span = (c.end - c.start) / Math.max(tokens.length, 1);
    fresh = tokens.map((t, k) => ({
      text: t,
      start: +(c.start + k * span).toFixed(2),
      end: +(c.start + (k + 1) * span - 0.02).toFixed(2),
      seg: old[0].seg,
      br: k === tokens.length - 1 && old[old.length - 1].br,
    }));
  }
  return [...words.slice(0, c.words[0]), ...fresh, ...words.slice(c.words[c.words.length - 1] + 1)];
}
