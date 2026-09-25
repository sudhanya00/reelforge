"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { ArrowUp, ChevronDown, Clapperboard, Link2, Plus, RefreshCw, RotateCcw, TriangleAlert, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, LiveBars, Segmented, Spinner, Textarea, Tip } from "@/components/ui/primitives";
import { providerInfo, useJobs, videoUsd } from "@/lib/hooks";
import { JobProgress } from "@/components/progress";
import { url, type Asset, type Project, type Scene, type Take } from "@/lib/api";
import { cn, secs, usd } from "@/lib/utils";
import { useProjectActions } from "./actions";

export function ScenesView({ p }: { p: Project }) {
  return (
    <div>
      <SceneStrip p={p} />
      <div className="mt-8 space-y-6">
        {p.scenes.map((sc, i) => (
          <SceneCard key={sc.id} p={p} sc={sc} index={i} />
        ))}
      </div>
    </div>
  );
}

/** Sticky row of scene chips to jump around, with status dots. */
function SceneStrip({ p }: { p: Project }) {
  return (
    <div className="sticky top-16 z-20 -mx-2 flex gap-1.5 overflow-x-auto rounded-full px-2 py-2 scrollbar-thin">
      {p.scenes.map((sc) => (
        <a
          key={sc.id}
          href={`#scene-${sc.id}`}
          className="flex shrink-0 items-center gap-2 rounded-full border bg-background/85 px-3 py-1 text-xs font-medium backdrop-blur transition-colors hover:bg-accent"
        >
          <span className={cn("size-1.5 rounded-full", sc.status === "generating" ? "animate-pulse bg-live" : sc.takes.length ? "bg-ok" : sc.error ? "bg-destructive" : "bg-muted-foreground/30")} />
          <span className="font-mono">{sc.id}</span>
          <span className="text-muted-foreground tabular">{sc.duration_s}s</span>
        </a>
      ))}
    </div>
  );
}

function SceneCard({ p, sc, index }: { p: Project; sc: Scene; index: number }) {
  const vertical = p.orientation === "9:16";
  const take = sc.takes.find((t) => t.name === sc.selected) ?? sc.takes.at(-1);
  const prev = index > 0 ? p.scenes[index - 1] : null;

  return (
    <motion.article
      id={`scene-${sc.id}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 5) * 0.04 }}
      className="scroll-mt-32 rounded-2xl border bg-card p-4 sm:p-5"
    >
      <div className={cn("grid gap-6", vertical ? "md:grid-cols-[260px_1fr]" : "lg:grid-cols-[minmax(0,540px)_1fr]")}>
        <div className="space-y-3">
          <Stage p={p} sc={sc} take={take} vertical={vertical} />
          <TakeStrip p={p} sc={sc} vertical={vertical} />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-foreground px-1.5 py-0.5 font-mono text-[11px] font-semibold text-background">{sc.id}</span>
            <Tip content={sc.render.duration_s !== sc.duration_s ? `Planned ${sc.duration_s}s; this model shoots ${sc.render.duration_s}s minimum` : null}>
              <Badge tone="outline" className="tabular">{sc.render.duration_s}s</Badge>
            </Tip>
            {sc.continuity === "continuous" && prev && (
              <Tip content={`Starts on the last frame of ${prev.id}'s selected take`}>
                <Badge tone="outline">
                  <Link2 />
                  continues {prev.id}
                </Badge>
              </Tip>
            )}
            <ModelPicker p={p} sc={sc} />
            {take && (
              <span className="ml-auto text-xs text-muted-foreground tabular">
                {take.name.replace(".mp4", "").replace("_", " ")} · {shortLabel(take.provider)} · {secs(take.duration_s)} ·{" "}
                {take.resolution} · {usd(take.cost_usd)}
              </span>
            )}
          </div>

          <p className="text-lg leading-snug font-medium tracking-tight">{sc.action}</p>

          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            {([["Shot", sc.shot], ["Camera", sc.camera], ["Lighting", sc.lighting], ["Sound", sc.audio]] as const).map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-muted-foreground">{k}</dt>
                <dd className="text-foreground/85">{v}</dd>
              </div>
            ))}
          </dl>

          {sc.dialogue && sc.dialogue.length > 0 && (
            <div className="space-y-1.5 border-l-2 pl-3">
              {sc.dialogue.map((d, i) => (
                <p key={i} className="text-sm">
                  <span className="font-medium">{d.speaker}</span> <span className="text-foreground/80 italic">“{d.line}”</span>
                </p>
              ))}
            </div>
          )}

          <Refs p={p} sc={sc} />
          <PromptPanel p={p} sc={sc} />
          {take && <FixComposer p={p} sc={sc} take={take} />}
        </div>
      </div>
    </motion.article>
  );
}

// ---------------------------------------------------------------- player

function Stage({ p, sc, take, vertical }: { p: Project; sc: Scene; take?: Take; vertical: boolean }) {
  const act = useProjectActions(p);
  const { running } = useJobs();
  const job = running.find((j) => j.project === p.id && (j.claims.includes(sc.id) || j.claims.includes("*")));
  const generating = sc.status === "generating";
  // a whole-film run shoots one scene at a time; the others are waiting their turn
  const queued = generating && !!job && job.claims.includes("*") && job.progress?.label !== `Shooting ${sc.id}`;
  const est = videoUsd(act.settings, sc.render.duration_s, null, sc.provider);
  const refImages = sc.refs_used.map((r) => p.assets.find((a) => a.id === r)?.image).filter(Boolean) as string[];

  return (
    <div className={cn("relative overflow-hidden rounded-xl bg-black", vertical ? "aspect-[9/16]" : "aspect-video")}>
      {take && (
        <video
          key={take.url}
          src={url(take.url)}
          poster={url(take.poster)}
          controls
          playsInline
          preload="metadata"
          className={cn("size-full object-contain transition-all duration-500", generating && "opacity-30 blur-sm")}
        />
      )}

      {!take && !generating && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-muted p-6 text-center">
          {refImages.length > 0 ? (
            <div className="flex -space-x-4">
              {refImages.slice(0, 3).map((src, i) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={src} src={url(src)} alt="" className="size-14 rounded-xl border-2 border-muted object-cover shadow-sm" style={{ rotate: `${(i - 1) * 6}deg` }} />
              ))}
            </div>
          ) : (
            <Clapperboard className="size-6 text-muted-foreground/50" />
          )}
          {sc.error ? (
            <p className="flex max-w-[90%] items-start gap-1.5 text-xs text-destructive">
              <TriangleAlert className="mt-px size-3.5 shrink-0" />
              <span className="line-clamp-4 text-left">{sc.error}</span>
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">Not shot yet</p>
          )}
          <Button size="sm" shape="pill" onClick={() => act.shoot(sc.id)} variant={sc.error ? "outline" : "default"}>
            {sc.error ? <RefreshCw /> : <Clapperboard />}
            {sc.error ? "Try again" : "Shoot"}
            <span className="text-xs font-normal opacity-60">≈{usd(est)}</span>
          </Button>
        </div>
      )}

      <AnimatePresence>
        {generating && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className={cn("absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-live", !queued && "shimmer", !take && "bg-muted")}
          >
            {queued ? (
              <>
                <span className="text-sm font-medium text-muted-foreground">Queued</span>
                <span className="text-center text-xs text-muted-foreground">Waiting for its turn in this run</span>
              </>
            ) : (
              <>
                <LiveBars className="h-5" bars={7} />
                <span className="text-sm font-medium">{job?.kind === "edit" ? "Applying fix" : "Rolling"}</span>
                {job && <JobProgress job={job} className="max-w-56" />}
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function TakeStrip({ p, sc, vertical }: { p: Project; sc: Scene; vertical: boolean }) {
  const act = useProjectActions(p);
  if (!sc.takes.length) return null;
  const est = videoUsd(act.settings, sc.render.duration_s, null, sc.provider);
  return (
    <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-thin">
      {sc.takes.map((t, i) => {
        const on = t.name === sc.selected;
        return (
          <Tip
            key={t.name}
            content={
              <span className="block space-y-0.5">
                <span className="block font-medium">Take {i + 1}{t.edited_from ? ` · fix of ${t.edited_from.replace(".mp4", "")}` : ""}</span>
                {t.edit && <span className="block opacity-80">“{t.edit.replace(" Keep everything else the same.", "")}”</span>}
                <span className="block opacity-70 tabular">{shortLabel(t.provider)} · {secs(t.duration_s)} · {t.resolution} · {usd(t.cost_usd)}</span>
              </span>
            }
          >
            <button
              onClick={() => !on && act.select(sc.id, t.name)}
              className={cn(
                "relative shrink-0 overflow-hidden rounded-lg bg-black ring-offset-2 ring-offset-card transition-all",
                vertical ? "h-20 w-[45px]" : "h-12 w-[85px]",
                on ? "ring-2 ring-foreground" : "opacity-60 hover:opacity-100",
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url(t.poster)} alt="" className="size-full object-cover" />
              <span className="absolute bottom-0.5 left-1 font-mono text-[10px] font-semibold text-white drop-shadow">{i + 1}{t.edited_from ? "✎" : ""}</span>
            </button>
          </Tip>
        );
      })}
      <Tip content={`Shoot another take · ≈${usd(est)}`}>
        <button
          onClick={() => act.shoot(sc.id)}
          disabled={sc.status === "generating"}
          className={cn("flex shrink-0 items-center justify-center rounded-lg border border-dashed text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground disabled:opacity-40", vertical ? "h-20 w-[45px]" : "h-12 w-[60px]")}
          aria-label="New take"
        >
          <Plus className="size-4" />
        </button>
      </Tip>
    </div>
  );
}

// ---------------------------------------------------------------- details

function Refs({ p, sc }: { p: Project; sc: Scene }) {
  const assets = sc.refs.map((r) => p.assets.find((a) => a.id === r)).filter(Boolean) as Asset[];
  if (!assets.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {assets.map((a) => (
        <Tip key={a.id} content={a.image ? `${a.id} is attached as a reference` : `${a.id} isn't painted yet — the clip would be shot without it`}>
          <div className={cn("flex items-center gap-2 rounded-full border py-0.5 pr-3 pl-0.5 text-xs", !a.image && "border-dashed border-live/50 text-live")}>
            {a.image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={url(a.image)} alt="" className="size-6 rounded-full object-cover" />
            ) : (
              <span className="flex size-6 items-center justify-center rounded-full bg-live/15">
                <TriangleAlert className="size-3" />
              </span>
            )}
            {a.name}
          </div>
        </Tip>
      ))}
    </div>
  );
}

function PromptPanel({ p, sc }: { p: Project; sc: Scene }) {
  const act = useProjectActions(p);
  const [open, setOpen] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [text, setText] = React.useState(sc.prompt);
  React.useEffect(() => { if (!editing) setText(sc.prompt); }, [sc.prompt, editing]);

  const save = async (value: string | null) => {
    if (await act.setPrompt(sc.id, value, sc.provider)) setEditing(false);
  };

  return (
    <div className="rounded-xl border bg-background/50">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-xs font-medium text-muted-foreground hover:text-foreground">
        <ChevronDown className={cn("size-3.5 transition-transform", !open && "-rotate-90")} />
        Prompt sent to {providerInfo(act.settings, sc.provider)?.label ?? "the video model"}
        {sc.overridden && <Badge tone="live" className="ml-1">custom</Badge>}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="space-y-2 px-3.5 pb-3.5">
              {editing ? (
                <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-48 font-mono text-xs leading-relaxed" autoFocus />
              ) : (
                <pre className="max-h-72 overflow-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground scrollbar-thin">{sc.prompt}</pre>
              )}
              <div className="flex gap-2">
                {editing ? (
                  <>
                    <Button size="sm" shape="pill" onClick={() => save(text === sc.default_prompt ? null : text)}>Save</Button>
                    <Button size="sm" variant="ghost" shape="pill" onClick={() => setEditing(false)}>Cancel</Button>
                  </>
                ) : (
                  <Button size="sm" variant="outline" shape="pill" onClick={() => setEditing(true)}>Edit</Button>
                )}
                {sc.overridden && !editing && (
                  <Button size="sm" variant="ghost" shape="pill" onClick={() => save(null)}>
                    <RotateCcw />
                    Use the plan&apos;s prompt
                  </Button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function FixComposer({ p, sc, take }: { p: Project; sc: Scene; take: Take }) {
  const act = useProjectActions(p);
  const [text, setText] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const busy = sc.status === "generating";
  // an edit goes to the model that made the take, at that take's resolution
  const est = videoUsd(act.settings, take.duration_s ?? sc.duration_s, take.resolution, take.provider, true);

  const send = async () => {
    if (!text.trim() || busy || sending) return;
    setSending(true);
    if (await act.fix(sc.id, take.name, text)) setText("");
    setSending(false);
  };

  return (
    <div className="mt-auto space-y-1.5">
      <div className="flex items-center gap-2 rounded-full border bg-background py-1 pr-1 pl-4 transition-shadow focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/30">
        <Wand2 className="size-4 shrink-0 text-muted-foreground" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={busy}
          placeholder="Describe a fix — e.g. make the snowfall heavier"
          className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70 disabled:opacity-50"
        />
        <Button size="icon-sm" shape="pill" onClick={send} disabled={!text.trim() || busy || sending} aria-label="Apply fix">
          {sending ? <Spinner /> : <ArrowUp />}
        </Button>
      </div>
      <p className="pl-4 text-[11px] text-muted-foreground">
        Edits {take.name.replace(".mp4", "").replace("_", " ")} and keeps everything else · ≈{usd(est)} · the original stays as a take
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- model choice

/** Short name for a provider: "Gemini", "Kling". */
function shortLabel(id: string) {
  return id === "gemini-omni" ? "Gemini" : id.charAt(0).toUpperCase() + id.slice(1);
}

/** Which video model shoots this scene. The settings default unless the scene picks another. */
function ModelPicker({ p, sc }: { p: Project; sc: Scene }) {
  const act = useProjectActions(p);
  const s = act.settings;
  const list = s?.providers ?? [];
  if (list.length < 2) return null;
  const busy = sc.status === "generating";
  const info = providerInfo(s, sc.provider);
  const mapped = s && sc.render.resolution !== s.resolution;
  return (
    <span className="flex items-center gap-1.5">
      <Segmented
        size="sm"
        value={sc.provider}
        onChange={(v) => act.setSceneProvider(sc.id, v === s?.video_provider ? null : v)}
        options={list.map((pr) => ({
          value: pr.id,
          label: shortLabel(pr.id),
          disabled: busy || !pr.configured,
          title: pr.configured ? `${pr.label} (${pr.model})` : `${pr.label}: ${pr.setup}`,
        }))}
      />
      {mapped && info && (
        <Tip content={`${info.label} doesn't offer ${s?.resolution}; it shoots at ${sc.render.resolution}`}>
          <Badge tone="outline" className="tabular">{sc.render.resolution}</Badge>
        </Tip>
      )}
    </span>
  );
}
