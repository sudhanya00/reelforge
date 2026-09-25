"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { motion, AnimatePresence } from "motion/react";
import { Armchair, ArrowUp, Check, Copy, DoorOpen, Footprints, ImageIcon, Info, MapPin, Megaphone, Mic, Plus, RefreshCw, Shirt, Smartphone, Sparkles, Trash2, TriangleAlert, Video as VideoIcon, Wand2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, InlineText, Input, Label, LiveBars, Segmented, Spinner, Textarea, Tip } from "@/components/ui/primitives";
import { useConfirm, useConfirmSpend } from "@/components/confirm";
import { JobProgress } from "@/components/progress";
import { useRoute } from "@/components/shell";
import { infKey, useAppState, useInfluencers, useJobs, useVideo } from "@/lib/hooks";
import { api, url, type Format, type Influencer, type Job, type Resolution, type Segment, type Setup, type Video, type VideoSummary } from "@/lib/api";
import { ago, cn, usd } from "@/lib/utils";

const LENGTHS = [10, 20, 30, 40] as const;

const FORMAT_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  talking_head: Smartphone,
  propped: Armchair,
  walk_and_talk: Footprints,
  mirror: Shirt,
  walk_in: DoorOpen,
  podcast: Mic,
};

const ACTION_HINT: Record<string, string> = {
  talking_head: "leans into the lens",
  propped: "pulls a knee up onto the chair",
  walk_and_talk: "glances ahead, steps around someone",
  mirror: "turns to show the back of the outfit",
  walk_in: "walks in from the left, drops a bag",
  podcast: "leans into the mic",
};

function useFormats(): Format[] {
  const { data } = useInfluencers();
  return data?.formats ?? [];
}

function FormatPicker({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const formats = useFormats();
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {formats.map((f) => {
        const Icon = FORMAT_ICON[f.id] ?? VideoIcon;
        const on = f.id === value;
        return (
          <button
            key={f.id}
            disabled={disabled}
            onClick={() => onChange(f.id)}
            className={cn(
              "flex items-start gap-2.5 rounded-xl border p-2.5 text-left transition-colors disabled:opacity-50",
              on ? "border-foreground/40 bg-accent" : "hover:border-foreground/25 hover:bg-accent/40",
            )}
          >
            <Icon className={cn("mt-0.5 size-4 shrink-0", on ? "text-foreground" : "text-muted-foreground")} />
            <span className="min-w-0">
              <span className="block text-sm font-medium leading-tight">{f.label}</span>
              <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{f.blurb}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Saved places as chips, plus "somewhere else" (a description). `place` "" = somewhere else. */
function WherePicker({
  inf,
  place,
  location,
  onChange,
  allowAuto,
  disabled,
}: {
  inf: Influencer;
  place: string | null;
  location: string;
  onChange: (place: string | null, location: string) => void;
  allowAuto?: boolean;
  disabled?: boolean;
}) {
  const chip = (on: boolean) =>
    cn(
      "flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors disabled:opacity-50",
      on ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30 hover:text-foreground",
    );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {allowAuto && (
          <button disabled={disabled} className={chip(place === null)} onClick={() => onChange(null, "")}>
            <Sparkles className="size-3" />
            AI picks
          </button>
        )}
        {inf.places.map((p) => (
          <button key={p.id} disabled={disabled} className={chip(place === p.id)} onClick={() => onChange(p.id, p.description)}>
            <MapPin className="size-3" />
            {p.name}
          </button>
        ))}
        <button disabled={disabled} className={chip(place === "")} onClick={() => onChange("", place ? "" : location)}>
          Somewhere else
        </button>
      </div>
      {place === "" && (
        <Textarea
          value={location}
          disabled={disabled}
          onChange={(e) => onChange("", e.target.value)}
          placeholder="e.g. a busy supermarket aisle, cereal boxes and fluorescent light"
          className="min-h-9"
          rows={1}
        />
      )}
    </div>
  );
}

export function VideosTab({ inf }: { inf: Influencer }) {
  const { video, goInf } = useRoute();
  const { running } = useJobs();
  const scripting = running.find((j) => j.project === infKey(inf.id) && j.kind === "script");
  const selected = video ?? null;

  return (
    <div className="mx-auto grid w-full max-w-[1300px] gap-8 px-6 pt-10 pb-24 lg:grid-cols-[300px_1fr]">
      <aside className="space-y-3 lg:sticky lg:top-24 lg:self-start">
        <button
          onClick={() => goInf(inf.id, "videos")}
          className={cn(
            "flex w-full items-center gap-2 rounded-xl border border-dashed px-3.5 py-3 text-sm font-medium transition-colors hover:border-foreground/30 hover:bg-accent/40",
            !selected ? "border-foreground/30 bg-accent/40" : "text-muted-foreground",
          )}
        >
          <Plus className="size-4" />
          New video
        </button>
        {scripting && (
          <div className="rounded-xl border bg-card p-3">
            <JobProgress job={scripting} showLabel className="text-live" />
          </div>
        )}
        <div className="space-y-1.5">
          {inf.videos.map((v) => (
            <VideoRow key={v.id} v={v} active={v.id === selected} onClick={() => goInf(inf.id, "videos", v.id)} />
          ))}
        </div>
      </aside>
      <section className="min-w-0">
        {selected ? <VideoEditor key={selected} inf={inf} vid={selected} /> : <NewVideo inf={inf} busy={!!scripting} />}
      </section>
    </div>
  );
}

function VideoRow({ v, active, onClick }: { v: VideoSummary; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn("flex w-full items-center gap-3 rounded-xl p-1.5 text-left transition-colors hover:bg-accent/60", active && "bg-accent")}>
      <div className="relative aspect-[9/16] w-11 shrink-0 overflow-hidden rounded-md bg-muted">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {v.poster ? <img src={url(v.poster)} alt="" className="size-full object-cover" /> : <VideoIcon className="m-auto mt-5 size-4 text-muted-foreground/40" />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{v.title}</p>
        <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          {v.busy ? (
            <span className="flex items-center gap-1 text-live">
              <LiveBars className="h-2.5" bars={4} />
              shooting
            </span>
          ) : v.final ? (
            <Check className="size-3 text-ok" />
          ) : (
            <span>script</span>
          )}
          <span className="tabular">· {v.seconds}s · {ago(v.updated)}</span>
        </p>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------- new video

function NewVideo({ inf, busy }: { inf: Influencer; busy: boolean }) {
  const { mutate } = useSWRConfig();
  const [topic, setTopic] = React.useState("");
  const [points, setPoints] = React.useState("");
  const [length, setLength] = React.useState<number>(30);
  const [format, setFormat] = React.useState("talking_head");
  const [place, setPlace] = React.useState<string | null>(null);      // null: AI picks
  const [location, setLocation] = React.useState("");
  const [outfit, setOutfit] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const { jobs } = useJobs();
  const { goInf } = useRoute();
  const p = inf.profile;

  // open the script as soon as it's written
  React.useEffect(() => {
    const j = jobs.find((x) => x.id === jobId);
    if (!j || j.status === "running") return;
    setJobId(null);
    if (j.status === "done" && j.result?.video) goInf(inf.id, "videos", String(j.result.video));
  }, [jobs, jobId, goInf, inf.id]);

  const submit = async () => {
    if (!topic.trim() || submitting) return;
    setSubmitting(true);
    try {
      const j = await api.newVideo(inf.id, {
        format, topic, points, length_s: length,
        place: place ?? "", location: place === "" ? location : "", outfit,
      });
      setJobId(j.id);
      mutate("/api/jobs");
      setTopic("");
      setPoints("");
      toast(`Writing in ${p.name}'s voice`, { description: "Usually under a minute. You'll edit it before anything is shot." });
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
    setSubmitting(false);
  };

  return (
    <div className="mx-auto max-w-2xl pt-6">
      <h2 className="text-2xl font-semibold tracking-tight">What should {p.name} post?</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Pick how it&apos;s filmed and what it&apos;s about. AI drafts the script in their voice and sets the scene (where, what they wear); you edit both before anything is shot.
      </p>

      <div className="mt-6">
        <FormatPicker value={format} onChange={setFormat} />
      </div>

      <div className="mt-4 rounded-2xl border bg-card shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_32px_-12px_rgba(0,0,0,0.12)] focus-within:shadow-[0_1px_2px_rgba(0,0,0,0.04),0_12px_40px_-12px_rgba(0,0,0,0.2)] dark:shadow-none">
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && submit()}
          autoFocus
          rows={2}
          placeholder={`e.g. ${p.niche ? `a ${p.niche.split(/[,.]/)[0].toLowerCase()} thing most people get wrong` : "the one habit that changed my mornings"}`}
          className="block w-full resize-none bg-transparent px-5 pt-5 pb-2 text-[15px] leading-relaxed outline-none field-sizing-content placeholder:text-muted-foreground/60"
        />
        <div className="px-5 pb-3">
          <input
            value={points}
            onChange={(e) => setPoints(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && submit()}
            placeholder="Talking points, product details or a call to action (optional)"
            className="h-8 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
          />
        </div>
        <div className="space-y-3 border-t px-5 py-4">
          <div className="grid gap-1.5 sm:grid-cols-[80px_1fr] sm:items-start">
            <Label className="pt-1.5">Where</Label>
            <WherePicker inf={inf} place={place} location={location} allowAuto onChange={(pl, loc) => (setPlace(pl), setLocation(loc))} />
          </div>
          <div className="grid gap-1.5 sm:grid-cols-[80px_1fr] sm:items-center">
            <Label>Wearing</Label>
            <div className="flex items-center gap-2">
              <Input value={outfit} onChange={(e) => setOutfit(e.target.value)} placeholder="AI picks something that fits, or describe it" className="h-8" />
              {p.outfit && (
                <Tip content={p.outfit}>
                  <button onClick={() => setOutfit(outfit === p.outfit ? "" : p.outfit)} className={cn("shrink-0 rounded-full border px-2.5 py-1 text-xs", outfit === p.outfit ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}>
                    Go-to outfit
                  </button>
                </Tip>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t px-3 py-3">
          <Segmented<string> size="sm" value={String(length)} onChange={(v) => setLength(Number(v))} options={LENGTHS.map((l) => ({ value: String(l), label: `${l}s` }))} />
          <Button size="sm" shape="pill" className="ml-auto pr-2" disabled={!topic.trim() || submitting || busy || (place === "" && !location.trim())} onClick={submit}>
            Write the script
            <span className="flex size-5 items-center justify-center rounded-full bg-primary-foreground/15">
              <ArrowUp className="size-3" />
            </span>
          </Button>
        </div>
      </div>
      <p className="mt-3 px-1 text-xs text-muted-foreground">
        Scripts cost about $0.02. Before shooting, an opening frame (≈$0.13) shows the setup; the video starts from it, and each 10 s after the first extends the same take.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- script + shoot

type Draft = { title: string; caption: string; segments: Segment[]; format: string; setup: Setup };

const draftOf = (v: Video): Draft => ({ title: v.title, caption: v.caption, segments: v.segments, format: v.format, setup: v.setup });

function VideoEditor({ inf, vid }: { inf: Influencer; vid: string }) {
  const { data: v, mutate } = useVideo(inf.id, vid);
  const { running } = useJobs();
  const job = running.find((j) => j.project === infKey(inf.id) && j.kind === "reel" && j.claims.includes(vid));
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (v && !draft) setDraft(draftOf(v));
  }, [v, draft]);

  if (!v || !draft) return <Spinner className="mx-auto mt-24 text-muted-foreground" />;

  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(v));
  const locked = !!job || v.busy;

  const save = async (): Promise<Video | null> => {
    setSaving(true);
    try {
      const next = await api.saveScript(inf.id, vid, draft);
      mutate(next, { revalidate: false });
      setDraft(draftOf(next));
      return next;
    } catch (e) {
      toast.error("Couldn't save", { description: (e as Error).message });
      return null;
    } finally {
      setSaving(false);
    }
  };

  const setSeg = (i: number, patch: Partial<Segment>) =>
    setDraft((d) => d && { ...d, segments: d.segments.map((s, k) => (k === i ? { ...s, ...patch } : s)) });

  return (
    <div className="grid gap-8 xl:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-6">
        <div>
          <InlineText value={draft.title} onChange={(t) => setDraft({ ...draft, title: t })} multiline={false} className="text-2xl font-semibold tracking-tight" />
          <p className="mt-1 text-sm text-muted-foreground">
            {v.brief.topic}
            <span className="tabular"> · {draft.segments.length * 10}s · {usd(v.cost_usd)} spent</span>
          </p>
        </div>

        <SetupCard inf={inf} draft={draft} setDraft={setDraft} locked={locked} />

        <div className="space-y-3">
          {draft.segments.map((s, i) => (
            <SegmentCard
              key={i}
              s={s}
              index={i}
              format={draft.format}
              locked={locked}
              onChange={(patch) => setSeg(i, patch)}
              onRemove={draft.segments.length > 1 ? () => setDraft({ ...draft, segments: draft.segments.filter((_, k) => k !== i) }) : undefined}
            />
          ))}
          {draft.segments.length < 4 && !locked && (
            <button
              onClick={() => setDraft({ ...draft, segments: [...draft.segments, { id: "", seconds: 10, lines: [""], delivery: "", action: "" }] })}
              className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed py-2.5 text-sm text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
            >
              <Plus className="size-4" />
              Add 10 seconds
            </button>
          )}
        </div>

        <Caption value={draft.caption} onChange={(c) => setDraft({ ...draft, caption: c })} />

        <AnimatePresence>
          {dirty && !locked && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} className="sticky bottom-4 flex items-center gap-2 rounded-full border bg-background/90 p-1.5 pl-4 shadow-lg backdrop-blur">
              <span className="text-sm text-muted-foreground">Unsaved script changes</span>
              <Button variant="ghost" size="sm" shape="pill" className="ml-auto" onClick={() => setDraft(draftOf(v))}>
                Discard
              </Button>
              <Button size="sm" shape="pill" onClick={save} disabled={saving}>
                Save script
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <ShootPanel inf={inf} v={v} job={job} dirty={dirty} save={save} />
    </div>
  );
}

function SetupCard({ inf, draft, setDraft, locked }: { inf: Influencer; draft: Draft; setDraft: (d: Draft) => void; locked: boolean }) {
  const set = (patch: Partial<Setup>) => setDraft({ ...draft, setup: { ...draft.setup, ...patch } });
  return (
    <div className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">Setup</h3>
        <span className="text-xs text-muted-foreground">How it&apos;s filmed, where, and what they&apos;re wearing today.</span>
      </div>
      <FormatPicker value={draft.format} onChange={(f) => setDraft({ ...draft, format: f })} disabled={locked} />
      <div className="space-y-1.5">
        <Label>Where</Label>
        <WherePicker inf={inf} place={draft.setup.place} location={draft.setup.location} disabled={locked} onChange={(place, location) => set({ place: place ?? "", location })} />
        {draft.setup.place !== "" && <p className="text-xs text-muted-foreground">{draft.setup.location}</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label>Wearing</Label>
          <Input value={draft.setup.outfit} disabled={locked} onChange={(e) => set({ outfit: e.target.value })} placeholder="e.g. black satin slip dress, silver hoops" className="h-8" />
        </div>
        <div className="space-y-1.5">
          <Label>Position</Label>
          <Input value={draft.setup.position} disabled={locked} onChange={(e) => set({ position: e.target.value })} placeholder="e.g. sitting cross-legged on the bed" className="h-8" />
        </div>
        <div className="space-y-1.5">
          <Label>Light</Label>
          <Input value={draft.setup.light} disabled={locked} onChange={(e) => set({ light: e.target.value })} placeholder="e.g. golden hour through the window" className="h-8" />
        </div>
      </div>
    </div>
  );
}

function SegmentCard({ s, index, format, locked, onChange, onRemove }: { s: Segment; index: number; format: string; locked: boolean; onChange: (p: Partial<Segment>) => void; onRemove?: () => void }) {
  const words = s.lines.join(" ").split(/\s+/).filter(Boolean).length;
  const tooLong = words > 28;
  return (
    <div className="group rounded-xl border bg-card p-4">
      <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded-full bg-muted px-2 py-0.5 font-medium tabular">
          {index * 10}–{index * 10 + 10}s
        </span>
        <span>{index === 0 ? "Starts from the opening frame" : "Extends the same take"}</span>
        <span className={cn("ml-auto tabular", tooLong && "text-live")}>
          {words} words{tooLong && " · may not fit in 10 s"}
        </span>
        {onRemove && !locked && (
          <Tip content="Remove these 10 seconds">
            <button onClick={onRemove} className="rounded-full p-1 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-accent hover:text-foreground" aria-label="Remove segment">
              <X className="size-3.5" />
            </button>
          </Tip>
        )}
      </div>
      <Textarea
        value={s.lines.join("\n")}
        onChange={(e) => onChange({ lines: e.target.value.split("\n") })}
        disabled={locked}
        placeholder="What they say, one line per breath"
        className="min-h-14 border-0 bg-transparent px-0 text-[15px] leading-relaxed shadow-none focus-visible:ring-0 dark:bg-transparent"
      />
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label>Delivery</Label>
          <Input value={s.delivery} onChange={(e) => onChange({ delivery: e.target.value })} disabled={locked} placeholder="excited, half-laughing" className="h-8" />
        </div>
        <div className="space-y-1">
          <Label>Action</Label>
          <Input value={s.action} onChange={(e) => onChange({ action: e.target.value })} disabled={locked} placeholder={ACTION_HINT[format] ?? "leans into the lens"} className="h-8" />
        </div>
      </div>
    </div>
  );
}

function Caption({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const sponsored = /#ad\b|sponsor|partner|discount|code\b|link in bio/i.test(value);
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="mb-1 flex items-center">
        <Label>Caption</Label>
        <Button variant="ghost" size="sm" shape="pill" className="-my-1 ml-auto h-7 text-xs" onClick={copy} disabled={!value}>
          {copied ? <Check className="text-ok" /> : <Copy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <Textarea value={value} onChange={(e) => onChange(e.target.value)} className="min-h-12 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 dark:bg-transparent" />
      <p className={cn("mt-2 flex items-start gap-1.5 text-xs", sponsored ? "text-live" : "text-muted-foreground")}>
        <Megaphone className="mt-0.5 size-3.5 shrink-0" />
        {sponsored
          ? "This looks sponsored: label it as a paid partnership (#ad) and turn on the platform's AI-generated content label."
          : "When you post, turn on the platform's AI-generated content label. Sponsored posts also need #ad."}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- the phone

function ShootPanel({ inf, v, job, dirty, save }: { inf: Influencer; v: Video; job: Job | undefined; dirty: boolean; save: () => Promise<Video | null> }) {
  const { data: state, mutate: mutateState } = useAppState();
  const { mutate } = useSWRConfig();
  const { goInf } = useRoute();
  const confirm = useConfirmSpend();
  const confirmPlain = useConfirm();
  const [playing, setPlaying] = React.useState<string | null>(null);
  const { running } = useJobs();
  const hasFace = !!inf.face;
  const est = v.estimate;
  const src = playing ?? v.final ?? v.turns.at(-1)?.url ?? null;
  const painting = running.find((j) => j.project === infKey(inf.id) && j.kind === "opening" && j.claims.includes(v.id));

  const paintOpening = async () => {
    if (dirty && !(await save())) return;
    try {
      await api.paintOpening(inf.id, v.id);
      mutate("/api/jobs");
      mutate(`/api/influencers/${inf.id}/videos/${v.id}`);
    } catch (err) {
      toast.error("Couldn't start", { description: (err as Error).message });
    }
  };

  const shoot = async () => {
    let cur = v;
    if (dirty) {
      const next = await save();
      if (!next) return;
      cur = next;
    }
    const e = cur.estimate;
    const ok = await confirm({
      title: `Shoot ${cur.seconds}s of ${inf.profile.name}?`,
      usd: e.usd,
      detail: `${e.turns} turn${e.turns === 1 ? "" : "s"} at ${e.resolution} (${usd(e.video_usd)})${e.images_usd ? `, plus ${usd(e.images_usd)} to paint the opening frame first` : ""}.`,
      action: "Shoot",
    });
    if (!ok) return;
    try {
      await api.shootVideo(inf.id, v.id);
      setPlaying(null);
      mutate("/api/jobs");
      mutate(`/api/influencers/${inf.id}/videos/${v.id}`);
    } catch (err) {
      toast.error("Couldn't start", { description: (err as Error).message });
    }
  };

  const remove = async () => {
    if (!(await confirmPlain({ title: `Delete "${v.title}"?`, detail: "The script and any takes move to the Recycle Bin.", action: "Delete", destructive: true }))) return;
    try {
      await api.deleteVideo(inf.id, v.id);
      mutate(`/api/influencers/${inf.id}`);
      goInf(inf.id, "videos");
    } catch (err) {
      toast.error("Couldn't delete", { description: (err as Error).message });
    }
  };

  const setResolution = async (r: Resolution) => {
    const next = await api.saveSettings({ resolution: r });
    mutateState(next, { revalidate: false });
    mutate(`/api/influencers/${inf.id}/videos/${v.id}`);
  };

  return (
    <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
      <div className="relative mx-auto aspect-[9/16] w-full max-w-[300px] overflow-hidden rounded-[28px] border-[6px] border-foreground/90 bg-black shadow-xl">
        {job ? (
          <div className="flex size-full flex-col items-center justify-center gap-4 p-6 text-white">
            <LiveBars className="h-5" />
            <JobProgress job={job} showLabel className="text-white" />
          </div>
        ) : painting ? (
          <div className="flex size-full flex-col items-center justify-center gap-4 p-6 text-white">
            <LiveBars className="h-5" />
            <JobProgress job={painting} showLabel className="text-white" />
          </div>
        ) : src ? (
          <video key={src} src={url(src)} controls playsInline className="size-full object-cover" poster={!playing && v.poster ? url(v.poster) : undefined} />
        ) : v.opening.opening ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url(v.opening.opening)} alt="Opening frame" className={cn("size-full object-cover", !v.opening_ok && "opacity-50")} />
        ) : (
          <div className="flex size-full flex-col items-center justify-center gap-2 p-6 text-center text-white/60">
            <VideoIcon className="size-7" />
            <p className="text-sm">Not shot yet</p>
            <p className="text-xs">Paint the opening frame to preview the setup.</p>
          </div>
        )}
      </div>

      {v.error && !job && (
        <p className="flex items-start gap-1.5 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {v.error}
        </p>
      )}

      {!job && (
        <Openings v={v} busy={!!painting} disabled={!hasFace} onPaint={paintOpening} />
      )}

      {!job && (
        <div className="space-y-2">
          {state && (
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>Quality</span>
              <Segmented<Resolution>
                size="sm"
                value={state.settings.resolution === "360p" ? "360p" : "720p"}
                onChange={setResolution}
                options={(["360p", "720p"] as Resolution[]).map((r) => ({ value: r, label: r, title: r === "360p" ? "Cheap test quality" : "Post quality" }))}
              />
            </div>
          )}
          <Button className="w-full" shape="pill" onClick={shoot} disabled={!hasFace || !v.segments.length || !!painting}>
            <Wand2 />
            {v.final ? "Shoot again" : "Shoot"}
            <span className="text-primary-foreground/70 tabular">{usd(est.usd)}</span>
          </Button>
          {!hasFace ? (
            <p className="text-center text-xs text-muted-foreground">
              Paint the identity pack first.{" "}
              <button className="underline underline-offset-2" onClick={() => goInf(inf.id, "identity")}>
                Go to Identity
              </button>
            </p>
          ) : (
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              {est.images_usd
                ? `Includes ${usd(est.images_usd)} to paint the opening frame${v.opening.opening ? " again: the setup changed" : ""}.`
                : "Starts from the opening frame above."}
            </p>
          )}
        </div>
      )}

      {v.turns.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center text-xs text-muted-foreground">
            <span className="font-medium">Takes</span>
            {v.extension_mode && (
              <Tip content={v.extension_mode === "cumulative" ? "Each extension returned the whole take so far; the last one is the video." : "Each extension returned only its new seconds; they were joined."}>
                <span className="ml-auto cursor-help underline decoration-dotted underline-offset-2">{v.extension_mode === "cumulative" ? "whole-take extensions" : "joined segments"}</span>
              </Tip>
            )}
          </div>
          {v.final && (
            <TakeRow label="Final video" active={!playing} onClick={() => setPlaying(null)} />
          )}
          {v.turns.map((t) => (
            <TakeRow key={t.name} label={`${t.segment ?? t.name} · ${t.extends ? "extension" : "first shot"}`} meta={`${t.duration_s?.toFixed(1) ?? "?"}s · ${usd(t.cost_usd)}`} active={playing === t.url} onClick={() => setPlaying(t.url)} />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
        <span className="tabular">{usd(v.costs.usd)} spent · {v.costs.calls} calls</span>
        <Tip content="Delete video">
          <Button variant="ghost" size="icon-sm" shape="pill" onClick={remove} disabled={!!job} aria-label="Delete video" className="hover:bg-destructive/10 hover:text-destructive">
            <Trash2 />
          </Button>
        </Tip>
      </div>
    </aside>
  );
}

function Openings({ v, busy, disabled, onPaint }: { v: Video; busy: boolean; disabled: boolean; onPaint: () => void }) {
  const views = Object.entries(v.opening) as [string, string | null][];
  const any = views.some(([, u]) => u);
  return (
    <div className="space-y-2 rounded-xl border p-3">
      <div className="flex items-center gap-2 text-xs">
        <ImageIcon className="size-3.5 text-muted-foreground" />
        <span className="font-medium">Opening frame</span>
        {any && !v.opening_ok && <Badge tone="live">setup changed</Badge>}
        <Button variant="ghost" size="sm" shape="pill" className="-my-1 ml-auto h-7 text-xs" onClick={onPaint} disabled={busy || disabled}>
          {any ? <RefreshCw /> : <Wand2 />}
          {any ? "Repaint" : "Paint"}
          {!v.opening_ok && <span className="tabular text-muted-foreground">{usd(v.estimate.images_usd)}</span>}
        </Button>
      </div>
      {any && (
        <div className="flex gap-2">
          {views.map(([k, u]) =>
            u ? (
              <a key={k} href={url(u)} target="_blank" rel="noreferrer" className="block w-16 overflow-hidden rounded-md border">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={url(u)} alt={k} className={cn("aspect-[9/16] w-full object-cover", !v.opening_ok && "opacity-50")} />
              </a>
            ) : null,
          )}
          {views.length > 1 && <p className="self-end text-[11px] leading-snug text-muted-foreground">The empty place they walk into, and their outfit.</p>}
        </div>
      )}
      {v.opening_error && (
        <p className="flex items-start gap-1.5 text-xs text-destructive">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {v.opening_error}
        </p>
      )}
    </div>
  );
}

function TakeRow({ label, meta, active, onClick }: { label: string; meta?: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn("flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-accent", active && "bg-accent")}>
      <span className={cn("size-1.5 rounded-full", active ? "bg-live" : "bg-muted-foreground/30")} />
      <span className="flex-1 truncate font-medium">{label}</span>
      {meta && <span className="tabular text-muted-foreground">{meta}</span>}
    </button>
  );
}
