"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, ClipboardCheck, RefreshCw, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, Tip } from "@/components/ui/primitives";
import { JobProgress } from "@/components/progress";
import { useJobs } from "@/lib/hooks";
import type { Project, Scene, Take } from "@/lib/api";
import { cn } from "@/lib/utils";

const VERDICT = {
  keep: { label: "Keep", tone: "ok" },
  fix: { label: "Fix", tone: "live" },
  reshoot: { label: "Reshoot", tone: "bad" },
} as const;

const REVIEW_USD = 0.05;

/** Jump the scene's player to a moment. */
function seek(sceneId: string, t: number) {
  const v = document.getElementById(`video-${sceneId}`) as HTMLVideoElement | null;
  if (!v) return;
  v.currentTime = t;
  v.pause();
  v.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

const mmss = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

export function ReviewPanel({
  p,
  sc,
  take,
  onReview,
  onUseFix,
}: {
  p: Project;
  sc: Scene;
  take: Take;
  onReview: () => void;
  onUseFix: (text: string) => void;
}) {
  const { running } = useJobs();
  const job = running.find((j) => j.project === p.id && j.claims.includes(`review:${sc.id}`));
  const r = take.review;
  const [advice, setAdvice] = React.useState(false);

  if (job)
    return (
      <div className="rounded-xl border bg-background/50 p-3.5 text-live">
        <p className="mb-2 flex items-center gap-2 text-xs font-medium">
          <ClipboardCheck className="size-3.5" /> Reviewing {take.name.replace(".mp4", "").replace("_", " ")}…
        </p>
        <JobProgress job={job} />
      </div>
    );

  if (!r)
    return (
      <div className="flex items-center gap-3 rounded-xl border border-dashed px-3.5 py-2.5">
        <ClipboardCheck className="size-4 shrink-0 text-muted-foreground" />
        <p className="flex-1 text-xs text-muted-foreground">
          Have Gemini watch this take against the brief and references: scores, timestamped issues and a suggested fix.
          {take.motion && take.motion.dead_s > 0 && (
            <span className="text-live"> The motion meter already found {take.motion.dead_s}s of frozen time.</span>
          )}
        </p>
        <Button size="sm" variant="outline" shape="pill" onClick={onReview}>
          Review <span className="text-xs font-normal opacity-60">≈${REVIEW_USD.toFixed(2)}</span>
        </Button>
      </div>
    );

  const v = VERDICT[r.verdict];
  const weak = Object.entries(r.scores).filter(([, s]) => s.score < 5).sort((a, b) => a[1].score - b[1].score);
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-3 rounded-xl border bg-background/50 p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={v.tone}>{v.label}</Badge>
        <span className="text-sm font-semibold tabular">{r.overall.toFixed(1)}</span>
        <span className="text-xs text-muted-foreground">/ 5</span>
        {r.dead_time_s > 0 && <Badge tone="outline" className="tabular">{r.dead_time_s}s dead</Badge>}
        <Tip content={`Review again · ≈$${REVIEW_USD.toFixed(2)}`}>
          <button onClick={onReview} className="ml-auto rounded-full p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Review again">
            <RefreshCw className="size-3.5" />
          </button>
        </Tip>
      </div>
      <p className="text-sm text-foreground/85">{r.summary}</p>

      {weak.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {weak.map(([k, s]) => (
            <Tip key={k} content={s.note}>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[11px] font-medium tabular",
                  s.score <= 2 ? "bg-destructive/12 text-destructive" : s.score === 3 ? "bg-live/15 text-live" : "bg-muted text-muted-foreground",
                )}
              >
                {k} {s.score}
              </span>
            </Tip>
          ))}
        </div>
      )}

      {r.issues.length > 0 && (
        <ul className="space-y-1">
          {r.issues.map((i, n) => (
            <li key={n}>
              <button onClick={() => seek(sc.id, i.t_start)} className="group flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-xs hover:bg-accent">
                <span className="shrink-0 font-mono text-muted-foreground group-hover:text-foreground">
                  {mmss(i.t_start)}–{mmss(i.t_end)}
                </span>
                <span
                  className={cn(
                    "shrink-0 font-medium",
                    i.severity === "fatal" ? "text-destructive" : i.severity === "major" ? "text-live" : "text-muted-foreground",
                  )}
                >
                  {i.severity}
                </span>
                <span className="text-foreground/85">{i.description}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {r.fix_instruction && (
        <div className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2">
          <Wand2 className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <p className="flex-1 text-xs">{r.fix_instruction}</p>
          <Button size="sm" variant="outline" shape="pill" className="h-7" onClick={() => onUseFix(r.fix_instruction)}>
            Use this fix
          </Button>
        </div>
      )}

      {r.prompt_advice && (
        <div>
          <button onClick={() => setAdvice(!advice)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronDown className={cn("size-3.5 transition-transform", !advice && "-rotate-90")} />
            How to reshoot it
          </button>
          <AnimatePresence initial={false}>
            {advice && (
              <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden pt-1.5 pl-5 text-xs text-foreground/80">
                {r.prompt_advice}
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}

