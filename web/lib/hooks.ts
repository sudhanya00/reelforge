"use client";

import { useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { fetcher, type AppState, type Influencer, type InfluencerList, type Job, type LibraryCharacter, type Video, type Project, type ProjectSummary, type ProviderInfo, type Resolution, type Settings } from "./api";

export function useAppState() {
  return useSWR<AppState>("/api/state", fetcher, { revalidateOnFocus: true });
}

export function useLibrary() {
  return useSWR<{ characters: LibraryCharacter[] }>("/api/library", fetcher);
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

/** Jobs for an influencer run under the pseudo-project "inf:<id>". */
export const infKey = (id: string) => `inf:${id}`;

export function useInfluencers() {
  const { running } = useJobs();
  return useSWR<InfluencerList>("/api/influencers", fetcher, {
    refreshInterval: running.some((j) => j.project?.startsWith("inf:")) ? 2500 : 0,
  });
}

export function useInfluencer(id: string | null) {
  const { running } = useJobs();
  const busy = !!id && running.some((j) => j.project === infKey(id));
  return useSWR<Influencer>(id ? `/api/influencers/${id}` : null, fetcher, {
    refreshInterval: busy ? 1500 : 0,
    keepPreviousData: true,
  });
}

export function useVideo(id: string | null, vid: string | null) {
  const { running } = useJobs();
  const busy = !!id && !!vid && running.some((j) => j.project === infKey(id) && j.claims.includes(vid));
  return useSWR<Video>(id && vid ? `/api/influencers/${id}/videos/${vid}` : null, fetcher, {
    refreshInterval: busy ? 1500 : 0,
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
export function useJobWatcher(
  onOpen: (project: string, tab?: string) => void,
  onOpenInfluencer: (id: string, tab?: string, video?: string) => void,
) {
  const { jobs } = useJobs();
  const { mutate } = useSWRConfig();
  const seen = useRef<Map<string, Job["status"]>>(new Map());
  const first = useRef(true);

  useEffect(() => {
    for (const j of jobs) {
      const before = seen.current.get(j.id);
      seen.current.set(j.id, j.status);
      if (first.current || before !== "running" || j.status === "running") continue;

      if (j.project?.startsWith("inf:") || j.kind === "design") {
        mutate((key) => typeof key === "string" && key.startsWith("/api/influencers"));
        if (j.kind === "design") continue; // the designer shows its own result
        const iid = j.project!.slice(4);
        const tab = j.kind === "identity" || j.kind === "place" ? "identity" : "videos";
        const video = j.kind === "script" ? (j.result?.video as string | undefined) : j.kind === "reel" || j.kind === "opening" ? j.claims[0] : undefined;
        if (j.status === "done") {
          toast.success(doneMessage(j), { action: { label: "Open", onClick: () => onOpenInfluencer(iid, tab, video) } });
        } else {
          toast.error(j.label + " failed", { description: j.error ?? undefined, duration: 12000 });
        }
        continue;
      }
      mutate("/api/projects");
      if (j.project) mutate(`/api/projects/${j.project}`);
      const project = j.project;
      if (j.status === "done") {
        const tab = ({ assets: "references", take: "scenes", edit: "scenes", review: "scenes", stitch: "final", produce: "final", film: "final", plan: "plan", direct: "plan" } as Partial<Record<Job["kind"], string>>)[j.kind];
        toast.success(doneMessage(j), {
          action: project ? { label: "Open", onClick: () => onOpen(project, tab) } : undefined,
        });
      } else {
        toast.error(j.label + " failed", { description: j.error ?? undefined, duration: 12000 });
      }
    }
    first.current = false;
  }, [jobs, mutate, onOpen, onOpenInfluencer]);
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
    case "review": return j.label.replace("Reviewing", "Review of") + " is ready";
    case "direct": return "The director has revised the plan";
    case "design": return "Influencer designed";
    case "identity": return j.label.replace("Painting", "Painted");
    case "script": return "The script is ready to edit";
    case "reel": return j.label.replace("Shooting", "Finished shooting");
    case "place": return j.label.replace("Painting", "Painted");
    case "opening": return "The opening frame is ready";
  }
}

// ---------------------------------------------------------------- estimates

export function providerInfo(s: Settings | undefined, id?: string | null) {
  return s?.providers.find((p) => p.id === (id ?? s.video_provider));
}

const RES_ORDER: Resolution[] = ["360p", "720p", "1080p", "4k"];

/** The requested resolution, or the nearest one the provider offers (Kling starts at 720p). */
export function resolutionFor(p: ProviderInfo | undefined, requested: Resolution): Resolution {
  if (!p || p.caps.resolutions.includes(requested)) return requested;
  const want = RES_ORDER.indexOf(requested);
  return [...p.caps.resolutions].sort(
    (a, b) => Math.abs(RES_ORDER.indexOf(a) - want) - Math.abs(RES_ORDER.indexOf(b) - want),
  )[0];
}

/** List price of `seconds` of video from a provider (default: the settings' one). */
export function videoUsd(s: Settings | undefined, seconds: number, res?: Resolution | null, provider?: string | null, edit = false) {
  const p = providerInfo(s, provider);
  if (!s || !p) return 0;
  const r = resolutionFor(p, res ?? s.resolution);
  return ((edit ? p.edit_price_per_s : p.price_per_s)[r] ?? 0) * seconds;
}

export function imageUsd(s: Settings | undefined, n = 1) {
  return s ? s.prices.image * n : 0;
}

// ---------------------------------------------------------------- progress

/**
 * How far along a job is. Generation APIs don't report progress, so each step is timed
 * against how long that kind of step usually takes (measured from past runs), capped at
 * 95% until it really finishes. Multi-step jobs add their done/total on top.
 */
export function useJobProgress(job: Job | undefined) {
  const now = useNow(!!job && job.status === "running", 500);
  const p = job?.progress;
  if (!job || !p) return null;
  if (job.status !== "running") return { fraction: 1, left: 0, slow: false, label: p.label, step: p.done, total: p.total };
  const elapsed = Math.max(0, now - p.step_started);
  const stepFrac = Math.min(0.95, elapsed / p.expected_s);
  const fraction = Math.min(0.99, (p.done + stepFrac) / p.total);
  const left = Math.max(0, p.expected_s - elapsed) + Math.max(0, p.total - p.done - 1) * p.expected_s;
  return { fraction, left, slow: elapsed > p.expected_s * 1.15, label: p.label, step: p.done, total: p.total };
}

export function leftText(pr: NonNullable<ReturnType<typeof useJobProgress>>) {
  if (pr.slow) return "taking longer than usual…";
  if (pr.left < 10) return "almost done";
  const m = Math.round(pr.left / 60);
  return pr.left < 90 ? `about ${Math.round(pr.left / 5) * 5}s left` : `about ${m} min left`;
}
