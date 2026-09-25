"use client";

import { leftText, useJobProgress, useNow } from "@/lib/hooks";
import type { Job } from "@/lib/api";
import { clock, cn } from "@/lib/utils";

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-current/15", className)} role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-current transition-[width] duration-700 ease-linear" style={{ width: `${Math.max(2, value * 100)}%` }} />
    </div>
  );
}

/** Bar + "1:12 · about 1 min left" (+ "2 of 8" for multi-step jobs). */
export function JobProgress({ job, className, showLabel = false }: { job: Job; className?: string; showLabel?: boolean }) {
  const pr = useJobProgress(job);
  const now = useNow(job.status === "running");
  if (!pr) return null;
  return (
    <div className={cn("w-full space-y-1.5", className)}>
      {showLabel && <p className="truncate text-sm font-medium">{pr.label}</p>}
      <ProgressBar value={pr.fraction} />
      <p className="flex justify-between gap-3 text-xs tabular opacity-80">
        <span>
          {clock(now - job.started)}
          {pr.total > 1 && ` · ${pr.step} of ${pr.total} done`}
        </span>
        <span>{leftText(pr)}</span>
      </p>
    </div>
  );
}
