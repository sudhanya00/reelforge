"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ThemeProvider, useTheme } from "next-themes";
import { SWRConfig } from "swr";
import { Toaster } from "sonner";
import { motion, AnimatePresence } from "motion/react";
import { Activity, Check, ChevronRight, Clapperboard, Moon, Settings2, Sun, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, LiveBars, Popover, PopoverContent, PopoverTrigger, Spinner, Tip, TooltipProvider } from "@/components/ui/primitives";
import { ConfirmSpendProvider } from "@/components/confirm";
import { JobProgress } from "@/components/progress";
import { SettingsDialog } from "@/components/settings";
import { useAppState, useJobs, useJobWatcher, useNow, useProject } from "@/lib/hooks";
import type { Job } from "@/lib/api";
import { ago, clock, cn, usd } from "@/lib/utils";

// ---------------------------------------------------------------- routing (single static page)

export type Tab = "plan" | "references" | "scenes" | "final";
export const TABS: Tab[] = ["plan", "references", "scenes", "final"];

export function useRoute() {
  const params = useSearchParams();
  const router = useRouter();
  const project = params.get("project");
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "plan") as Tab;
  const go = React.useCallback(
    (p: string | null, t?: string) => {
      const q = new URLSearchParams();
      if (p) q.set("project", p);
      if (p && t) q.set("tab", t);
      router.push(q.size ? `/?${q}` : "/", { scroll: false });
      window.scrollTo({ top: 0 });
    },
    [router],
  );
  return { project, tab, go };
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

export function Nav() {
  const { project, tab, go } = useRoute();
  const { data: p } = useProject(project);
  useJobWatcher(go);

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
        <button onClick={() => go(null)} className="group flex items-center gap-2 rounded-full pr-2 outline-none">
          <span className="flex size-7 items-center justify-center rounded-lg bg-foreground text-background transition-transform group-hover:-rotate-6">
            <Clapperboard className="size-4" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">ReelForge</span>
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

        <div className="ml-auto flex items-center gap-1">
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
  if (data.fake) notes.push(<>Demo mode · a fake model is used and nothing is billed</>);
  if (!data.ffmpeg) notes.push(<>ffmpeg wasn&apos;t found, so continuous scenes, posters and stitching won&apos;t work. Install it and relaunch.</>);
  if (!notes.length) return null;
  return (
    <div className={cn("border-b text-center text-xs", data.fake && data.ffmpeg ? "bg-muted/60 text-muted-foreground" : "bg-live/10 text-foreground")}>
      {notes.map((n, i) => (
        <div key={i} className="flex items-center justify-center gap-1.5 py-1.5">
          {!data.fake || !data.ffmpeg ? <TriangleAlert className="size-3.5 text-live" /> : null}
          {n}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- jobs

function JobsButton() {
  const { jobs, running } = useJobs();
  const { go } = useRoute();
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
            <JobRow key={j.id} job={j} onOpen={() => j.project && go(j.project, tabFor(j))} />
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

const tabFor = (j: Job) =>
  ({ assets: "references", take: "scenes", edit: "scenes", review: "scenes", stitch: "final", produce: "final", film: "final", plan: "plan" })[j.kind];

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
            {job.project ?? "new film"} · {job.status === "running" ? clock(elapsed) : `${clock(elapsed)} · ${ago(job.finished ?? job.started)}`}
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
