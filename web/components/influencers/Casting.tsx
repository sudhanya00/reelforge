"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { Check, PenLine, Trash2, Users } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Badge, Input, Popover, PopoverContent, PopoverTrigger, Segmented, Textarea, Tip } from "@/components/ui/primitives";
import { useConfirm, useConfirmSpend } from "@/components/confirm";
import { JobProgress } from "@/components/progress";
import { imageUsd, infKey, useAppState, useJobs } from "@/lib/hooks";
import { api, url, type CastingOption, type Influencer } from "@/lib/api";
import { cn, usd } from "@/lib/utils";

/**
 * Choose their face: paint a few options from the description, refine one with notes,
 * lock it. The rest of the identity pack is then painted from the locked face.
 */
export function Casting({ inf }: { inf: Influencer }) {
  const { data: state } = useAppState();
  const { running } = useJobs();
  const { mutate } = useSWRConfig();
  const confirm = useConfirmSpend();
  const confirmPlain = useConfirm();
  const [count, setCount] = React.useState("4");
  const [direction, setDirection] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const job = running.find((j) => j.project === infKey(inf.id) && j.kind === "casting");
  const { candidates, locked } = inf.casting;
  const expanded = open || candidates.length > 0 || !!job;
  const per = imageUsd(state?.settings, 1);
  const refresh = (next?: Influencer) => (next ? mutate(`/api/influencers/${inf.id}`, next, { revalidate: false }) : mutate(`/api/influencers/${inf.id}`));

  const cast = async () => {
    const n = Number(count);
    if (!(await confirm({ title: `Cast ${n} faces?`, usd: per * n, action: "Cast" }))) return;
    try {
      await api.castFaces(inf.id, n, direction);
      mutate("/api/jobs");
      refresh();
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };

  const lock = async (c: CastingOption) => {
    const hasViews = inf.identity.some((v) => v.from_face && v.image);
    if (inf.face && hasViews) {
      const ok = await confirmPlain({
        title: "Use this face?",
        detail: "It replaces their current face. The other views were painted from the old one, so update them after (you'll see a button).",
        action: "Use this face",
      });
      if (!ok) return;
    }
    try {
      refresh(await api.lockFace(inf.id, c.name));
      mutate("/api/influencers");
      toast.success("That's their face now", { description: hasViews ? "Update the other views to match it." : "Paint the rest of the identity pack from it." });
    } catch (e) {
      toast.error("Couldn't use it", { description: (e as Error).message });
    }
  };

  const remove = async (c: CastingOption) => {
    try {
      refresh(await api.deleteCandidate(inf.id, c.name));
    } catch (e) {
      toast.error("Couldn't delete", { description: (e as Error).message });
    }
  };

  if (!expanded) {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-xl border border-dashed p-3">
        <Users className="size-5 text-muted-foreground" />
        <p className="flex-1 text-sm">
          <span className="font-medium">Casting</span>
          <span className="text-muted-foreground"> · paint a few faces from the description and pick the one that feels right.</span>
        </p>
        <Button size="sm" variant="outline" shape="pill" onClick={() => setOpen(true)}>
          Start casting
        </Button>
      </div>
    );
  }

  return (
    <div className="mb-6 rounded-xl border p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">Casting</h3>
          <p className="text-xs text-muted-foreground">
            Faces painted from the description. Pick one, refine it with notes, then use it: the rest of the identity pack is painted from it.
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Input value={direction} onChange={(e) => setDirection(e.target.value)} placeholder="Direction (optional): softer, more girl-next-door, freckles" className="h-8 min-w-60 flex-1" />
        <Segmented<string> size="sm" value={count} onChange={setCount} options={["2", "4", "6"].map((v) => ({ value: v, label: v }))} />
        <Button size="sm" shape="pill" onClick={cast} disabled={!!job}>
          <Users />
          Cast {count} faces
          <span className="text-primary-foreground/70 tabular">{usd(per * Number(count))}</span>
        </Button>
      </div>
      {job && <JobProgress job={job} showLabel className="mt-3 text-live" />}
      {candidates.length > 0 && (
        <div className="mt-4 grid grid-cols-3 gap-3 md:grid-cols-4 xl:grid-cols-6">
          {[...candidates].reverse().map((c) => (
            <Option key={c.name} inf={inf} c={c} locked={c.name === locked} busy={!!job} onLock={() => lock(c)} onDelete={() => remove(c)} per={per} />
          ))}
        </div>
      )}
    </div>
  );
}

function Option({
  inf,
  c,
  locked,
  busy,
  onLock,
  onDelete,
  per,
}: {
  inf: Influencer;
  c: CastingOption;
  locked: boolean;
  busy: boolean;
  onLock: () => void;
  onDelete: () => void;
  per: number;
}) {
  const { mutate } = useSWRConfig();
  const [notes, setNotes] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const refine = async () => {
    try {
      await api.refineFace(inf.id, c.name, notes);
      mutate("/api/jobs");
      mutate(`/api/influencers/${inf.id}`);
      setOpen(false);
      setNotes("");
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };
  const num = Number(c.name.split(".")[0]);
  return (
    <div className="group">
      <div className={cn("relative aspect-[3/4] overflow-hidden rounded-lg border bg-muted", locked && "ring-2 ring-ok")}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url(c.url)} alt={`Option ${num}`} className="size-full object-cover" />
        {locked && (
          <Badge tone="ok" className="absolute top-1.5 left-1.5 bg-background/90">
            <Check />
            their face
          </Badge>
        )}
        <div className="absolute inset-x-1.5 bottom-1.5 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {!locked && (
            <Button size="sm" shape="pill" className="h-7 flex-1 px-2 text-xs" onClick={onLock} disabled={busy}>
              Use this face
            </Button>
          )}
          <Popover open={open} onOpenChange={setOpen}>
            <Tip content="Refine: a variation with your notes">
              <PopoverTrigger asChild>
                <Button size="icon-sm" variant="secondary" shape="pill" className="size-7 bg-background/90" disabled={busy} aria-label="Refine">
                  <PenLine />
                </Button>
              </PopoverTrigger>
            </Tip>
            <PopoverContent align="start" className="w-72 space-y-2 p-3">
              <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} autoFocus placeholder="What to change: fuller lips, lighter brows, a bigger smile" className="min-h-16 text-sm" />
              <Button size="sm" shape="pill" className="w-full" onClick={refine} disabled={!notes.trim()}>
                Paint a variation <span className="text-primary-foreground/70 tabular">{usd(per)}</span>
              </Button>
              <p className="text-[11px] text-muted-foreground">The original option stays; the variation appears next to it.</p>
            </PopoverContent>
          </Popover>
          {!locked && (
            <Tip content="Delete this option">
              <Button size="icon-sm" variant="secondary" shape="pill" className="size-7 bg-background/90 hover:text-destructive" onClick={onDelete} disabled={busy} aria-label="Delete option">
                <Trash2 />
              </Button>
            </Tip>
          )}
        </div>
      </div>
      <p className="mt-1 truncate text-[11px] text-muted-foreground" title={c.notes}>
        #{num}
        {c.from ? ` from #${Number(c.from.split(".")[0])}: ${c.notes}` : c.notes ? ` · ${c.notes}` : ""}
      </p>
    </div>
  );
}
