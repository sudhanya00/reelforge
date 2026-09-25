"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { ArrowRight, Clapperboard, FolderOpen, Trash2, RectangleHorizontal, RectangleVertical, Scissors, Sparkles, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, Kbd, LiveBars, Spinner, Tip } from "@/components/ui/primitives";
import { useRoute, type Tab } from "@/components/shell";
import { leftText, useJobProgress, useJobs, useProject } from "@/lib/hooks";
import type { Job } from "@/lib/api";
import type { Plan, Project } from "@/lib/api";
import { cn, plural, secs, usd } from "@/lib/utils";
import { useDeleteFilm, useProjectActions } from "./actions";
import { PlanView } from "./PlanView";
import { ReferencesView } from "./ReferencesView";
import { ScenesView } from "./ScenesView";
import { FinalView } from "./FinalView";

export function Workspace({ id }: { id: string }) {
  const { tab, go } = useRoute();
  const { data: p, error } = useProject(id);
  const [draft, setDraft] = React.useState<Plan | null>(null);

  if (error && !p)
    return (
      <div className="mx-auto mt-24 max-w-md text-center">
        <p className="font-medium">This film couldn&apos;t be opened.</p>
        <p className="mt-1 text-sm text-muted-foreground">{String(error.message)}</p>
        <Button className="mt-6" variant="outline" shape="pill" onClick={() => go(null)}>
          Back to films
        </Button>
      </div>
    );
  if (!p)
    return (
      <div className="flex grow items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" />
      </div>
    );

  const totalS = p.plan.scenes.reduce((t, s) => t + s.duration_s, 0);
  return (
    <div className="mx-auto w-full max-w-[1200px] px-6 pt-10 pb-40">
      <Header p={p} totalS={totalS} />
      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.2 }} className="mt-10">
          {tab === "plan" && <PlanView p={p} draft={draft ?? p.plan} setDraft={setDraft} />}
          {tab === "references" && <ReferencesView p={p} />}
          {tab === "scenes" && <ScenesView p={p} />}
          {tab === "final" && <FinalView p={p} />}
        </motion.div>
      </AnimatePresence>
      <ActionBar p={p} tab={tab} draft={draft} setDraft={setDraft} />
    </div>
  );
}

function Header({ p, totalS }: { p: Project; totalS: number }) {
  const a = useProjectActions(p);
  const del = useDeleteFilm();
  const { go } = useRoute();
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge tone="outline">
            {p.orientation === "9:16" ? <RectangleVertical /> : <RectangleHorizontal />}
            {p.orientation}
          </Badge>
          <Badge tone="outline">
            {plural(p.plan.scenes.length, "scene")} · {secs(totalS)}
          </Badge>
          <Badge tone="outline">
            {plural(p.plan.characters.length, "character")} · {plural(p.plan.environments.length, "location")}
          </Badge>
        </div>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">{p.plan.title}</h1>
        <p className="mt-2 max-w-3xl text-muted-foreground">{p.plan.logline}</p>
      </div>
      <div className="flex gap-1">
        <Tip content="Open the project folder">
          <Button variant="ghost" size="icon" shape="pill" onClick={a.reveal} aria-label="Open folder">
            <FolderOpen />
          </Button>
        </Tip>
        <Tip content={p.busy.length ? "Can't delete while something is generating" : "Delete film"}>
          <span>
            <Button
              variant="ghost"
              size="icon"
              shape="pill"
              disabled={p.busy.length > 0}
              onClick={() => del(p.id, p.plan.title, () => go(null))}
              aria-label="Delete film"
              className="hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 />
            </Button>
          </span>
        </Tip>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- floating action bar

function ActionBar({ p, tab, draft, setDraft }: { p: Project; tab: Tab; draft: Plan | null; setDraft: (p: Plan | null) => void }) {
  const a = useProjectActions(p);
  const { go } = useRoute();
  const { running } = useJobs();
  const mine = running.filter((j) => j.project === p.id);
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(p.plan);
  const [saving, setSaving] = React.useState(false);

  const save = React.useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    if (await a.savePlan(draft)) setDraft(null);
    setSaving(false);
  }, [a, draft, setDraft]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s" && dirty) {
        e.preventDefault();
        save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, save]);

  const busyAll = p.busy.includes("*");
  const allShot = p.scenes.every((s) => s.takes.length);
  const stale = !!p.final && p.scenes.some((s) => s.takes.find((t) => t.name === s.selected && t.created > (p.final?.updated ?? 0)));

  let primary: React.ReactNode = null;
  if (dirty) {
    primary = (
      <>
        <span className="px-2 text-sm text-muted-foreground">Unsaved changes</span>
        <Button variant="ghost" size="sm" shape="pill" onClick={() => setDraft(null)} disabled={saving}>
          Discard
        </Button>
        <Button size="sm" shape="pill" onClick={save} disabled={saving}>
          {saving ? <Spinner /> : null}Save <Kbd className="border-primary-foreground/20 bg-primary-foreground/10 text-primary-foreground/70">Ctrl S</Kbd>
        </Button>
      </>
    );
  } else if (
    ((tab === "plan" || tab === "references") && p.assets.some((x) => x.status === "generating")) ||
    ((tab === "scenes" || tab === "final") && busyAll)
  ) {
    primary = null; // the live status says what's happening; the next step can wait
  } else if (tab === "plan" || tab === "references") {
    primary = a.missingRefs.length ? (
      <Button size="sm" shape="pill" onClick={a.paintMissing} disabled={busyAll}>
        <Wand2 />
        Paint {plural(a.missingRefs.length, "reference")}
        <Cost usd={a.settings ? a.settings.prices.image * a.missingRefs.length : 0} />
      </Button>
    ) : (
      <Button size="sm" shape="pill" onClick={() => go(p.id, tab === "plan" ? "references" : "scenes")}>
        {tab === "plan" ? "Review references" : "Shoot scenes"}
        <ArrowRight />
      </Button>
    );
  } else if (tab === "scenes" || (tab === "final" && !allShot)) {
    primary = a.missingScenes.length || a.missingRefs.length ? (
      <Button size="sm" shape="pill" onClick={a.produce} disabled={busyAll || mine.length > 0}>
        <Sparkles />
        Make everything missing
        <Cost usd={a.remainingUsd} />
      </Button>
    ) : (
      <Button size="sm" shape="pill" onClick={() => go(p.id, "final")}>
        Final cut
        <ArrowRight />
      </Button>
    );
  } else if (tab === "final") {
    primary = (
      <Button size="sm" shape="pill" onClick={a.stitch} disabled={p.busy.includes("stitch")}>
        <Scissors />
        {p.final ? (stale ? "Re-stitch with new takes" : "Stitch again") : "Stitch the final cut"}
        <span className="text-xs font-normal opacity-60">free</span>
      </Button>
    );
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center bg-gradient-to-t from-canvas via-canvas/80 to-transparent px-4 pt-10 pb-6">
      <motion.div
        initial={{ y: "100%", opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ type: "spring", bounce: 0.2, duration: 0.5 }}
        layout
        className="pointer-events-auto flex items-center gap-2 rounded-full border bg-card/95 p-1.5 pl-2 shadow-[0_8px_40px_-8px_rgba(0,0,0,0.25)] backdrop-blur-xl"
      >
        <AnimatePresence initial={false}>
          {mine.length > 0 && (
            <motion.div
              key="live"
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: "auto" }}
              exit={{ opacity: 0, width: 0 }}
              className="relative flex items-center gap-2.5 overflow-hidden rounded-full bg-live/10 py-1.5 pr-3.5 pl-3 text-sm whitespace-nowrap text-live"
            >
              <LiveProgress job={mine[0]} />
              {mine.length > 1 && <span className="opacity-70">+{mine.length - 1}</span>}
            </motion.div>
          )}
        </AnimatePresence>
        {mine.length === 0 && !dirty && (
          <span className="flex items-center gap-2 px-2 text-sm text-muted-foreground">
            <Clapperboard className="size-4" />
            <span className="tabular">{usd(p.costs.usd)}</span> spent
          </span>
        )}
        {primary}
      </motion.div>
    </div>
  );
}

function LiveProgress({ job }: { job: Job }) {
  const pr = useJobProgress(job);
  return (
    <>
      <LiveBars />
      <span className="max-w-72 truncate font-medium">{pr?.label ?? job.label}</span>
      {pr && <span className="tabular opacity-70">{leftText(pr)}</span>}
      {pr && (
        <span className="absolute inset-x-3 bottom-0 h-[2px] overflow-hidden rounded-full bg-live/15">
          <span className="block h-full bg-live transition-[width] duration-700 ease-linear" style={{ width: `${pr.fraction * 100}%` }} />
        </span>
      )}
    </>
  );
}

export function Cost({ usd: n, className }: { usd: number; className?: string }) {
  return <span className={cn("text-xs font-normal tabular opacity-60", className)}>≈{usd(n)}</span>;
}
