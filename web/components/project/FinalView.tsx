"use client";

import * as React from "react";
import { Download, Film, FolderOpen, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LiveBars, Tip } from "@/components/ui/primitives";
import { useRoute } from "@/components/shell";
import { url, type Project } from "@/lib/api";
import { ago, cn, plural, secs, usd } from "@/lib/utils";
import { useProjectActions } from "./actions";

export function FinalView({ p }: { p: Project }) {
  const act = useProjectActions(p);
  const vertical = p.orientation === "9:16";
  const stitching = p.busy.includes("stitch");
  const stale = !!p.final && p.scenes.some((s) => s.takes.find((t) => t.name === s.selected && t.created > (p.final?.updated ?? 0)));
  const unshot = p.scenes.filter((s) => !s.takes.length);

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-6">
        <div className="flex justify-center rounded-2xl border bg-card p-4">
          {p.final ? (
            <video
              key={p.final.url}
              src={url(p.final.url)}
              poster={url(p.final.poster)}
              controls
              playsInline
              className={cn("rounded-xl bg-black", vertical ? "h-[calc(100vh-330px)] min-h-[360px] max-h-[760px] aspect-[9/16]" : "w-full max-h-[calc(100vh-330px)] aspect-video")}
            />
          ) : (
            <div className={cn("flex flex-col items-center justify-center gap-3 rounded-xl bg-muted text-center", vertical ? "h-[60vh] aspect-[9/16]" : "w-full aspect-video")}>
              {stitching ? <LiveBars className="h-5 text-live" bars={7} /> : <Film className="size-7 text-muted-foreground/50" />}
              <p className="max-w-xs text-sm text-muted-foreground">
                {stitching
                  ? "Stitching the selected takes…"
                  : unshot.length
                    ? `${plural(unshot.length, "scene")} still need a take before the final cut.`
                    : "Every scene has a take. Stitch them into the final cut."}
              </p>
            </div>
          )}
        </div>

        {p.final && (
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" size="sm" shape="pill">
              <a href={url(p.final.url)} download={`${p.plan.title}.mp4`}>
                <Download />
                Download
              </a>
            </Button>
            <Button variant="ghost" size="sm" shape="pill" onClick={act.reveal}>
              <FolderOpen />
              Show in folder
            </Button>
            <span className="ml-auto text-xs text-muted-foreground tabular">
              {secs(p.final.duration_s)} · stitched {ago(p.final.updated)}
            </span>
          </div>
        )}
        {stale && (
          <p className="flex items-center gap-2 rounded-lg bg-live/10 px-3 py-2 text-sm">
            <TriangleAlert className="size-4 text-live" />
            You picked newer takes since this cut. Stitch again to include them.
          </p>
        )}

        <Timeline p={p} />
      </div>

      <Spend p={p} remaining={act.remainingUsd} />
    </div>
  );
}

/** The cut as a strip: each selected take, as wide as it is long. */
function Timeline({ p }: { p: Project }) {
  const { go } = useRoute();
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold">The cut</h3>
      <div className="flex gap-1 overflow-hidden rounded-xl">
        {p.scenes.map((sc) => {
          const take = sc.takes.find((t) => t.name === sc.selected);
          const d = take?.duration_s ?? sc.duration_s;
          return (
            <Tip key={sc.id} content={take ? `${sc.id} · ${take.name} · ${secs(d)}` : `${sc.id} · not shot yet`}>
              <button
                onClick={() => {
                  go(p.id, "scenes");
                  setTimeout(() => document.getElementById(`scene-${sc.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 350);
                }}
                style={{ flexGrow: d, flexBasis: 0 }}
                className={cn("group relative h-20 min-w-10 overflow-hidden transition-opacity hover:opacity-90", !take && "border border-dashed bg-muted/40")}
              >
                {take && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={url(take.poster)} alt="" className="absolute inset-0 size-full object-cover" />
                )}
                <span className={cn("absolute bottom-1 left-1.5 font-mono text-[10px] font-semibold", take ? "text-white drop-shadow" : "text-muted-foreground")}>
                  {sc.id} · {Math.round(d)}s
                </span>
              </button>
            </Tip>
          );
        })}
      </div>
    </div>
  );
}

const KINDS = [
  { key: ["plan", "review"], label: "Planning & reviews", color: "var(--chart-1)" },
  { key: ["image"], label: "References", color: "var(--chart-2)" },
  { key: ["video", "video_unsaved"], label: "Scenes", color: "var(--chart-3)" },
  { key: ["video_edit"], label: "Fixes", color: "var(--chart-4)" },
];

/** Hero total + one stacked bar (part-to-whole) with a labelled legend. */
function Spend({ p, remaining }: { p: Project; remaining: number }) {
  const c = p.costs;
  const rows = KINDS.map((k) => ({
    ...k,
    usd: k.key.reduce((t, key) => t + (c.by_kind[key]?.usd ?? 0), 0),
    calls: k.key.reduce((t, key) => t + (c.by_kind[key]?.calls ?? 0), 0),
  }));
  const total = rows.reduce((t, r) => t + r.usd, 0);

  return (
    <aside className="h-fit space-y-5 rounded-2xl border bg-card p-5 lg:sticky lg:top-24">
      <div>
        <p className="text-xs font-medium text-muted-foreground">Spent on this film</p>
        <p className="mt-1 text-5xl font-semibold tracking-tight tabular">{usd(c.usd)}</p>
        <p className="mt-1.5 text-xs text-muted-foreground tabular">
          {plural(c.calls, "generation call")} · {secs(c.video_s)} of video
        </p>
      </div>

      {total > 0 && (
        <div className="flex h-2.5 gap-[2px]" role="img" aria-label="Spend by stage">
          {rows.filter((r) => r.usd > 0).map((r) => (
            <Tip key={r.label} content={`${r.label} · ${usd(r.usd)} · ${Math.round((r.usd / total) * 100)}%`}>
              <span className="h-full rounded-[3px] transition-opacity hover:opacity-80" style={{ flexGrow: r.usd, flexBasis: 0, background: r.color }} />
            </Tip>
          ))}
        </div>
      )}

      <table className="w-full text-sm">
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t first:border-0">
              <td className="py-2">
                <span className="flex items-center gap-2">
                  <span className="size-2.5 rounded-[3px]" style={{ background: r.color }} />
                  {r.label}
                </span>
              </td>
              <td className="py-2 text-right text-xs text-muted-foreground tabular">{r.calls ? plural(r.calls, "call") : "—"}</td>
              <td className="w-16 py-2 text-right font-medium tabular">{usd(r.usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {c.unpriced > 0 && <p className="text-xs text-muted-foreground">{plural(c.unpriced, "call")} made before cost tracking aren&apos;t counted.</p>}
      {remaining > 0 && (
        <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
          Finishing what&apos;s missing would cost about <span className="font-semibold text-foreground tabular">{usd(remaining)}</span>.
        </p>
      )}
    </aside>
  );
}
