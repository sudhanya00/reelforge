"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, Clapperboard, Pause, Plus, Scissors, ShieldCheck, Trash2 } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Badge, InlineText, Tip } from "@/components/ui/primitives";
import { JobProgress } from "@/components/progress";
import { useJobs } from "@/lib/hooks";
import type { Beat, Plan, PlanScene, Project } from "@/lib/api";
import { cn } from "@/lib/utils";

const fmt = (t: number) => `${Number(t.toFixed(1))}`;

// ---------------------------------------------------------------- plan: beats editor

export function BeatsEditor({ sc, onChange }: { sc: PlanScene; onChange: (beats: Beat[], multi?: boolean) => void }) {
  const beats = sc.beats ?? [];
  const set = (i: number, patch: Partial<Beat>) => onChange(beats.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const add = () => {
    const end = beats.at(-1)?.t_end ?? 0;
    onChange([...beats, { t_start: end, t_end: end + 2, action: "", camera: "" }]);
  };
  const total = beats.at(-1)?.t_end ?? 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        Beats
        <span className="tabular font-normal">· {fmt(total)}s</span>
        <button
          onClick={() => onChange(beats, !sc.multi_shot)}
          className={cn(
            "ml-auto flex items-center gap-1 rounded-full border px-2 py-0.5 font-normal transition-colors",
            sc.multi_shot ? "border-foreground/30 text-foreground" : "hover:text-foreground",
          )}
          title="Let this clip cut between shots (Omni and Kling both support cuts inside one generation)"
        >
          <Scissors className="size-3" /> {sc.multi_shot ? "Cuts inside this clip" : "One continuous shot"}
        </button>
      </div>
      <BeatStrip sc={sc} />
      <ol className="space-y-1.5">
        {beats.map((b, i) => (
          <li key={i} className="group grid grid-cols-[92px_1fr_auto] items-start gap-2 rounded-lg border bg-background/50 px-2.5 py-2">
            <div className="flex items-center gap-1 pt-1 font-mono text-[11px] text-muted-foreground">
              <input
                type="number"
                step={0.5}
                min={0}
                value={b.t_start}
                onChange={(e) => set(i, { t_start: Number(e.target.value) })}
                className="w-9 bg-transparent text-right tabular outline-none focus:text-foreground"
              />
              –
              <input
                type="number"
                step={0.5}
                min={0}
                value={b.t_end}
                onChange={(e) => set(i, { t_end: Number(e.target.value) })}
                className="w-9 bg-transparent tabular outline-none focus:text-foreground"
              />
              s
            </div>
            <div className="min-w-0">
              <InlineText value={b.action} onChange={(v) => set(i, { action: v })} placeholder="What visibly changes" className="text-sm" />
              <InlineText value={b.camera} onChange={(v) => set(i, { camera: v })} placeholder="Camera" className="text-xs text-muted-foreground" />
            </div>
            <div className="flex items-center gap-0.5 pt-0.5">
              <Tip content={b.hold ? "A deliberate hold (click to unmark)" : "Mark as a deliberate hold"}>
                <button onClick={() => set(i, { hold: !b.hold })} className={cn("rounded p-1", b.hold ? "text-live" : "text-muted-foreground/40 hover:text-foreground")}>
                  <Pause className="size-3.5" />
                </button>
              </Tip>
              {sc.multi_shot && i > 0 && (
                <Tip content={b.cut ? "A new shot starts here" : "Cut to a new shot here"}>
                  <button onClick={() => set(i, { cut: !b.cut })} className={cn("rounded p-1", b.cut ? "text-foreground" : "text-muted-foreground/40 hover:text-foreground")}>
                    <Scissors className="size-3.5" />
                  </button>
                </Tip>
              )}
              <button onClick={() => onChange(beats.filter((_, j) => j !== i))} className="rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive" aria-label="Remove beat">
                <Trash2 className="size-3.5" />
              </button>
            </div>
          </li>
        ))}
      </ol>
      <button onClick={add} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <Plus className="size-3.5" /> Add a beat
      </button>
      {sc.risks && sc.risks.length > 0 && <Risks risks={sc.risks} />}
    </div>
  );
}

export function Risks({ risks }: { risks: NonNullable<PlanScene["risks"]> }) {
  return (
    <div className="space-y-1">
      {risks.map((r, i) => (
        <p key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-ok" />
          <span>
            <span className="text-foreground/80">{r.what}</span> — {r.handling}
          </span>
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- the clip as a strip of beats

export function BeatStrip({ sc, className }: { sc: PlanScene; className?: string }) {
  const beats = sc.beats ?? [];
  if (!beats.length) return null;
  const total = beats.at(-1)!.t_end || 1;
  return (
    <div className={cn("flex h-7 w-full gap-[2px] overflow-hidden rounded-md", className)}>
      {beats.map((b, i) => (
        <Tip key={i} content={<span className="block max-w-72"><b className="tabular">{fmt(b.t_start)}–{fmt(b.t_end)}s</b> {b.action}{b.camera ? ` · ${b.camera}` : ""}</span>}>
          <div
            style={{ flexGrow: Math.max(0.3, b.t_end - b.t_start), flexBasis: 0 }}
            className={cn(
              "relative flex min-w-0 items-center px-1.5 text-[10px] font-medium",
              b.hold ? "bg-muted [background-image:repeating-linear-gradient(135deg,transparent_0_4px,color-mix(in_oklch,var(--foreground)_8%,transparent)_4px_6px)]" : "bg-foreground/10",
              b.cut && sc.multi_shot && "border-l-2 border-foreground",
            )}
          >
            <span className="truncate text-foreground/70">{b.action}</span>
          </div>
        </Tip>
      ))}
      <span className="sr-only">{fmt(total)} seconds</span>
    </div>
  );
}

// ---------------------------------------------------------------- the director's notes

export function DirectorNotes({ p, plan, dirty, onDirect }: { p: Project; plan: Plan; dirty: boolean; onDirect: () => void }) {
  const { running } = useJobs();
  const job = running.find((j) => j.project === p.id && j.kind === "direct");
  const notes = plan.director_notes ?? [];
  const [open, setOpen] = React.useState(true);
  if (plan.planner !== "v2" && !notes.length && !job)
    return (
      <div className="flex items-center gap-3 rounded-xl border border-dashed px-4 py-3">
        <Clapperboard className="size-4 shrink-0 text-muted-foreground" />
        <p className="flex-1 text-sm text-muted-foreground">
          This plan was written before the director existed. Let the director time every scene into beats and fix what
          commonly goes wrong, before you spend on video.
        </p>
        <Button size="sm" variant="outline" shape="pill" disabled={dirty} onClick={onDirect} title={dirty ? "Save your changes first" : undefined}>
          Direct it <span className="text-xs font-normal opacity-60">≈$0.20</span>
        </Button>
      </div>
    );
  return (
    <div className="rounded-xl border bg-card">
      <div className="flex items-center gap-3 px-4 py-3">
        <button onClick={() => setOpen(!open)} className="flex flex-1 items-center gap-2 text-left text-sm font-medium">
          <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", !open && "-rotate-90")} />
          Director&apos;s notes
          <Badge tone="outline">{notes.length} change{notes.length === 1 ? "" : "s"}</Badge>
        </button>
        {job ? (
          <JobProgress job={job} className="max-w-60 text-live" />
        ) : (
          <Tip content={dirty ? "Save your changes first" : "Review the current plan again (after your edits)"}>
            <span>
              <Button size="sm" variant="ghost" shape="pill" disabled={dirty} onClick={onDirect}>
                Direct again <span className="text-xs font-normal opacity-60">≈$0.20</span>
              </Button>
            </span>
          </Tip>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && notes.length > 0 && (
          <motion.ul initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-t">
            {notes.map((n, i) => (
              <li key={i} className="flex gap-3 px-4 py-2.5 text-sm">
                <span className="w-10 shrink-0 font-mono text-xs text-muted-foreground">{n.scene || "film"}</span>
                <span>
                  {n.change} <span className="text-muted-foreground">— {n.reason}</span>
                </span>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
