"use client";

import { useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { fetcher, type AppState, type Job, type Project, type ProjectSummary, type Resolution, type Settings } from "./api";

export function useAppState() {
  return useSWR<AppState>("/api/state", fetcher, { revalidateOnFocus: true });
}

export function useJobs() {
  const r = useSWR<Job[]>("/api/jobs", fetcher, {
    refreshInterval: (data) => (data?.some((j) => j.status === "running") ? 1200 : 4000),
  });
  return { ...r, jobs: r.data ?? [], running: (r.data ?? []).filter((j) => j.status === "running") };
}

export function useProjects() {
  const { running } = useJobs();
  return useSWR<ProjectSummary[]>("/api/projects", fetcher, {
    refreshInterval: running.length ? 2500 : 0,
  });
}

export function useProject(id: string | null) {
  const { running } = useJobs();
  const busy = running.some((j) => j.project === id);
  return useSWR<Project>(id ? `/api/projects/${id}` : null, fetcher, {
    refreshInterval: busy ? 1500 : 0,
    keepPreviousData: true,
  });
}

/** A clock that re-renders every `ms` while `on` is true. */
export function useNow(on = true, ms = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => setNow(Date.now() / 1000), ms);
    return () => clearInterval(t);
  }, [on, ms]);
  return now;
}

/** Toast when jobs finish, and refresh the data they changed. Mounted once in the shell. */
export function useJobWatcher(onOpen: (project: string, tab?: string) => void) {
  const { jobs } = useJobs();
  const { mutate } = useSWRConfig();
  const seen = useRef<Map<string, Job["status"]>>(new Map());
  const first = useRef(true);

  useEffect(() => {
    for (const j of jobs) {
      const before = seen.current.get(j.id);
      seen.current.set(j.id, j.status);
      if (first.current || before !== "running" || j.status === "running") continue;

      mutate("/api/projects");
      if (j.project) mutate(`/api/projects/${j.project}`);
      const project = j.project;
      if (j.status === "done") {
        const tab = { assets: "references", take: "scenes", edit: "scenes", stitch: "final", produce: "final", film: "final", plan: "plan" }[j.kind];
        toast.success(doneMessage(j), {
          action: project ? { label: "Open", onClick: () => onOpen(project, tab) } : undefined,
        });
      } else {
        toast.error(j.label + " failed", { description: j.error ?? undefined, duration: 12000 });
      }
    }
    first.current = false;
  }, [jobs, mutate, onOpen]);
}

function doneMessage(j: Job) {
  switch (j.kind) {
    case "plan": return "The plan is ready";
    case "film": return "Your film is done";
    case "assets": return j.label.replace("Painting", "Painted");
    case "take": return j.label.replace("Shooting", "New take of") + " is ready";
    case "edit": return j.label.replace("Fixing", "Fixed take of") + " is ready";
    case "stitch": return "Final cut stitched";
    case "produce": return "Everything is made";
  }
}

// ---------------------------------------------------------------- estimates

export function videoUsd(s: Settings | undefined, seconds: number, res?: Resolution | null) {
  if (!s) return 0;
  return (s.prices.video_per_s[res ?? s.resolution] ?? 0) * seconds;
}

export function imageUsd(s: Settings | undefined, n = 1) {
  return s ? s.prices.image * n : 0;
}
