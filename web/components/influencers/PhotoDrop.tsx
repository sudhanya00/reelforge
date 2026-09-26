"use client";

import * as React from "react";
import { toast } from "sonner";
import { ImagePlus, X } from "@/components/icons";
import { LiveBars } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Photo = { token: string; preview: string };

/** Drop or pick photos; each is uploaded (cleaned server-side) and shown from the local file. */
export function PhotoDrop({
  photos,
  onChange,
  max = 4,
  hint,
  className,
}: {
  photos: Photo[];
  onChange: (p: Photo[]) => void;
  max?: number;
  hint: string;
  className?: string;
}) {
  const [busy, setBusy] = React.useState(0);
  const [over, setOver] = React.useState(false);
  const latest = React.useRef(photos);
  latest.current = photos;

  const add = async (files: File[]) => {
    const room = max - latest.current.length;
    const take = files.filter((f) => f.type.startsWith("image/")).slice(0, Math.max(0, room));
    if (!take.length) return;
    setBusy((b) => b + take.length);
    for (const f of take) {
      try {
        const token = await api.uploadImage(f);
        onChange([...latest.current, { token, preview: URL.createObjectURL(f) }]);
      } catch (e) {
        toast.error(`Couldn't add ${f.name}`, { description: (e as Error).message });
      }
      setBusy((b) => b - 1);
    }
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-2">
        {photos.map((p) => (
          <div key={p.token} className="group relative size-20 overflow-hidden rounded-lg border bg-muted">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={p.preview} alt="" className="size-full object-cover" />
            <button
              onClick={() => onChange(photos.filter((x) => x.token !== p.token))}
              className="absolute top-1 right-1 hidden rounded-full bg-background/90 p-0.5 group-hover:block"
              aria-label="Remove photo"
            >
              <X className="size-3" />
            </button>
          </div>
        ))}
        {Array.from({ length: busy }).map((_, i) => (
          <div key={`b${i}`} className="shimmer flex size-20 items-center justify-center rounded-lg border bg-muted text-live">
            <LiveBars className="h-3" />
          </div>
        ))}
        {photos.length + busy < max && (
          <label
            onDragOver={(e) => (e.preventDefault(), setOver(true))}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              add(Array.from(e.dataTransfer.files));
            }}
            className={cn(
              "flex size-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-[11px] text-muted-foreground hover:border-foreground/40 hover:text-foreground",
              over && "border-foreground bg-accent",
            )}
          >
            <ImagePlus className="size-5" />
            Add
            <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => (add(Array.from(e.target.files ?? [])), (e.target.value = ""))} />
          </label>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}
