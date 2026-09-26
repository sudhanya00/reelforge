"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { ArrowUp, Check, Clapperboard, Film, Minus, Palette, Plus, RectangleHorizontal, RectangleVertical, Sparkles, Trash2, UserPlus, Users, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, Kbd, LiveBars, Meter, Popover, PopoverContent, PopoverTrigger, Segmented, Tip } from "@/components/ui/primitives";
import { useConfirmSpend } from "@/components/confirm";
import { useRoute } from "@/components/shell";
import { imageUsd, useAppState, useJobs, useLibrary, useProjects, videoUsd } from "@/lib/hooks";
import { JobProgress } from "@/components/progress";
import { useDeleteFilm } from "@/components/project/actions";
import { api, url, type Job, type Orientation, type Pacing, type ProjectSummary, type Resolution } from "@/lib/api";
import { ago, cn, usd } from "@/lib/utils";

export function Library() {
  const { data: projects } = useProjects();
  const { jobs } = useJobs();
  const pending = jobs.filter((j) => (j.kind === "plan" || j.kind === "film") && j.status === "running" && !j.project);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-6 pt-16 pb-24">
      <Composer />

      <section className="mt-20">
        <div className="mb-5 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Your films</h2>
          {projects && projects.length > 0 && <span className="text-xs text-muted-foreground tabular">{projects.length}</span>}
        </div>
        {projects && projects.length === 0 && pending.length === 0 ? (
          <div className="rounded-2xl border border-dashed px-6 py-14 text-center">
            <Film className="mx-auto size-6 text-muted-foreground/60" />
            <p className="mt-3 text-sm text-muted-foreground">Your films will show up here.</p>
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-5">
            <AnimatePresence mode="popLayout">
              {pending.map((j) => (
                <PendingCard key={j.id} job={j} />
              ))}
              {(projects ?? []).map((p, i) => (
                <FilmCard key={p.id} p={p} index={i} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- composer

const EXAMPLES = [
  "A lighthouse keeper finds a message in a bottle addressed to her from 40 years ago.",
  "Two rival street food vendors in Old Delhi are forced to share a stall for one monsoon night.",
  "A retired astronaut teaches her granddaughter to see the ISS pass over their farm.",
];

function Composer() {
  const { data: state, mutate } = useAppState();
  const { go } = useRoute();
  const confirm = useConfirmSpend();
  const { mutate: globalMutate } = useSWRConfig();
  const s = state?.settings;
  const [story, setStory] = React.useState("");
  const [style, setStyle] = React.useState("");
  const [scenes, setScenes] = React.useState(6);
  const [orientation, setOrientation] = React.useState<Orientation | null>(null);
  const [preset, setPreset] = React.useState<string | null>(null);
  const [pacing, setPacing] = React.useState<Pacing | null>(null);   // null = the preset's default
  const [cast, setCast] = React.useState<string[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [waitingFor, setWaitingFor] = React.useState<string | null>(null);
  const { jobs } = useJobs();
  const ref = React.useRef<HTMLTextAreaElement>(null);

  const orient = orientation ?? s?.orientation ?? "9:16";
  const pace: Pacing = pacing ?? state?.styles.find((x) => x.id === preset)?.pacing ?? "balanced";
  // rough: ~7s per scene, about half as many references as scenes plus a few locations
  const filmUsd = videoUsd(s, scenes * 7) + imageUsd(s, Math.ceil(scenes / 2) + 3) + 0.05;

  // open the project as soon as its plan is written
  React.useEffect(() => {
    const j = jobs.find((x) => x.id === waitingFor);
    if (!j || j.status === "running") return;
    setWaitingFor(null);
    if (j.status === "done" && j.kind === "plan" && j.result?.project) go(String(j.result.project), "plan");
  }, [jobs, waitingFor, go]);

  const submit = async (auto: boolean) => {
    if (!story.trim() || submitting) return;
    if (auto && !(await confirm({ title: "Make the whole film?", usd: filmUsd, detail: `Roughly — the plan decides the exact number of scenes and references. Everything runs at ${s?.resolution}.`, action: "Make it" }))) return;
    setSubmitting(true);
    try {
      const job = await api.newFilm({ story, style, scenes, orientation: orient, auto, preset, pacing: pace, cast });
      setWaitingFor(job.id);
      globalMutate("/api/jobs");
      setStory("");
      setStyle("");
      setCast([]);
      toast(auto ? "Making your film" : "Writing the plan", { description: auto ? "Follow along in Activity. It can be resumed if anything fails." : "Usually under a minute." });
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    } finally {
      setSubmitting(false);
    }
  };

  const setResolution = async (r: Resolution) => {
    const next = await api.saveSettings({ resolution: r });
    mutate(next, { revalidate: false });
  };

  return (
    <div className="mx-auto max-w-2xl">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight text-balance">What&apos;s the story?</h1>
        <p className="mt-3 text-balance text-muted-foreground">
          Describe an idea. ReelForge plans it, paints the cast and locations, shoots every scene and cuts the film — with a checkpoint at each step.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.05 }}
        className="mt-9 rounded-2xl border bg-card shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_32px_-12px_rgba(0,0,0,0.12)] transition-shadow focus-within:shadow-[0_1px_2px_rgba(0,0,0,0.04),0_12px_40px_-12px_rgba(0,0,0,0.2)] dark:shadow-none"
      >
        <textarea
          ref={ref}
          value={story}
          onChange={(e) => setStory(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(false);
          }}
          placeholder="A young rider caught in sudden snowfall on a Himalayan pass shelters in a parachute-tent dhaba run by an old woman…"
          rows={4}
          autoFocus
          className="block max-h-[40vh] min-h-28 w-full resize-none bg-transparent px-5 pt-5 pb-2 text-[15px] leading-relaxed outline-none field-sizing-content placeholder:text-muted-foreground/60"
        />
        {state && (
          <div className="flex flex-wrap items-center gap-1.5 px-5 pb-2">
            {state.styles.map((st) => (
              <button
                key={st.id}
                onClick={() => setPreset(preset === st.id ? null : st.id)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs transition-colors",
                  preset === st.id ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                )}
              >
                {st.label}
              </button>
            ))}
          </div>
        )}
        <CastPicker cast={cast} setCast={setCast} />
        <div className="flex items-center gap-2 px-5 pb-3">
          <Palette className="size-4 shrink-0 text-muted-foreground" />
          <input
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && submit(false)}
            placeholder={preset ? "Refine the style (optional) — e.g. warm amber interiors, heavy snow" : "Style — or pick a preset above"}
            className="h-8 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t px-3 py-3">
          <Segmented<Orientation>
            size="sm"
            value={orient}
            onChange={setOrientation}
            options={[
              { value: "9:16", label: <><RectangleVertical />9:16</> },
              { value: "16:9", label: <><RectangleHorizontal />16:9</> },
            ]}
          />
          <div className="flex h-8 items-center rounded-full bg-muted px-1 text-xs font-medium">
            <button className="flex size-6 items-center justify-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground disabled:opacity-40" onClick={() => setScenes(Math.max(2, scenes - 1))} disabled={scenes <= 2} aria-label="Fewer scenes">
              <Minus className="size-3.5" />
            </button>
            <span className="w-16 text-center tabular">{scenes} scenes</span>
            <button className="flex size-6 items-center justify-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground disabled:opacity-40" onClick={() => setScenes(Math.min(12, scenes + 1))} disabled={scenes >= 12} aria-label="More scenes">
              <Plus className="size-3.5" />
            </button>
          </div>
          {state && (
            <Tip content={state.pacing.find((x) => x.id === pace)?.brief}>
              <span>
                <Segmented<Pacing>
                  size="sm"
                  value={pace}
                  onChange={setPacing}
                  options={state.pacing.map((x) => ({ value: x.id, label: x.label }))}
                />
              </span>
            </Tip>
          )}
          {s && (
            <Segmented<Resolution>
              size="sm"
              value={s.resolution}
              onChange={setResolution}
              options={(["360p", "720p", "1080p"] as Resolution[]).map((r) => ({
                value: r,
                label: r,
                disabled: r === "1080p" && !s.high_res_ready,
                title: r === "360p" ? "Cheap test quality" : r === "720p" ? "Film quality" : s.high_res_ready ? "Native 1080p" : "Needs a Cloud Storage bucket: Settings → Generation",
              }))}
            />
          )}
          <div className="ml-auto flex items-center gap-2">
            <Tip content={<>Plans, then makes every reference and scene with no checkpoints. About {usd(filmUsd)} at {s?.resolution}.</>}>
              <Button variant="ghost" size="sm" shape="pill" disabled={!story.trim() || submitting} onClick={() => submit(true)}>
                <Sparkles />
                Make it all
              </Button>
            </Tip>
            <Button size="sm" shape="pill" disabled={!story.trim() || submitting} onClick={() => submit(false)} className="pr-2">
              Write the plan
              <span className="flex size-5 items-center justify-center rounded-full bg-primary-foreground/15">
                <ArrowUp className="size-3" />
              </span>
            </Button>
          </div>
        </div>
      </motion.div>

      <div className="mt-3 flex items-center justify-between px-1 text-xs text-muted-foreground">
        <span>
          Planning costs about $0.05 · a full film ≈ <span className="tabular">{usd(filmUsd)}</span> at {s?.resolution ?? "…"}
        </span>
        <span className="hidden items-center gap-1 sm:flex">
          <Kbd>Ctrl</Kbd>
          <Kbd>Enter</Kbd>
          to plan
        </span>
      </div>

      {!story && (
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {EXAMPLES.map((e) => (
            <button key={e} onClick={() => (setStory(e), ref.current?.focus())} className="max-w-[280px] truncate rounded-full border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              {e}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- cast from the library

function CastPicker({ cast, setCast }: { cast: string[]; setCast: (c: string[]) => void }) {
  const { data } = useLibrary();
  const chars = data?.characters ?? [];
  if (!chars.length) return null;
  const chosen = chars.filter((c) => cast.includes(c.id));
  const toggle = (id: string) => setCast(cast.includes(id) ? cast.filter((x) => x !== id) : [...cast, id]);
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-5 pb-2">
      <Users className="size-4 shrink-0 text-muted-foreground" />
      {chosen.map((c) => (
        <span key={c.id} className="flex items-center gap-1.5 rounded-full border py-0.5 pr-1 pl-0.5 text-xs">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {c.image && <img src={url(c.image)} alt="" className="size-5 rounded-full object-cover object-top" />}
          {c.name}
          <button onClick={() => toggle(c.id)} className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Remove ${c.name}`}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <Popover>
        <PopoverTrigger asChild>
          <button className="flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground hover:border-foreground/30 hover:text-foreground">
            <UserPlus className="size-3.5" />
            {chosen.length ? "Add" : "Cast from library"}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 p-2">
          <p className="px-2 pt-1 pb-2 text-xs text-muted-foreground">Saved characters appear exactly as painted, at no image cost.</p>
          <div className="max-h-72 space-y-0.5 overflow-y-auto scrollbar-thin">
            {chars.map((c) => {
              const on = cast.includes(c.id);
              return (
                <button key={c.id} onClick={() => toggle(c.id)} className={cn("flex w-full items-center gap-3 rounded-lg p-1.5 text-left hover:bg-accent", on && "bg-accent")}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {c.image ? <img src={url(c.image)} alt="" className="h-10 w-16 rounded-md object-cover object-top" /> : <span className="h-10 w-16 rounded-md bg-muted" />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{c.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{c.appearance}</span>
                  </span>
                  {on && <Check className="size-4 text-ok" />}
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

// ---------------------------------------------------------------- cards

function Poster({ src, orientation, className }: { src: string | null; orientation: Orientation; className?: string }) {
  if (!src)
    return (
      <div className={cn("flex items-center justify-center bg-gradient-to-br from-muted to-muted/40", className)}>
        <Clapperboard className="size-7 text-muted-foreground/40" />
      </div>
    );
  return (
    <div className={cn("relative overflow-hidden bg-muted", className)}>
      {orientation === "9:16" && (
        // vertical films: blurred fill behind a contained poster, so the grid stays even
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url(src)} alt="" aria-hidden className="absolute inset-0 size-full scale-125 object-cover opacity-60 blur-2xl" />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url(src)} alt="" className={cn("relative size-full transition-transform duration-500 group-hover:scale-[1.03]", orientation === "9:16" ? "object-contain" : "object-cover")} />
    </div>
  );
}

function FilmCard({ p, index }: { p: ProjectSummary; index: number }) {
  const { go } = useRoute();
  const del = useDeleteFilm();
  const next = p.final ? "final" : p.scenes[0] > 0 ? "scenes" : p.refs[0] > 0 ? "references" : "plan";
  return (
    <motion.div
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && go(p.id, next)}
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.35, delay: Math.min(index, 8) * 0.03 }}
      onClick={() => go(p.id, next)}
      className="group overflow-hidden rounded-xl border bg-card text-left transition-all hover:-translate-y-0.5 hover:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.25)] focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <div className="relative">
        <Poster src={p.poster} orientation={p.orientation} className="aspect-[16/10]" />
        <div className="absolute inset-x-3 top-3 flex justify-between">
          {p.busy ? (
            <Badge tone="live" className="bg-background/85 backdrop-blur">
              <LiveBars className="h-2.5" bars={4} />
              Generating
            </Badge>
          ) : (
            <span />
          )}
          {p.final && (
            <Badge className="bg-background/85 backdrop-blur">
              <Check className="text-ok" />
              Final cut
            </Badge>
          )}
        </div>
      </div>
      <div className="space-y-3 p-4">
        <div>
          <h3 className="truncate font-medium tracking-tight">{p.title}</h3>
          <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted-foreground">{p.logline}</p>
        </div>
        <div className="flex gap-4">
          <Meter label="References" value={p.refs[0]} total={p.refs[1]} tone={p.refs[0] === p.refs[1] ? "ok" : "neutral"} />
          <Meter label="Scenes" value={p.scenes[0]} total={p.scenes[1]} tone={p.scenes[0] === p.scenes[1] ? "ok" : "neutral"} />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {p.orientation === "9:16" ? <RectangleVertical className="size-3.5" /> : <RectangleHorizontal className="size-3.5" />}
          <span className="tabular">{usd(p.cost_usd)} spent</span>
          <span className="ml-auto">{ago(p.updated)}</span>
          {!p.busy && (
            <Tip content="Delete film">
              <button
                onClick={(e) => (e.stopPropagation(), del(p.id, p.title))}
                className="-my-1 -mr-1 rounded-full p-1.5 text-muted-foreground opacity-0 transition-all group-hover:opacity-100 hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100"
                aria-label={`Delete ${p.title}`}
              >
                <Trash2 className="size-3.5" />
              </button>
            </Tip>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function PendingCard({ job }: { job: Job }) {
  return (
    <motion.div layout initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="overflow-hidden rounded-xl border bg-card">
      <div className="shimmer flex aspect-[16/10] items-center justify-center bg-muted/60">
        <span className="flex items-center gap-2 text-sm font-medium text-live">
          <LiveBars />
          {job.kind === "film" ? "Making the film" : "Writing the plan"}
        </span>
      </div>
      <div className="space-y-2 p-4">
        <div className="shimmer h-4 w-2/3 rounded bg-muted" />
        <p className="line-clamp-2 min-h-10 text-sm text-muted-foreground">{job.logs.at(-1) ?? "Directing…"}</p>
        <JobProgress job={job} className="text-live" />
      </div>
    </motion.div>
  );
}
