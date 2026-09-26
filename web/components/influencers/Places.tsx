"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { MapPin, PaintBrush, Plus, RefreshCw, Trash2, TriangleAlert } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Input, Label, LiveBars, Popover, PopoverContent, PopoverTrigger, Textarea, Tip } from "@/components/ui/primitives";
import { useConfirm } from "@/components/confirm";
import { imageUsd, useAppState } from "@/lib/hooks";
import { api, url, type Influencer, type Place } from "@/lib/api";
import { usd } from "@/lib/utils";

const IDEAS = ["their gym", "a favourite café", "the car, driver's seat", "a supermarket aisle", "a nightclub", "the office", "a park path"];

/** Places they film in more than once. Each gets an empty plate that keeps it consistent. */
export function PlacesSection({ inf }: { inf: Influencer }) {
  const { mutate } = useSWRConfig();
  const confirm = useConfirm();
  const refresh = () => {
    mutate("/api/jobs");
    mutate(`/api/influencers/${inf.id}`);
  };

  const repaint = async (p: Place) => {
    try {
      await (p.id === "home" ? api.paintIdentity(inf.id, ["setting"], true) : api.repaintPlace(inf.id, p.id));
      refresh();
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };

  const remove = async (p: Place) => {
    if (!(await confirm({ title: `Remove ${p.name}?`, detail: "Videos already made there keep their frames.", action: "Remove", destructive: true }))) return;
    try {
      await api.deletePlace(inf.id, p.id);
      refresh();
    } catch (e) {
      toast.error("Couldn't remove", { description: (e as Error).message });
    }
  };

  return (
    <div className="mt-12">
      <div className="mb-5">
        <h2 className="text-lg font-semibold tracking-tight">Places</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Where they film more than once. A video can also happen anywhere new; you just describe it.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        {inf.places.map((p) => (
          <div key={p.id} className="group">
            <div className="relative aspect-[9/16] overflow-hidden rounded-xl border bg-muted">
              {p.status === "generating" ? (
                <div className="shimmer flex size-full items-center justify-center text-live">
                  <LiveBars />
                </div>
              ) : p.image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={url(p.image)} alt={p.name} className="size-full object-cover" />
              ) : (
                <div className="flex size-full flex-col items-center justify-center gap-2 p-3 text-center">
                  {p.error ? (
                    <>
                      <TriangleAlert className="size-5 text-destructive" />
                      <p className="line-clamp-4 text-xs text-destructive">{p.error}</p>
                    </>
                  ) : (
                    <MapPin className="size-6 text-muted-foreground/40" />
                  )}
                  <Button size="sm" variant="outline" shape="pill" onClick={() => repaint(p)} className="mt-1">
                    <PaintBrush />
                    Paint
                  </Button>
                </div>
              )}
              {p.image && p.status !== "generating" && (
                <div className="absolute top-2 right-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                  <Tip content="Repaint">
                    <Button size="icon-sm" variant="secondary" shape="pill" className="bg-background/85 backdrop-blur" onClick={() => repaint(p)} aria-label="Repaint">
                      <RefreshCw />
                    </Button>
                  </Tip>
                  {p.id !== "home" && (
                    <Tip content="Remove">
                      <Button size="icon-sm" variant="secondary" shape="pill" className="bg-background/85 backdrop-blur hover:text-destructive" onClick={() => remove(p)} aria-label="Remove">
                        <Trash2 />
                      </Button>
                    </Tip>
                  )}
                </div>
              )}
            </div>
            <p className="mt-2 text-sm font-medium">{p.name}</p>
            <p className="line-clamp-2 text-xs leading-snug text-muted-foreground">{p.description}</p>
          </div>
        ))}
        <AddPlace inf={inf} onAdded={refresh} />
      </div>
    </div>
  );
}

function AddPlace({ inf, onAdded }: { inf: Influencer; onAdded: () => void }) {
  const { data: state } = useAppState();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.addPlace(inf.id, name, description);
      onAdded();
      setOpen(false);
      setName("");
      setDescription("");
    } catch (e) {
      toast.error("Couldn't add", { description: (e as Error).message });
    }
    setBusy(false);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="flex aspect-[9/16] flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-accent/40 hover:text-foreground">
          <Plus className="size-5" />
          Add a place
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 space-y-3 p-4">
        <div className="space-y-1.5">
          <Label htmlFor="place-name">Name</Label>
          <Input id="place-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Gym" autoFocus />
          <div className="flex flex-wrap gap-1">
            {IDEAS.map((i) => (
              <button key={i} onClick={() => setName(i.replace(/^(their|a|the) /, "").replace(/^./, (c) => c.toUpperCase()))} className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground hover:border-foreground/30 hover:text-foreground">
                {i}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="place-desc">What it looks like</Label>
          <Textarea id="place-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="A small concrete-floor gym: chalky squat racks, a mirrored wall, a fan in the corner, fluorescent light" />
        </div>
        <Button className="w-full" shape="pill" onClick={save} disabled={busy || !name.trim() || !description.trim()}>
          <PaintBrush />
          Save and paint
          <span className="text-primary-foreground/70 tabular">{usd(imageUsd(state?.settings, 1))}</span>
        </Button>
      </PopoverContent>
    </Popover>
  );
}
