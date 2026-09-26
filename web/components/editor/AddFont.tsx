"use client";

import * as React from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Plus, Search, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, LiveBars, Popover, PopoverContent, PopoverTrigger, Segmented } from "@/components/ui/primitives";
import { api, fetcher } from "@/lib/api";
import type { CaptionCatalog } from "@/lib/captions";
import { cn } from "@/lib/utils";

type GoogleFamily = { family: string; category: string; popularity: number; weights: number[] };

const WEIGHT_NAME: Record<number, string> = {
  100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
  600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black",
};

/** Show Google results in their own typeface (straight from Google's CSS, preview only). */
function useGooglePreview(families: GoogleFamily[]) {
  React.useEffect(() => {
    if (!families.length) return;
    const href =
      "https://fonts.googleapis.com/css2?" +
      families.map((f) => `family=${encodeURIComponent(f.family).replace(/%20/g, "+")}:wght@${Math.max(...f.weights.filter((w) => w <= 900))}`).join("&") +
      "&display=swap&text=" + encodeURIComponent(families.map((f) => f.family).join("") + "Hey there");
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
    return () => link.remove();
  }, [families]);
}

export function AddFont({ onAdded }: { onAdded: (catalog: CaptionCatalog, id: string) => void }) {
  const [open, setOpen] = React.useState(false);
  const [tab, setTab] = React.useState<"google" | "upload">("google");
  const [q, setQ] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [busy, setBusy] = React.useState<string | null>(null);
  const { data: catalog } = useSWR<CaptionCatalog>("/api/captions", fetcher);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, error, isLoading } = useSWR<{ results: GoogleFamily[] }>(
    open && tab === "google" ? `/api/captions/fonts/google?q=${encodeURIComponent(debounced)}` : null,
    fetcher,
  );
  const results = React.useMemo(() => data?.results ?? [], [data]);
  useGooglePreview(results);

  const add = async (key: string, run: () => Promise<CaptionCatalog & { added: { id: string; label: string } }>) => {
    setBusy(key);
    try {
      const r = await run();
      onAdded(r, r.added.id);
      toast.success(`Added ${r.added.label}`);
      setOpen(false);
    } catch (e) {
      toast.error("Couldn't add the font", { description: (e as Error).message });
    }
    setBusy(null);
  };

  const upload = async (file: File) => {
    const bytes = await file.arrayBuffer();
    add("upload", () => api.uploadFont(file.name, bytes));
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="flex items-center gap-1 rounded-md border border-dashed px-2 py-1 text-sm text-muted-foreground hover:border-foreground/40 hover:text-foreground">
          <Plus className="size-3.5" />
          Add font
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" side="left" className="w-[380px] p-3">
        <Segmented<"google" | "upload">
          size="sm"
          value={tab}
          onChange={setTab}
          options={[
            { value: "google", label: <><Search />Google Fonts</> },
            { value: "upload", label: <><Upload />Upload</> },
          ]}
        />
        {tab === "google" ? (
          <div className="mt-3 space-y-3">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search 1,900 free fonts, e.g. Montserrat" autoFocus className="h-8" />
            {!q && catalog?.popular && (
              <div>
                <p className="mb-1.5 text-xs text-muted-foreground">Popular for captions, one click:</p>
                <div className="flex flex-wrap gap-1.5">
                  {catalog.popular.map((p) => {
                    const have = catalog.fonts.some((f) => f.label === p.label);
                    return (
                      <button
                        key={p.label}
                        disabled={have || !!busy}
                        onClick={() => add(p.label, () => api.importGoogleFont(p.family, p.weight))}
                        className={cn("rounded-full border px-2.5 py-1 text-xs", have ? "opacity-40" : "hover:border-foreground/40")}
                      >
                        {busy === p.label ? <LiveBars className="h-3" /> : p.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="max-h-72 space-y-0.5 overflow-y-auto scrollbar-thin">
              {error && <p className="text-xs text-destructive">{(error as Error).message}</p>}
              {isLoading && <p className="text-xs text-muted-foreground">Loading the catalogue…</p>}
              {results.map((f) => (
                <GoogleRow key={f.family} f={f} busy={busy === f.family} onAdd={(w) => add(f.family, () => api.importGoogleFont(f.family, w))} />
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">Free for commercial use (OFL/Apache). Saved in your library, used in previews and exports.</p>
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center text-sm hover:bg-accent/40">
              {busy === "upload" ? <LiveBars /> : <Upload className="size-5 text-muted-foreground" />}
              Choose a .ttf or .otf file
              <input type="file" accept=".ttf,.otf,font/ttf,font/otf" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            <p className="text-[11px] text-muted-foreground">
              One weight per file (e.g. Montserrat-ExtraBold.ttf). Variable fonts export at their default weight. Make sure your licence allows use in videos.
            </p>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

function GoogleRow({ f, busy, onAdd }: { f: GoogleFamily; busy: boolean; onAdd: (weight: number) => void }) {
  const upright = f.weights.filter((w) => w <= 900);
  const [w, setW] = React.useState(upright.includes(800) ? 800 : upright.includes(700) ? 700 : upright[upright.length - 1]);
  return (
    <div className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-accent/60">
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] leading-tight" style={{ fontFamily: `"${f.family}"`, fontWeight: w }}>
          {f.family}
        </p>
        <p className="text-[11px] text-muted-foreground">{f.category}</p>
      </div>
      <select value={w} onChange={(e) => setW(Number(e.target.value))} className="h-7 rounded-md border bg-background px-1 text-xs">
        {upright.map((x) => (
          <option key={x} value={x}>
            {WEIGHT_NAME[x] ?? x}
          </option>
        ))}
      </select>
      <Button size="sm" variant="outline" shape="pill" className="h-7 px-2.5 text-xs" disabled={busy} onClick={() => onAdd(w)}>
        {busy ? <LiveBars className="h-3" /> : "Add"}
      </Button>
    </div>
  );
}
