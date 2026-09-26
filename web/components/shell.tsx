"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ThemeProvider, useTheme } from "next-themes";
import { SWRConfig } from "swr";
import { Toaster } from "sonner";
import { motion, AnimatePresence } from "motion/react";
import { Activity, Check, ChevronRight, Clapperboard, Film, Moon, Settings2, Sun, TriangleAlert, UserRound } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Badge, LiveBars, Popover, PopoverContent, PopoverTrigger, Segmented, Spinner, Tip, TooltipProvider } from "@/components/ui/primitives";
import { ConfirmSpendProvider } from "@/components/confirm";
import { JobProgress } from "@/components/progress";
import { SettingsDialog } from "@/components/settings";
import { useAppState, useInfluencer, useJobs, useJobWatcher, useNow, useProject } from "@/lib/hooks";
import type { Job } from "@/lib/api";
import { ago, clock, cn, usd } from "@/lib/utils";

// ---------------------------------------------------------------- routing (single static page)

export type Tab = "plan" | "references" | "scenes" | "final";
export const TABS: Tab[] = ["plan", "references", "scenes", "final"];

export type Mode = "films" | "influencers";
export type InfTab = "identity" | "videos";

export function useRoute() {
  const params = useSearchParams();
  const router = useRouter();
  const project = params.get("project");
  const influencer = params.get("influencer");
  const video = params.get("video");
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "plan") as Tab;
  const infTab: InfTab = params.get("tab") === "videos" || video ? "videos" : "identity";
  const mode: Mode = influencer || params.get("mode") === "influencers" ? "influencers" : "films";
  const push = React.useCallback(
    (q: URLSearchParams) => {
      router.push(q.size ? `/?${q}` : "/", { scroll: false });
      window.scrollTo({ top: 0 });
    },
    [router],
  );
  const go = React.useCallback(
    (p: string | null, t?: string) => {
      const q = new URLSearchParams();
      if (p) q.set("project", p);
      if (p && t) q.set("tab", t);
      push(q);
    },
    [push],
  );
  /** An influencer's page (null: the influencers home). */
  const goInf = React.useCallback(
    (id: string | null, t?: string, v?: string) => {
      const q = new URLSearchParams();
      if (!id) q.set("mode", "influencers");
      else {
        q.set("influencer", id);
        if (t) q.set("tab", t);
        if (v) q.set("video", v);
      }
      push(q);
    },
    [push],
  );
  const goMode = React.useCallback((m: Mode) => (m === "films" ? go(null) : goInf(null)), [go, goInf]);
  return { project, tab, go, influencer, infTab, video, goInf, mode, goMode };
}

// ---------------------------------------------------------------- providers

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <SWRConfig value={{ revalidateOnFocus: false, shouldRetryOnError: true, errorRetryInterval: 3000 }}>
        <TooltipProvider>
          <ConfirmSpendProvider>{children}</ConfirmSpendProvider>
          {/* bottom-right: clear of the nav tabs and the centred action bar */}
          <Toaster position="bottom-right" richColors closeButton theme="system" />
        </TooltipProvider>
      </SWRConfig>
    </ThemeProvider>
  );
}

// ---------------------------------------------------------------- nav

const TAB_LABEL: Record<Tab, string> = { plan: "Plan", references: "References", scenes: "Scenes", final: "Final cut" };

function PillTabs<V extends string>({ value, options, onChange }: { value: V; options: { value: V; label: React.ReactNode; extra?: React.ReactNode }[]; onChange: (v: V) => void }) {
  return (
    <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center rounded-full bg-muted p-0.5 lg:flex">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "relative flex h-8 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors",
            value === o.value ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {value === o.value && (
            <motion.span
              layoutId="tab-pill"
              className="absolute inset-0 rounded-full bg-background shadow-sm dark:bg-accent"
              transition={{ type: "spring", bounce: 0.15, duration: 0.45 }}
            />
          )}
          <span className="relative flex items-center gap-1.5 [&_svg]:size-3.5">{o.label}</span>
          {o.extra}
        </button>
      ))}
    </nav>
  );
}

export function Nav() {
  const { project, tab, go, influencer, infTab, goInf, mode, goMode } = useRoute();
  const { data: p } = useProject(project);
  const { data: inf } = useInfluencer(influencer);
  useJobWatcher(go, goInf);

  const counts: Partial<Record<Tab, [number, number]>> = p
    ? {
        references: [p.assets.filter((a) => a.image).length, p.assets.length],
        scenes: [p.scenes.filter((s) => s.takes.length).length, p.scenes.length],
      }
    : {};

  return (
    <>
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/75 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 px-4">
        <button onClick={() => goMode(mode)} className="group flex items-center gap-2 rounded-full pr-2 outline-none">
          <span className="flex size-7 items-center justify-center rounded-lg bg-foreground text-background transition-transform group-hover:-rotate-6">
            <Clapperboard className="size-4" />
          </span>
          <span className="font-display text-[21px] leading-none">ReelForge</span>
        </button>

        {project && p && (
          <>
            <ChevronRight className="size-4 shrink-0 text-muted-foreground/50" />
            <span className="max-w-[260px] truncate text-sm font-medium">{p.plan.title}</span>
            <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center rounded-full bg-muted p-0.5 lg:flex">
              {TABS.map((t) => {
                const c = counts[t];
                const done = t === "final" ? !!p.final : c ? c[0] === c[1] && c[1] > 0 : t === "plan";
                return (
                  <button
                    key={t}
                    onClick={() => go(project, t)}
                    className={cn(
                      "relative flex h-8 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors",
                      tab === t ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {tab === t && (
                      <motion.span
                        layoutId="tab-pill"
                        className="absolute inset-0 rounded-full bg-background shadow-sm dark:bg-accent"
                        transition={{ type: "spring", bounce: 0.15, duration: 0.45 }}
                      />
                    )}
                    <span className="relative">{TAB_LABEL[t]}</span>
                    {c && !done && <span className="relative tabular text-xs text-muted-foreground">{c[0]}/{c[1]}</span>}
                    {done && <Check className="relative size-3.5 text-ok" />}
                  </button>
                );
              })}
            </nav>
          </>
        )}

        {!project && !influencer && (
          <div className="md:absolute md:left-1/2 md:-translate-x-1/2">
            <Segmented<Mode>
              value={mode}
              onChange={goMode}
              options={[
                { value: "films", label: <><Film />Films</> },
                { value: "influencers", label: <><UserRound />Influencers</> },
              ]}
            />
          </div>
        )}

        {influencer && inf && (
          <>
            <ChevronRight className="hidden size-4 shrink-0 text-muted-foreground/50 sm:block" />
            <button onClick={() => goInf(null)} className="hidden text-sm text-muted-foreground hover:text-foreground sm:block">
              Influencers
            </button>
            <ChevronRight className="size-4 shrink-0 text-muted-foreground/50" />
            <span className="min-w-0 max-w-[200px] truncate text-sm font-medium">{inf.profile.name}</span>
            <PillTabs<InfTab>
              value={infTab}
              onChange={(t) => goInf(influencer, t)}
              options={[
                {
                  value: "identity",
                  label: "Identity",
                  extra:
                    inf.identity_done === inf.identity_total ? (
                      <Check className="relative size-3.5 text-ok" />
                    ) : (
                      <span className="relative tabular text-xs text-muted-foreground">{inf.identity_done}/{inf.identity_total}</span>
                    ),
                },
                {
                  value: "videos",
                  label: "Videos",
                  extra: inf.videos_count ? <span className="relative tabular text-xs text-muted-foreground">{inf.videos_count}</span> : null,
                },
              ]}
            />
          </>
        )}

        <div className="ml-auto flex items-center gap-1">
          {influencer && inf && (
            <Tip content="Spent on this influencer so far: identity pack, scripts and videos">
              <span className="mr-1 hidden items-center rounded-full border px-2.5 py-1 text-xs font-medium tabular text-muted-foreground sm:flex">
                {usd(inf.cost_usd)}
              </span>
            </Tip>
          )}
          {p && (
            <Tip content={`Spent on this film so far · ${p.costs.calls} generation calls`}>
              <span className="mr-1 hidden items-center rounded-full border px-2.5 py-1 text-xs font-medium tabular text-muted-foreground sm:flex">
                {usd(p.costs.usd)}
              </span>
            </Tip>
          )}
          <JobsButton />
          <SettingsDialog>
            <Button variant="ghost" size="icon" shape="pill" aria-label="Settings">
              <Settings2 />
            </Button>
          </SettingsDialog>
          <ThemeToggle />
        </div>
      </div>
    </header>
    {/* outside the sticky header, so the header keeps a fixed height for sticky content below */}
    <SetupWarnings />
    </>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  const dark = mounted && resolvedTheme === "dark";
  return (
    <Tip content={dark ? "Light mode" : "Dark mode"}>
      <Button variant="ghost" size="icon" shape="pill" onClick={() => setTheme(dark ? "light" : "dark")} aria-label="Toggle theme">
        {dark ? <Sun /> : <Moon />}
      </Button>
    </Tip>
  );
}

function SetupWarnings() {
  const { data } = useAppState();
  if (!data) return null;
  const notes: React.ReactNode[] = [];
  if (data.stale) notes.push(<>ReelForge was updated while it was running. Restart it (close its window and run ReelForge.bat) to use the new version.</>);
  if (data.fake) notes.push(<>Demo mode · a fake model is used and nothing is billed</>);
  if (!data.ffmpeg) notes.push(<>ffmpeg wasn&apos;t found, so continuous scenes, posters and stitching won&apos;t work. Install it and relaunch.</>);
  if (!notes.length) return null;
  return (
    <div className={cn("border-b text-center text-xs", data.fake && data.ffmpeg && !data.stale ? "bg-muted/60 text-muted-foreground" : "bg-live/10 text-foreground")}>
      {notes.map((n, i) => (
        <div key={i} className="flex items-center justify-center gap-1.5 py-1.5">
          {!data.fake || !data.ffmpeg || data.stale ? <TriangleAlert className="size-3.5 text-live" /> : null}
          {n}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- jobs

function JobsButton() {
  const { jobs, running } = useJobs();
  const { go, goInf } = useRoute();
  const open = (j: Job) => {
    if (j.project === "products") goInf(null);
    else if (j.project?.startsWith("inf:"))
      goInf(j.project.slice(4), j.kind === "identity" || j.kind === "place" ? "identity" : "videos", ["reel", "opening", "export"].includes(j.kind) ? j.claims[0] : undefined);
    else if (j.project) go(j.project, tabFor(j));
  };
  return (
    <Popover>
      <Tip content={running.length ? `${running.length} running` : "Activity"}>
        <PopoverTrigger asChild>
          <Button variant="ghost" shape="pill" size={running.length ? "sm" : "icon"} aria-label="Activity" className={cn(running.length && "px-3 text-live")}>
            {running.length ? (
              <>
                <LiveBars />
                <span className="tabular text-xs font-semibold">{running.length}</span>
              </>
            ) : (
              <Activity />
            )}
          </Button>
        </PopoverTrigger>
      </Tip>
      <PopoverContent className="w-96">
        <div className="border-b px-4 py-3 text-sm font-semibold">Activity</div>
        <div className="max-h-[60vh] overflow-y-auto p-2 scrollbar-thin">
          {jobs.length === 0 && <p className="px-2 py-6 text-center text-sm text-muted-foreground">Nothing has run yet.</p>}
          {jobs.map((j) => (
            <JobRow key={j.id} job={j} onOpen={() => open(j)} />
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

const tabFor = (j: Job) =>
  ({ assets: "references", take: "scenes", edit: "scenes", review: "scenes", stitch: "final", produce: "final", film: "final", plan: "plan", direct: "plan", export: "final" } as Partial<Record<Job["kind"], string>>)[j.kind];

function JobRow({ job, onOpen }: { job: Job; onOpen: () => void }) {
  const [open, setOpen] = React.useState(false);
  const now = useNow(job.status === "running");
  const elapsed = (job.finished ?? now) - job.started;
  return (
    <div className="rounded-lg px-2 py-2 hover:bg-accent/60">
      <button className="flex w-full items-center gap-2.5 text-left" onClick={() => setOpen(!open)}>
        <span className="flex size-6 shrink-0 items-center justify-center">
          {job.status === "running" ? (
            <Spinner className="text-live" />
          ) : job.status === "done" ? (
            <Check className="size-4 text-ok" />
          ) : (
            <TriangleAlert className="size-4 text-destructive" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{job.label}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {job.project?.startsWith("inf:") ? job.project.slice(4) : (job.project ?? (job.kind === "design" || job.kind === "describe" ? "influencers" : "new film"))} · {job.status === "running" ? clock(elapsed) : `${clock(elapsed)} · ${ago(job.finished ?? job.started)}`}
          </span>
        </span>
        {job.project && (
          <Badge tone="outline" className="cursor-pointer hover:text-foreground" onClick={(e) => (e.stopPropagation(), onOpen())}>
            Open
          </Badge>
        )}
      </button>
      {job.status === "running" && job.progress && <JobProgress job={job} className="mt-2 pl-8 text-live" />}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            {job.error && <p className="mt-2 ml-8 rounded-md bg-destructive/10 px-2 py-1.5 text-xs text-destructive">{job.error}</p>}
            {job.logs.length > 0 && (
              <pre className="mt-2 ml-8 max-h-48 overflow-auto rounded-md bg-muted px-2 py-1.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground scrollbar-thin">
                {job.logs.join("\n")}
              </pre>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
