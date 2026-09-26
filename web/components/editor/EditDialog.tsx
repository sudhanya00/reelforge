"use client";

import * as React from "react";
import { Captions, Pause, Play, RotateCcw, Scissors, SlidersHorizontal, SunMedium, Volume2 } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Label, Segmented } from "@/components/ui/primitives";
import { useCaptionFonts, type CaptionCatalog, type CaptionState, type CaptionStyle } from "@/lib/captions";
import { CaptionOverlay } from "./CaptionOverlay";
import { CaptionsPanel } from "./CaptionsPanel";

export interface CaptionsProps {
  state: CaptionState;
  catalog: CaptionCatalog;
  onChange: (patch: Partial<CaptionState>) => void;
  onSync: () => void;
  syncing: boolean;
  onSavePreset: (name: string, style: CaptionStyle) => void;
  onDeletePreset: (id: string) => void;
  onFontsChanged: (catalog: CaptionCatalog) => void;
}
import { EDIT_DEFAULTS, LOOKS, feMatrix, isIdentity, type ColorKey, type EditParams } from "@/lib/edit";
import { cn, secs } from "@/lib/utils";

/**
 * Trim, colour and audio for a finished video. The preview is live (colour through an SVG
 * filter with the same maths ffmpeg uses; volume through Web Audio); denoise and loudness
 * are applied on export. Nothing touches the original.
 */
export function EditDialog({
  open,
  onOpenChange,
  src,
  vertical,
  duration,
  initial,
  onExport,
  captions,
  initialTab = "edit",
  startAt,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  src: string;
  vertical: boolean;
  duration: number;
  initial: EditParams;
  onExport: (e: EditParams) => Promise<void>;
  captions?: CaptionsProps;
  initialTab?: "edit" | "captions";
  startAt?: number;
}) {
  const [e, setE] = React.useState<EditParams>(initial);
  const [t, setT] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [compare, setCompare] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const video = React.useRef<HTMLVideoElement>(null);
  const audio = React.useRef<{ ctx: AudioContext; gain: GainNode } | null>(null);
  const fid = React.useId().replace(/:/g, "");
  const end = e.end ?? duration;
  const [tab, setTab] = React.useState<"edit" | "captions">(initialTab);
  const [box, setBox] = React.useState({ w: 0, h: 0 });
  useCaptionFonts(captions?.catalog.fonts);

  // the rendered size of the video (captions scale with it); the dialog mounts it a render late
  const [videoEl, setVideoEl] = React.useState<HTMLVideoElement | null>(null);
  const videoRef = React.useCallback((el: HTMLVideoElement | null) => {
    video.current = el;
    setVideoEl(el);
    if (el && startAt) {
      el.currentTime = startAt;
      setT(startAt);
    }
  }, []);
  React.useEffect(() => {
    if (!videoEl) return;
    const ro = new ResizeObserver(() => setBox({ w: videoEl.clientWidth, h: videoEl.clientHeight }));
    ro.observe(videoEl);
    return () => ro.disconnect();
  }, [videoEl]);

  // word-accurate time while playing (timeupdate is only ~4 per second)
  React.useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      if (video.current) setT(video.current.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  React.useEffect(() => {
    if (open) setE(initial);
  }, [open, initial]);

  // volume preview (can go above 100%, which <video>.volume can't)
  React.useEffect(() => {
    if (audio.current) audio.current.gain.gain.value = e.mute ? 0 : e.volume;
  }, [e.volume, e.mute]);

  const set = (patch: Partial<EditParams>) => setE((x) => ({ ...x, ...patch }));

  const togglePlay = () => {
    const v = video.current;
    if (!v) return;
    if (!audio.current) {
      try {
        const ctx = new AudioContext();
        const gain = ctx.createGain();
        ctx.createMediaElementSource(v).connect(gain).connect(ctx.destination);
        gain.gain.value = e.mute ? 0 : e.volume;
        audio.current = { ctx, gain };
      } catch {
        /* preview without volume boost */
      }
    }
    audio.current?.ctx.resume();
    if (v.paused) {
      if (v.currentTime < e.start || v.currentTime >= end - 0.05) v.currentTime = e.start;
      v.play();
    } else v.pause();
  };

  // keep playback inside the trim
  const onTime = () => {
    const v = video.current;
    if (!v) return;
    if (v.currentTime >= end) {
      v.pause();
      v.currentTime = e.start;
    } else if (v.currentTime < e.start - 0.05) v.currentTime = e.start;
    setT(v.currentTime);
  };

  const seek = React.useCallback((x: number) => {
    if (video.current) video.current.currentTime = x;
    setT(x);
  }, []);

  const exportIt = async () => {
    setBusy(true);
    try {
      await onExport(e);
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  const look = LOOKS.find((l) => (Object.keys(l.set) as ColorKey[]).every((k) => Math.abs(e[k] - (l.set[k] ?? 0)) < 1e-6));
  const c = e.contrast;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(1080px,calc(100vw-2rem))] max-w-none gap-0 p-0">
        <svg width="0" height="0" className="absolute" aria-hidden>
          <filter id={fid} colorInterpolationFilters="sRGB">
            <feColorMatrix type="matrix" values={feMatrix(e)} />
            <feComponentTransfer>
              {(["R", "G", "B"] as const).map((ch) => {
                const F = { R: "feFuncR", G: "feFuncG", B: "feFuncB" }[ch] as "feFuncR";
                return <F key={ch} type="linear" slope={c} intercept={0.5 - 0.5 * c} />;
              })}
            </feComponentTransfer>
          </filter>
        </svg>
        <div className="grid max-h-[calc(100vh-2rem)] min-h-0 md:h-[min(860px,calc(100vh-2rem))] md:grid-cols-[1fr_340px] md:grid-rows-[minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col gap-3 bg-black/90 p-4">
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <div className="relative">
              <video
                ref={videoRef}
                src={src}
                playsInline
                onTimeUpdate={onTime}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onClick={togglePlay}
                className={cn("max-h-[62vh] rounded-lg bg-black", vertical ? "aspect-[9/16] h-[62vh]" : "aspect-video w-full")}
                style={compare ? undefined : { filter: `url(#${fid})` }}
              />
              {captions?.state.enabled && !compare && (
                <CaptionOverlay words={captions.state.words} style={captions.state.style} fonts={captions.catalog.fonts} t={t} width={box.w} height={box.h} />
              )}
              </div>
            </div>
            <div className="flex items-center gap-3 text-white">
              <Button size="icon-sm" variant="secondary" shape="pill" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
                {playing ? <Pause /> : <Play />}
              </Button>
              <TrimBar duration={duration} start={e.start} end={end} t={t} onTrim={(s, en) => set({ start: s, end: en >= duration - 0.05 ? null : en })} onSeek={seek} />
              <span className="w-20 text-right text-xs tabular text-white/70">
                {secs(end - e.start)} / {secs(duration)}
              </span>
            </div>
          </div>

          <div className="flex min-h-0 flex-col">
            <div className="border-b px-5 pt-5 pb-4">
              <DialogTitle>Edit</DialogTitle>
              <DialogDescription className="mt-1">Exports a copy; the original stays as it is.</DialogDescription>
              {captions && (
                <Segmented<"edit" | "captions">
                  size="sm"
                  className="mt-3"
                  value={tab}
                  onChange={setTab}
                  options={[
                    { value: "edit", label: <><SlidersHorizontal />Trim, colour, audio</> },
                    { value: "captions", label: <><Captions />Captions</> },
                  ]}
                />
              )}
            </div>
            {captions && tab === "captions" ? (
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 scrollbar-thin">
                <CaptionsPanel {...captions} onSeek={seek} />
              </div>
            ) : (
            <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5 scrollbar-thin">
              <section className="space-y-2">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                  <Scissors className="size-4" /> Trim
                </h3>
                <p className="text-xs text-muted-foreground">
                  Drag the handles under the video. Keeping {secs(e.start)} → {secs(end)}.
                </p>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" shape="pill" className="h-7 text-xs" onClick={() => set({ start: Math.min(t, end - 0.5) })}>
                    Start here
                  </Button>
                  <Button size="sm" variant="outline" shape="pill" className="h-7 text-xs" onClick={() => set({ end: Math.max(t, e.start + 0.5) })}>
                    End here
                  </Button>
                </div>
              </section>

              <section className="space-y-3">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                  <SunMedium className="size-4" /> Colour
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {LOOKS.map((l) => (
                    <button
                      key={l.id}
                      onClick={() => set(l.set)}
                      className={cn(
                        "rounded-full border px-2.5 py-1 text-xs transition-colors",
                        look?.id === l.id ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                      )}
                    >
                      {l.label}
                    </button>
                  ))}
                </div>
                <Slider label="Brightness" value={e.brightness} min={0.5} max={1.5} onChange={(v) => set({ brightness: v })} />
                <Slider label="Contrast" value={e.contrast} min={0.5} max={1.5} onChange={(v) => set({ contrast: v })} />
                <Slider label="Saturation" value={e.saturation} min={0} max={2} onChange={(v) => set({ saturation: v })} />
                <Slider label="Warmth" value={e.warmth} min={-1} max={1} center={0} onChange={(v) => set({ warmth: v })} format={(v) => (v > 0 ? `+${Math.round(v * 100)}` : `${Math.round(v * 100)}`)} />
                <Button
                  size="sm"
                  variant="ghost"
                  shape="pill"
                  className="h-7 text-xs"
                  onPointerDown={() => setCompare(true)}
                  onPointerUp={() => setCompare(false)}
                  onPointerLeave={() => setCompare(false)}
                >
                  Hold to see the original
                </Button>
              </section>

              <section className="space-y-3">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                  <Volume2 className="size-4" /> Audio
                </h3>
                <Slider label="Volume" value={e.volume} min={0} max={2} onChange={(v) => set({ volume: v })} format={(v) => `${Math.round(v * 100)}%`} disabled={e.mute} />
                <Toggle label="Reduce background noise" hint="Hiss and room hum; applied on export" checked={e.denoise} onChange={(v) => set({ denoise: v })} />
                <Toggle label="Even out loudness" hint="Social-media level (−14 LUFS); applied on export" checked={e.normalize} onChange={(v) => set({ normalize: v })} />
                <Toggle label="Mute" hint="For adding music or a voice-over elsewhere" checked={e.mute} onChange={(v) => set({ mute: v })} />
              </section>
            </div>
            )}
            <div className="flex items-center gap-2 border-t px-5 py-4">
              <Button variant="ghost" size="sm" shape="pill" onClick={() => setE(EDIT_DEFAULTS)} disabled={isIdentity(e)}>
                <RotateCcw />
                Reset
              </Button>
              <Button shape="pill" className="ml-auto" onClick={exportIt} disabled={busy}>
                {isIdentity(e) && !isIdentity(initial) && !captions?.state.enabled ? "Remove edit" : captions?.state.enabled ? "Export with captions" : "Export"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  center = 1,
  onChange,
  format = (v) => `${Math.round(v * 100)}%`,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  center?: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
  disabled?: boolean;
}) {
  return (
    <div className={cn("space-y-1", disabled && "opacity-50")}>
      <div className="flex items-center justify-between text-xs">
        <Label>{label}</Label>
        <button className="tabular text-muted-foreground hover:text-foreground" onClick={() => onChange(center)} title="Reset" disabled={disabled}>
          {format(value)}
        </button>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={0.01}
        value={value}
        disabled={disabled}
        onChange={(ev) => onChange(Number(ev.target.value))}
        onDoubleClick={() => onChange(center)}
        className="w-full accent-foreground"
      />
    </div>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3">
      <span className="text-sm">
        {label}
        <span className="block text-xs text-muted-foreground">{hint}</span>
      </span>
      <input type="checkbox" checked={checked} onChange={(ev) => onChange(ev.target.checked)} className="mt-1 size-4 accent-foreground" />
    </label>
  );
}

/** One track, two handles (start and end), a playhead; click the track to seek. */
function TrimBar({ duration, start, end, t, onTrim, onSeek }: { duration: number; start: number; end: number; t: number; onTrim: (s: number, e: number) => void; onSeek: (t: number) => void }) {
  const pct = (x: number) => `${(x / Math.max(duration, 0.01)) * 100}%`;
  const thumb =
    "pointer-events-none absolute inset-0 h-full w-full appearance-none bg-transparent [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:h-7 [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:cursor-ew-resize [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-sm [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow";
  return (
    <div
      className="relative h-7 flex-1 cursor-pointer"
      onClick={(ev) => {
        const r = ev.currentTarget.getBoundingClientRect();
        onSeek(Math.min(end, Math.max(start, ((ev.clientX - r.left) / r.width) * duration)));
      }}
    >
      <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-white/15" />
      <div className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-white/60" style={{ left: pct(start), width: `calc(${pct(end)} - ${pct(start)})` }} />
      <div className="absolute top-0 h-full w-0.5 bg-live" style={{ left: pct(t) }} />
      <input type="range" min={0} max={duration} step={0.05} value={start} onChange={(ev) => onTrim(Math.min(Number(ev.target.value), end - 0.5), end)} className={thumb} aria-label="Trim start" onClick={(ev) => ev.stopPropagation()} />
      <input type="range" min={0} max={duration} step={0.05} value={end} onChange={(ev) => onTrim(start, Math.max(Number(ev.target.value), start + 0.5))} className={thumb} aria-label="Trim end" onClick={(ev) => ev.stopPropagation()} />
    </div>
  );
}
