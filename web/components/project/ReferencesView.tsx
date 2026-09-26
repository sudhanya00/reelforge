"use client";

import * as React from "react";
import { motion } from "motion/react";
import { BookmarkCheck, BookmarkPlus, Expand, ImageOff, Link2, PaintBrush, PenLine, RefreshCw, RotateCcw, TriangleAlert } from "@/components/icons";
import { useSWRConfig } from "swr";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Dialog, DialogContent, DialogDescription, DialogTitle, LiveBars, Textarea, Tip } from "@/components/ui/primitives";
import { useJobs } from "@/lib/hooks";
import { JobProgress } from "@/components/progress";
import { api, url, type Asset, type Project } from "@/lib/api";
import { cn, plural, usd } from "@/lib/utils";
import { useProjectActions } from "./actions";

const GROUPS = [
  { kind: "character", title: "Cast", hint: "Turnaround sheets — every clip matches faces and costumes to these" },
  { kind: "prop", title: "Props", hint: "Objects that recur across shots" },
  { kind: "environment", title: "Locations", hint: "Establishing plates; variants are painted from their base" },
] as const;

export function ReferencesView({ p }: { p: Project }) {
  const [prompting, setPrompting] = React.useState<Asset | null>(null);
  const [viewing, setViewing] = React.useState<Asset | null>(null);
  const usage = React.useMemo(() => {
    const m: Record<string, number> = {};
    p.plan.scenes.forEach((s) => s.refs.forEach((r) => (m[r] = (m[r] ?? 0) + 1)));
    return m;
  }, [p.plan.scenes]);

  return (
    <div className="space-y-12">
      {GROUPS.map((g) => {
        const items = p.assets.filter((a) => a.kind === g.kind);
        if (!items.length) return null;
        return (
          <section key={g.kind}>
            <div className="mb-4 flex items-baseline gap-3">
              <h2 className="text-lg font-semibold tracking-tight">{g.title}</h2>
              <span className="text-sm text-muted-foreground">{g.hint}</span>
            </div>
            <div className={cn("grid gap-5", g.kind === "environment" && p.orientation === "9:16" ? "grid-cols-[repeat(auto-fill,minmax(220px,1fr))]" : "grid-cols-[repeat(auto-fill,minmax(340px,1fr))]")}>
              {items.map((a, i) => (
                <AssetCard key={a.id} a={a} p={p} index={i} uses={usage[a.id] ?? 0} onPrompt={() => setPrompting(a)} onView={() => setViewing(a)} />
              ))}
            </div>
          </section>
        );
      })}
      <PromptSheet p={p} asset={prompting} onClose={() => setPrompting(null)} />
      <Dialog open={!!viewing} onOpenChange={(o) => !o && setViewing(null)}>
        <DialogContent className="w-auto max-w-[92vw] p-2">
          <DialogTitle className="sr-only">{viewing?.name}</DialogTitle>
          {viewing?.image && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url(viewing.image)} alt={viewing.name} className="max-h-[86vh] rounded-xl object-contain" />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function useJobFor(p: Project, id: string) {
  const { running } = useJobs();
  return running.find((j) => j.project === p.id && (j.claims.includes(id) || j.claims.includes("*")));
}

function AssetCard({ a, p, index, uses, onPrompt, onView }: { a: Asset; p: Project; index: number; uses: number; onPrompt: () => void; onView: () => void }) {
  const act = useProjectActions(p);
  const job = useJobFor(p, a.id);
  const price = act.settings?.prices.image ?? 0;
  const generating = a.status === "generating";

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(index, 6) * 0.04 }} className="group overflow-hidden rounded-xl border bg-card">
      <div className={cn("relative bg-muted", a.aspect === "9:16" ? "aspect-[9/16]" : "aspect-video")}>
        {a.image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url(a.image)} alt={a.name} className={cn("size-full object-cover transition-all duration-500", generating && "scale-[1.02] opacity-40 blur-sm")} />
        )}

        {generating && (
          <div className="shimmer absolute inset-0 flex flex-col items-center justify-center gap-3 px-8 text-live">
            <LiveBars />
            <span className="text-sm font-medium">Painting</span>
            {job && <JobProgress job={job} className="max-w-60" />}
          </div>
        )}

        {!a.image && !generating && (
          <div className={cn("absolute inset-2 flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center", a.error && "border-destructive/40 bg-destructive/5")}>
            {a.error ? (
              <>
                <TriangleAlert className="size-5 text-destructive" />
                <p className="line-clamp-3 max-w-[85%] text-xs text-destructive">{a.error}</p>
              </>
            ) : (
              <ImageOff className="size-5 text-muted-foreground/60" />
            )}
            <Button size="sm" shape="pill" variant={a.error ? "outline" : "default"} onClick={() => act.paint(a.id)}>
              {a.error ? <RefreshCw /> : <PaintBrush />}
              {a.error ? "Try again" : "Paint"}
              <span className="text-xs font-normal opacity-60">≈{usd(price)}</span>
            </Button>
          </div>
        )}

        {a.image && !generating && (
          <div className="absolute inset-x-0 bottom-0 flex justify-end gap-1 bg-gradient-to-t from-black/50 to-transparent p-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <OverlayButton tip="View full size" onClick={onView}><Expand /></OverlayButton>
            <OverlayButton tip="Edit prompt" onClick={onPrompt}><PenLine /></OverlayButton>
            <OverlayButton tip={`Paint again · ≈${usd(price)}`} onClick={() => act.paint(a.id)}><RefreshCw /></OverlayButton>
          </div>
        )}
      </div>

      <div className="flex items-start gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-medium">{a.name}</h3>
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{a.id}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge tone="outline">in {plural(uses, "scene")}</Badge>
            {a.base && (
              <Badge tone="outline">
                <Link2 />
                from {a.base}
              </Badge>
            )}
            {a.overridden && <Badge tone="live">custom prompt</Badge>}
            {a.kind === "character" && a.library_id && (
              <Badge tone="ok">
                <BookmarkCheck />
                in library
              </Badge>
            )}
          </div>
        </div>
        {a.kind === "character" && a.image && !generating && !a.library_id && <SaveToLibrary p={p} a={a} />}
        {!a.image || generating ? (
          <Tip content="Edit prompt">
            <Button variant="ghost" size="icon-sm" shape="pill" onClick={onPrompt} aria-label="Edit prompt">
              <PenLine />
            </Button>
          </Tip>
        ) : null}
      </div>
    </motion.div>
  );
}

function SaveToLibrary({ p, a }: { p: Project; a: Asset }) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = React.useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.saveCharacter(p.id, a.id);
      toast.success(`${a.name} saved to your library`, { description: "Cast them in any new film from the new-film box." });
      mutate(`/api/projects/${p.id}`);
      mutate("/api/library");
    } catch (e) {
      toast.error("Couldn't save to the library", { description: (e as Error).message });
    }
    setBusy(false);
  };
  return (
    <Tip content="Save to library: reuse this character, exactly as painted, in other films">
      <Button variant="ghost" size="icon-sm" shape="pill" onClick={save} disabled={busy} aria-label="Save to library">
        <BookmarkPlus />
      </Button>
    </Tip>
  );
}

function OverlayButton({ tip, onClick, children }: { tip: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tip content={tip}>
      <button onClick={onClick} className="flex size-8 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur transition-colors hover:bg-black/75 [&_svg]:size-4">
        {children}
      </button>
    </Tip>
  );
}

function PromptSheet({ p, asset, onClose }: { p: Project; asset: Asset | null; onClose: () => void }) {
  const act = useProjectActions(p);
  const [text, setText] = React.useState("");
  React.useEffect(() => setText(asset?.prompt ?? ""), [asset]);
  if (!asset) return <Dialog open={false} />;
  const changed = text.trim() !== asset.prompt.trim();
  const save = async (andPaint: boolean) => {
    const ok = changed ? await act.setPrompt(asset.id, text === asset.default_prompt ? null : text) : true;
    if (ok && andPaint) await act.paint(asset.id);
    if (ok) onClose();
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right">
        <div>
          <DialogTitle>{asset.name}</DialogTitle>
          <DialogDescription className="mt-1">
            The exact prompt sent to the image model. It&apos;s built from the plan; edits here override it for this image only.
          </DialogDescription>
        </div>
        {asset.base && (
          <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            Painted with <span className="font-mono">{asset.base}</span> attached as a reference, so the place stays the same.
          </p>
        )}
        <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-72 grow text-sm leading-relaxed" />
        <div className="flex items-center gap-2">
          {(asset.overridden || text !== asset.default_prompt) && (
            <Button variant="ghost" size="sm" shape="pill" onClick={() => setText(asset.default_prompt)}>
              <RotateCcw />
              Use the plan&apos;s prompt
            </Button>
          )}
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" shape="pill" onClick={() => save(false)} disabled={!changed}>
              Save
            </Button>
            <Button size="sm" shape="pill" onClick={() => save(true)}>
              <PaintBrush />
              {changed ? "Save & paint" : "Paint again"}
              <span className="text-xs font-normal opacity-60">≈{usd(act.settings?.prices.image)}</span>
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
