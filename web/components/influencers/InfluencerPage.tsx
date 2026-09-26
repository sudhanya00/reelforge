"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { motion } from "motion/react";
import { Expand, PaintBrush, PenLine, RefreshCw, RotateCcw, Trash2, TriangleAlert, UserRound } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Badge, Dialog, DialogContent, DialogTitle, LiveBars, Popover, PopoverContent, PopoverTrigger, Spinner, Textarea, Tip } from "@/components/ui/primitives";
import { useConfirm, useConfirmSpend } from "@/components/confirm";
import { JobProgress } from "@/components/progress";
import { useRoute } from "@/components/shell";
import { imageUsd, infKey, useAppState, useInfluencer, useJobs } from "@/lib/hooks";
import { api, url, type IdentityImage, type IdentityView, type Influencer } from "@/lib/api";
import { cn, usd } from "@/lib/utils";
import { Designer } from "./Designer";
import { PlacesSection } from "./Places";
import { Casting } from "./Casting";
import { PhotoDrop, type Photo } from "./PhotoDrop";
import { VideosTab } from "./Videos";

export function InfluencerPage({ id }: { id: string }) {
  const { data: inf, error } = useInfluencer(id);
  const { infTab } = useRoute();
  if (error) return <p className="mx-auto mt-24 text-sm text-muted-foreground">{error.message}</p>;
  if (!inf) return <Spinner className="mx-auto mt-24 text-muted-foreground" />;
  return infTab === "videos" ? <VideosTab inf={inf} /> : <IdentityTab inf={inf} />;
}

// ---------------------------------------------------------------- identity

const VIEW_LABEL: Record<IdentityView, [string, string]> = {
  face: ["Face", "Front-camera selfie. Everything else is painted from this."],
  three_quarter: ["Three-quarter", "Same face, turned. Helps the video model hold identity when they move."],
  profile: ["Profile", "Side view, for head turns."],
  full_body: ["Full body", "Build and proportions. Outfits change per video."],
  setting: ["Home", "Their place, empty. Also the first of their saved places."],
};

function useIdentityJob(id: string) {
  const { running } = useJobs();
  return running.find((j) => j.project === infKey(id) && j.kind === "identity");
}

function IdentityTab({ inf }: { inf: Influencer }) {
  const { data: state } = useAppState();
  const { mutate } = useSWRConfig();
  const { goInf } = useRoute();
  const confirm = useConfirmSpend();
  const confirmPlain = useConfirm();
  const [editing, setEditing] = React.useState(false);
  const job = useIdentityJob(inf.id);
  const missing = inf.identity.filter((v) => !v.image);
  const stale = inf.identity.filter((v) => v.image && v.stale);
  const todo = [...missing, ...stale];
  const hasFace = !!inf.identity.find((v) => v.view === "face")?.image;
  const p = inf.profile;

  const paint = async (views?: IdentityView[], force = false) => {
    const n = views?.length ?? missing.length;
    if (!(await confirm({ title: `Paint ${n} photo${n === 1 ? "" : "s"}?`, usd: imageUsd(state?.settings, n), action: "Paint" }))) return;
    try {
      await api.paintIdentity(inf.id, views, force);
      mutate("/api/jobs");
      mutate(`/api/influencers/${inf.id}`);
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };

  const repaint = async (v: IdentityView) => {
    if (v === "face" && inf.identity.some((x) => x.from_face && x.image)) {
      const ok = await confirmPlain({
        title: "Repaint the face?",
        detail: "A new face is a new person: repaint the other views afterwards so they match it.",
        action: "Repaint face",
      });
      if (!ok) return;
    }
    paint([v], true);
  };

  const remove = async () => {
    const ok = await confirmPlain({
      title: `Delete ${p.name}?`,
      detail: "Their identity pack and every video move to the Recycle Bin.",
      action: "Delete",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.deleteInfluencer(inf.id);
      mutate("/api/influencers");
      goInf(null);
    } catch (e) {
      toast.error("Couldn't delete", { description: (e as Error).message });
    }
  };

  return (
    <div className="mx-auto grid w-full max-w-[1300px] gap-8 px-6 pt-10 pb-24 lg:grid-cols-[320px_1fr]">
      <aside className="space-y-5 lg:sticky lg:top-24 lg:self-start">
        <div className="flex items-center gap-4">
          <div className="size-16 shrink-0 overflow-hidden rounded-full bg-muted">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {inf.face ? <img src={url(inf.face)} alt="" className="size-full object-cover" /> : <UserRound className="m-4 size-8 text-muted-foreground/50" />}
          </div>
          <div className="min-w-0">
            <h1 className="truncate font-display text-3xl leading-tight">{p.name}</h1>
            <p className="truncate text-sm text-muted-foreground">{[p.handle, p.niche].filter(Boolean).join(" · ")}</p>
          </div>
        </div>
        <dl className="space-y-3 rounded-xl border bg-card p-4 text-sm">
          {(
            [
              ["Who", [p.age && `${p.age}`, p.ethnicity, p.gender].filter(Boolean).join(", ")],
              ["Look", [p.hair, p.body, p.features].filter(Boolean).join("; ")],
              ["Style", [p.style, p.outfit && `usually ${p.outfit}`].filter(Boolean).join("; ")],
              ["Personality", p.persona],
              ["Talks", p.speech],
              ["Voice", p.voice],
              ["Home", p.setting],
            ] as [string, string][]
          )
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs font-medium text-muted-foreground">{k}</dt>
                <dd className="mt-0.5 leading-snug">{v}</dd>
              </div>
            ))}
        </dl>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" shape="pill" onClick={() => setEditing(true)} disabled={!!job}>
            <PenLine />
            Edit profile
          </Button>
          <Tip content="Delete influencer">
            <Button variant="ghost" size="icon-sm" shape="pill" onClick={remove} disabled={inf.busy} aria-label="Delete influencer" className="hover:bg-destructive/10 hover:text-destructive">
              <Trash2 />
            </Button>
          </Tip>
          <span className="ml-auto self-center text-xs text-muted-foreground tabular">{usd(inf.identity_usd)} on photos</span>
        </div>
      </aside>

      <section>
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold tracking-tight">Identity pack</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Every video is anchored to these photos. Raw and unretouched on purpose: real skin, natural light, no filters.
            </p>
          </div>
          {job ? (
            <div className="w-64">
              <JobProgress job={job} showLabel className="text-live" />
            </div>
          ) : todo.length ? (
            <Button shape="pill" onClick={() => (stale.length ? paint(todo.map((v) => v.view), true) : paint())}>
              <PaintBrush />
              {missing.length === inf.identity.length
                ? "Paint the identity pack"
                : stale.length && !missing.length
                  ? `Update ${stale.length} to the new face`
                  : `Paint ${todo.length} ${stale.length ? "missing or out of date" : "missing"}`}
              <span className="text-primary-foreground/70 tabular">{usd(imageUsd(state?.settings, todo.length))}</span>
            </Button>
          ) : (
            <Button shape="pill" onClick={() => goInf(inf.id, "videos")}>
              Make a video
            </Button>
          )}
        </div>
        {inf.consent ? <SourcePhotos inf={inf} /> : <Casting inf={inf} />}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
          {inf.identity.map((v, i) => (
            <IdentityCard key={v.view} inf={inf} v={v} index={i} canPaint={!job && (!v.from_face || hasFace)} onRepaint={() => repaint(v.view)} onPaint={() => paint([v.view])} />
          ))}
        </div>
        <PlacesSection inf={inf} />
      </section>

      <Designer open={editing} onOpenChange={setEditing} initial={inf.profile} id={inf.id} />
    </div>
  );
}

/** The photos a character made from a real person is painted from. */
function SourcePhotos({ inf }: { inf: Influencer }) {
  const { mutate } = useSWRConfig();
  const [adding, setAdding] = React.useState<Photo[]>([]);
  const refresh = (next: Influencer) => mutate(`/api/influencers/${inf.id}`, next, { revalidate: false });
  React.useEffect(() => {
    if (!adding.length) return;
    api.addSources(inf.id, adding.map((x) => x.token)).then(refresh, (e) => toast.error("Couldn't add", { description: (e as Error).message }));
    setAdding([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adding]);
  return (
    <div className="mb-5 rounded-xl border p-3">
      <div className="mb-2 flex items-baseline gap-2">
        <p className="text-sm font-medium">Made from these photos</p>
        <p className="text-xs text-muted-foreground">Every view is painted from them. Add or remove photos, then repaint.</p>
      </div>
      <div className="flex flex-wrap items-start gap-2">
        {inf.sources.map((x) => (
          <div key={x.name} className="group relative size-16 overflow-hidden rounded-lg border">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url(x.url)} alt="" className="size-full object-cover" />
            <button
              onClick={() => api.deleteSource(inf.id, x.name).then(refresh)}
              className="absolute top-0.5 right-0.5 hidden rounded-full bg-background/90 p-0.5 group-hover:block"
              aria-label="Remove photo"
            >
              <Trash2 className="size-3" />
            </button>
          </div>
        ))}
        {inf.sources.length < 6 && <PhotoDrop photos={adding} onChange={setAdding} max={6 - inf.sources.length} hint="" className="[&_label]:size-16" />}
      </div>
    </div>
  );
}

function IdentityCard({
  inf,
  v,
  index,
  canPaint,
  onRepaint,
  onPaint,
}: {
  inf: Influencer;
  v: IdentityImage;
  index: number;
  canPaint: boolean;
  onRepaint: () => void;
  onPaint: () => void;
}) {
  const [zoom, setZoom] = React.useState(false);
  const [label, hint] = VIEW_LABEL[v.view];
  const generating = v.status === "generating";
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="group">
      <div className={cn("relative overflow-hidden rounded-xl border bg-muted", v.aspect === "3:4" ? "aspect-[3/4]" : "aspect-[9/16]")}>
        {v.image && !generating ? (
          <button onClick={() => setZoom(true)} className="size-full" aria-label={`View ${label}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url(v.image)} alt={label} className="size-full object-cover" />
          </button>
        ) : generating ? (
          <div className="shimmer flex size-full items-center justify-center text-live">
            <LiveBars />
          </div>
        ) : (
          <div className="flex size-full flex-col items-center justify-center gap-2 p-3 text-center">
            {v.error ? (
              <>
                <TriangleAlert className="size-5 text-destructive" />
                <p className="line-clamp-4 text-xs text-destructive">{v.error}</p>
              </>
            ) : (
              <UserRound className="size-6 text-muted-foreground/40" />
            )}
            {canPaint && (
              <Button size="sm" variant="outline" shape="pill" onClick={onPaint} className="mt-1">
                <PaintBrush />
                Paint
              </Button>
            )}
          </div>
        )}
        {v.image && !generating && (
          <div className="absolute top-2 right-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <Tip content="Enlarge">
              <Button size="icon-sm" variant="secondary" shape="pill" className="bg-background/85 backdrop-blur" onClick={() => setZoom(true)} aria-label="Enlarge">
                <Expand />
              </Button>
            </Tip>
            {canPaint && (
              <Tip content="Repaint">
                <Button size="icon-sm" variant="secondary" shape="pill" className="bg-background/85 backdrop-blur" onClick={onRepaint} aria-label="Repaint">
                  <RefreshCw />
                </Button>
              </Tip>
            )}
          </div>
        )}
      </div>
      <div className="mt-2 flex items-start gap-1">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-sm font-medium">
            {label}
            {v.overridden && <Badge tone="live">custom</Badge>}
            {v.stale && <Badge tone="live">older face</Badge>}
          </p>
          <p className="text-xs leading-snug text-muted-foreground">{hint}</p>
        </div>
        <PromptEditor inf={inf} v={v} disabled={generating} />
      </div>
      <Dialog open={zoom} onOpenChange={setZoom}>
        <DialogContent className="w-auto max-w-[90vw] p-2">
          <DialogTitle className="sr-only">{label}</DialogTitle>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {v.image && <img src={url(v.image)} alt={label} className="max-h-[85vh] rounded-xl object-contain" />}
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}

function PromptEditor({ inf, v, disabled }: { inf: Influencer; v: IdentityImage; disabled: boolean }) {
  const { mutate } = useSWRConfig();
  const [open, setOpen] = React.useState(false);
  const [text, setText] = React.useState(v.prompt);
  React.useEffect(() => setText(v.prompt), [v.prompt, open]);
  const save = async (prompt: string | null) => {
    try {
      const next = await api.setIdentityPrompt(inf.id, v.view, prompt);
      mutate(`/api/influencers/${inf.id}`, next, { revalidate: false });
      setOpen(false);
      toast.success(prompt ? "Prompt saved" : "Prompt reset", { description: "Repaint to use it." });
    } catch (e) {
      toast.error("Couldn't save", { description: (e as Error).message });
    }
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tip content="Edit prompt">
        <PopoverTrigger asChild>
          <Button variant="ghost" size="icon-sm" shape="pill" disabled={disabled} aria-label="Edit prompt" className="-mt-1 -mr-2 shrink-0">
            <PenLine />
          </Button>
        </PopoverTrigger>
      </Tip>
      <PopoverContent className="w-[420px] p-3">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} className="max-h-72 text-xs leading-relaxed" />
        <div className="mt-2 flex items-center gap-2">
          {v.overridden && (
            <Button size="sm" variant="ghost" shape="pill" onClick={() => save(null)}>
              <RotateCcw />
              Reset
            </Button>
          )}
          <Button size="sm" shape="pill" className="ml-auto" onClick={() => save(text)} disabled={text === v.prompt}>
            Save prompt
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
