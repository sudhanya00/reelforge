"use client";

import * as React from "react";
import { AudioLines, Bookmark, Check, Clock, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label, LiveBars, Segmented, Tip } from "@/components/ui/primitives";
import { chunk, editChunk, type Animation, type CaptionCatalog, type CaptionState, type CaptionStyle } from "@/lib/captions";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { captionTextStyle } from "./CaptionOverlay";
import { AddFont } from "./AddFont";

const ANIM_SHORT: Record<Animation, string> = {
  none: "Static",
  fade: "Fade",
  pop: "Pop",
  highlight: "Highlight",
  highlight_pop: "Highlight + pop",
  word_by_word: "Word by word",
};

export const CaptionsPanel = React.memo(function CaptionsPanel({
  state,
  catalog,
  onChange,
  onSync,
  syncing,
  onSeek,
  onSavePreset,
  onDeletePreset,
  onFontsChanged,
}: {
  state: CaptionState;
  catalog: CaptionCatalog;
  onChange: (patch: Partial<CaptionState>) => void;
  onSync: () => void;
  syncing: boolean;
  onSeek: (t: number) => void;
  onSavePreset: (name: string, style: CaptionStyle) => void;
  onDeletePreset: (id: string) => void;
  onFontsChanged: (catalog: CaptionCatalog) => void;
}) {
  const st = state.style;
  const set = (patch: Partial<CaptionStyle>) => onChange({ style: { ...st, ...patch } });
  const [presetName, setPresetName] = React.useState("");
  const chunks = React.useMemo(() => chunk(state.words, st), [state.words, st]);
  const same = (a: CaptionStyle, b: CaptionStyle) => JSON.stringify(a) === JSON.stringify(b);

  return (
    <div className="space-y-6">
      <label className="flex cursor-pointer items-center justify-between rounded-xl border p-3">
        <span>
          <span className="block text-sm font-medium">Captions</span>
          <span className="block text-xs text-muted-foreground">Your script&apos;s words, burned into the export</span>
        </span>
        <input type="checkbox" checked={state.enabled} onChange={(e) => onChange({ enabled: e.target.checked })} className="size-4 accent-foreground" />
      </label>

      <div className={cn("space-y-6", !state.enabled && "pointer-events-none opacity-40")}>
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Presets</h3>
          <div className="grid grid-cols-2 gap-2">
            {catalog.presets.map((p) => (
              <div key={p.id} className="group relative">
                <button
                  onClick={() => onChange({ style: p.style })}
                  className={cn(
                    "flex h-16 w-full flex-col items-center justify-center gap-1 overflow-hidden rounded-lg border bg-gradient-to-br from-slate-600 to-slate-800 px-1 transition-colors",
                    same(p.style, st) ? "ring-2 ring-foreground" : "hover:border-foreground/40",
                  )}
                >
                  <span style={{ ...captionTextStyle({ ...p.style, lines: 1 }, catalog.fonts, 170), whiteSpace: "nowrap" }}>
                    {p.style.animation.startsWith("highlight") ? (
                      <>
                        <span style={{ color: p.style.highlight }}>Hey</span> there
                      </>
                    ) : (
                      "Hey there"
                    )}
                  </span>
                  <span className="text-[10px] text-white/70">{p.name}</span>
                </button>
                {!p.builtin && (
                  <button
                    onClick={() => onDeletePreset(p.id)}
                    className="absolute top-1 right-1 hidden rounded-full bg-background/80 p-0.5 group-hover:block"
                    aria-label={`Delete ${p.name}`}
                  >
                    <X className="size-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Input value={presetName} onChange={(e) => setPresetName(e.target.value)} placeholder="Name this style" className="h-8" />
            <Button
              size="sm"
              variant="outline"
              shape="pill"
              disabled={!presetName.trim()}
              onClick={() => {
                onSavePreset(presetName, st);
                setPresetName("");
              }}
            >
              <Bookmark />
              Save
            </Button>
          </div>
        </section>

        <section className="space-y-3">
          <h3 className="text-sm font-semibold">Style</h3>
          <div className="space-y-1.5">
            <Label>Font</Label>
            <div className="flex flex-wrap gap-1.5">
              {catalog.fonts.map((f) => (
                <span key={f.id} className="group relative">
                  <button
                    onClick={() => set({ font: f.id })}
                    className={cn("rounded-md border px-2 py-1 text-sm", st.font === f.id ? "border-foreground bg-accent" : "hover:border-foreground/40")}
                    style={{ fontFamily: `"cap-${f.id}"` }}
                    title={f.user ? `${f.label} · ${f.source === "google" ? "from Google Fonts" : "uploaded"}${f.variable ? " · variable font: exports at its default weight" : ""}` : f.label}
                  >
                    {f.label}
                  </button>
                  {f.user && (
                    <button
                      onClick={async () => {
                        onFontsChanged(await api.deleteFont(f.id));
                        if (st.font === f.id) set({ font: catalog.defaults.font });
                      }}
                      className="absolute -top-1.5 -right-1.5 hidden rounded-full border bg-background p-0.5 group-hover:block"
                      aria-label={`Remove ${f.label}`}
                    >
                      <X className="size-2.5" />
                    </button>
                  )}
                </span>
              ))}
              <AddFont
                onAdded={(c, id) => {
                  onFontsChanged(c);
                  set({ font: id });
                }}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Animation</Label>
            <div className="flex flex-wrap gap-1.5">
              {catalog.animations.map((a) => (
                <Tip key={a.id} content={a.label}>
                  <button
                    onClick={() => set({ animation: a.id })}
                    className={cn("rounded-full border px-2.5 py-1 text-xs", st.animation === a.id ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}
                  >
                    {ANIM_SHORT[a.id]}
                  </button>
                </Tip>
              ))}
            </div>
          </div>
          <Range label="Size" value={st.size} min={3} max={12} step={0.1} fmt={(v) => v.toFixed(1)} onChange={(v) => set({ size: v })} />
          <Range label="Position" value={st.position} min={10} max={90} step={1} fmt={(v) => (v < 35 ? "top" : v > 65 ? "bottom" : "middle")} onChange={(v) => set({ position: v })} />
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Words per caption</Label>
              <Segmented<string> size="sm" value={String(st.words)} onChange={(v) => set({ words: Number(v) })} options={["1", "2", "3", "4", "6"].map((v) => ({ value: v, label: v }))} />
            </div>
            <div className="space-y-1.5">
              <Label>Lines</Label>
              <Segmented<string> size="sm" value={String(st.lines)} onChange={(v) => set({ lines: Number(v) })} options={["1", "2"].map((v) => ({ value: v, label: v }))} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Color label="Text" value={st.color} onChange={(v) => set({ color: v })} />
            <Color label="Highlight" value={st.highlight} onChange={(v) => set({ highlight: v })} />
            {st.box ? <Color label="Box" value={st.box_color} onChange={(v) => set({ box_color: v })} /> : <Color label="Outline" value={st.outline_color} onChange={(v) => set({ outline_color: v })} />}
          </div>
          {st.box ? (
            <Range label="Box opacity" value={st.box_opacity} min={0} max={1} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} onChange={(v) => set({ box_opacity: v })} />
          ) : (
            <Range label="Outline" value={st.outline} min={0} max={30} step={1} fmt={(v) => `${v}`} onChange={(v) => set({ outline: v })} />
          )}
          <Range label="Shadow" value={st.shadow} min={0} max={30} step={1} fmt={(v) => `${v}`} onChange={(v) => set({ shadow: v })} />
          <div className="flex gap-4">
            <Check2 label="Box behind text" checked={st.box} onChange={(v) => set({ box: v })} />
            <Check2 label="ALL CAPS" checked={st.uppercase} onChange={(v) => set({ uppercase: v })} />
          </div>
        </section>

        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">Timing</h3>
            <span className={cn("flex items-center gap-1 text-xs", state.synced === "voice" ? "text-ok" : "text-muted-foreground")}>
              {state.synced === "voice" ? <Check className="size-3" /> : <Clock className="size-3" />}
              {state.synced === "voice" ? "synced to the voice" : "estimated"}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            {state.synced === "voice"
              ? "Word times come from the audio. The words are still exactly yours."
              : "Estimated from the script; can drift by a second. Syncing listens to the audio for when each of your words is said. It never changes the words."}
          </p>
          <Button size="sm" variant="outline" shape="pill" onClick={onSync} disabled={syncing}>
            {syncing ? <LiveBars /> : <AudioLines />}
            {state.synced === "voice" ? "Sync again" : "Sync to the voice"}
            <span className="text-muted-foreground tabular">≈$0.02</span>
          </Button>
          {state.differences.length > 0 && (
            <div className="space-y-1 rounded-lg bg-live/10 p-2.5 text-xs">
              <p className="flex items-center gap-1.5 font-medium">
                <TriangleAlert className="size-3.5 text-live" />
                She didn&apos;t say it exactly as written here. Listen and edit the text below if needed:
              </p>
              {state.differences.map((d, i) => (
                <button key={i} onClick={() => onSeek(Math.max(0, d.at - 0.5))} className="block w-full rounded px-1 py-0.5 text-left hover:bg-live/10">
                  <span className="tabular text-muted-foreground">{d.at.toFixed(1)}s</span> script &ldquo;{d.expected}&rdquo; · heard &ldquo;{d.heard}&rdquo;
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Text</h3>
          <div className="space-y-1">
            {chunks.map((c, k) => (
              <ChunkRow
                key={`${k}-${c.words[0]}-${state.words[c.words[0]]?.text}`}
                time={c.start}
                text={c.words.map((i) => state.words[i].text).join(" ")}
                onSeek={() => onSeek(c.start)}
                onCommit={(text) => text.trim() && onChange({ words: editChunk(state.words, c, text) })}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
});

function ChunkRow({ time, text, onSeek, onCommit }: { time: number; text: string; onSeek: () => void; onCommit: (t: string) => void }) {
  const [v, setV] = React.useState(text);
  return (
    <div className="flex items-center gap-2">
      <button onClick={onSeek} className="w-10 shrink-0 text-right text-[11px] tabular text-muted-foreground hover:text-foreground">
        {time.toFixed(1)}s
      </button>
      <input
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== text && onCommit(v)}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        className="h-7 min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 text-sm outline-none hover:border-border focus:border-ring"
      />
    </div>
  );
}

function Range({ label, value, min, max, step, fmt, onChange }: { label: string; value: number; min: number; max: number; step: number; fmt: (v: number) => string; onChange: (v: number) => void }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <Label>{label}</Label>
        <span className="tabular text-muted-foreground">{fmt(value)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-foreground" />
    </div>
  );
}

function Color({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs">
      <input type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} className="size-5 cursor-pointer rounded border-0 bg-transparent p-0" />
      {label}
    </label>
  );
}

function Check2({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-foreground" />
      {label}
    </label>
  );
}
