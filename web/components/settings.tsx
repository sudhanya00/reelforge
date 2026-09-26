"use client";

import * as React from "react";
import { useSWRConfig } from "swr";
import { toast } from "sonner";
import { CheckCircle2, CircleAlert, PlugZap, RectangleHorizontal, RectangleVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger, Input, Label, Segmented, Spinner } from "@/components/ui/primitives";
import { providerInfo, resolutionFor, useAppState, videoUsd } from "@/lib/hooks";
import { api, type Backend, type Resolution, type Settings } from "@/lib/api";
import { cn, usd } from "@/lib/utils";

const MODEL_FIELDS = [
  { key: "planner_model", label: "Planner", hint: "writes the production plan" },
  { key: "image_model", label: "References", hint: "character, prop and location sheets" },
  { key: "video_model", label: "Video", hint: "shoots and edits each scene" },
] as const;

export function SettingsDialog({ children }: { children: React.ReactNode }) {
  const { data, mutate } = useAppState();
  const { mutate: globalMutate } = useSWRConfig();
  const s = data?.settings;

  const save = async (patch: Parameters<typeof api.saveSettings>[0]) => {
    try {
      const next = await api.saveSettings(patch);
      mutate(next, { revalidate: false });
      globalMutate((k) => typeof k === "string" && k.startsWith("/api/projects"));
    } catch (e) {
      toast.error("Couldn't save settings", { description: String((e as Error).message) });
    }
  };

  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent side="right" className="gap-0 overflow-y-auto p-0 scrollbar-thin">
        <div className="border-b px-6 py-5">
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription className="mt-1">Saved as you change them. Costs update everywhere.</DialogDescription>
        </div>
        {!s ? (
          <div className="flex justify-center p-10"><Spinner /></div>
        ) : (
          <div className="divide-y">
            <Section title="Video model" description="Shoots every scene unless a scene picks another model.">
              <div className="space-y-2">
                {s.providers.map((pr) => {
                  const on = pr.id === s.video_provider;
                  const res = resolutionFor(pr, s.resolution);
                  return (
                    <button
                      key={pr.id}
                      disabled={!pr.configured}
                      onClick={() => !on && save({ video_provider: pr.id })}
                      className={cn(
                        "flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors disabled:cursor-not-allowed",
                        on ? "border-foreground/40 bg-accent/60" : "hover:bg-accent/40",
                      )}
                    >
                      <span className={cn("mt-1 flex size-4 shrink-0 items-center justify-center rounded-full border", on && "border-foreground")}>
                        {on && <span className="size-2 rounded-full bg-foreground" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="text-sm font-medium">{pr.label}</span>
                          <span className="text-xs text-muted-foreground tabular">
                            {usd(pr.price_per_s[res], 3)}/s at {res}
                          </span>
                        </span>
                        <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">{pr.model}</span>
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {pr.configured
                            ? `${pr.caps.durations[0]}-${pr.caps.durations[1]}s clips · ${pr.caps.resolutions.join(", ")} · up to ${pr.caps.max_refs} reference images`
                            : pr.setup}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
              {providerInfo(s, "kling")?.configured && (
                <label className="flex cursor-pointer items-center justify-between gap-3 text-sm">
                  <span>
                    Kling native audio
                    <span className="ml-1.5 text-xs text-muted-foreground">sound design and dialogue; costs a little more</span>
                  </span>
                  <input type="checkbox" checked={s.kling_audio} onChange={(e) => save({ kling_audio: e.target.checked })} className="size-4 accent-foreground" />
                </label>
              )}
            </Section>

            <Section title="Generation">
              <Field label="Video resolution" hint="720p for films, 360p for cheap tests">
                <Segmented<Resolution>
                  value={s.resolution}
                  onChange={(v) => save({ resolution: v })}
                  options={(["360p", "720p", "1080p", "4k"] as Resolution[]).map((r) => {
                    const def = providerInfo(s);
                    const blocked = s.video_provider === "gemini-omni" && !s.high_res_ready && (r === "1080p" || r === "4k");
                    const mapped = resolutionFor(def, r) !== r;
                    return {
                      value: r,
                      disabled: blocked,
                      title: blocked ? "Needs a Cloud Storage bucket (below)" : undefined,
                      label: (
                        <span className="flex flex-col items-center leading-tight">
                          <span>{r}</span>
                          <span className="text-[10px] font-normal opacity-60 tabular">
                            {mapped ? `→ ${resolutionFor(def, r)}` : `${usd(videoUsd(s, 1, r), 3)}/s`}
                          </span>
                        </span>
                      ),
                    };
                  })}
                  className="[&>button]:h-11 [&>button]:px-4"
                />
              </Field>
              {s.backend === "vertex" && <BucketField s={s} />}
              <Field label="Reference image size" hint="1K and 2K cost the same">
                <Segmented value={s.image_size} onChange={(v) => save({ image_size: v })} options={["1K", "2K", "4K"].map((v) => ({ value: v as Settings["image_size"], label: v }))} />
              </Field>
              <Field label="New films are">
                <Segmented
                  value={s.orientation}
                  onChange={(v) => save({ orientation: v })}
                  options={[
                    { value: "9:16", label: <><RectangleVertical />Vertical 9:16</> },
                    { value: "16:9", label: <><RectangleHorizontal />Horizontal 16:9</> },
                  ]}
                />
              </Field>
            </Section>

            <Section title="Account">
              <Field label="Bill generation to">
                <Segmented<Backend>
                  value={s.backend}
                  onChange={(v) => save({ backend: v })}
                  options={[
                    { value: "vertex", label: "Vertex AI · GCP credits" },
                    { value: "gemini", label: "Gemini API key" },
                  ]}
                />
              </Field>
              {s.backend === "vertex" ? (
                <div className="grid grid-cols-[1fr_140px] gap-3">
                  <Field label="GCP project">
                    <BlurInput value={s.gcp_project} onCommit={(v) => save({ gcp_project: v })} placeholder="my-project-id" />
                  </Field>
                  <Field label="Location">
                    <BlurInput value={s.gcp_location} onCommit={(v) => save({ gcp_location: v })} placeholder="global" />
                  </Field>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Uses <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">GEMINI_API_KEY</code> from the{" "}
                  <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">.env</code> file.
                </p>
              )}
              <ConnectionCheck key={`${s.backend}-${s.gcp_project}`} />
            </Section>

            <Section title="Models" description="Preview models get renamed; change the ids here when they do.">
              {MODEL_FIELDS.map((f) => {
                const def = s.default_models[s.backend][f.key];
                return (
                  <Field
                    key={`${s.backend}-${f.key}`}
                    label={f.label}
                    hint={f.hint}
                    action={
                      s[f.key] !== def && (
                        <button className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline" onClick={() => save({ models: { [s.backend]: { [f.key]: def } } })}>
                          Reset
                        </button>
                      )
                    }
                  >
                    <BlurInput className="font-mono text-xs" value={s[f.key]} onCommit={(v) => save({ models: { [s.backend]: { [f.key]: v || def } } })} />
                  </Field>
                );
              })}
            </Section>

            <Section title="Storage">
              <p className="text-sm break-all text-muted-foreground">
                Films are saved in <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{data.projects_dir}</code>
              </p>
            </Section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 px-6 py-5">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, hint, action, children }: { label: string; hint?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <Label>
          {label}
          {hint && <span className="ml-1.5 font-normal text-muted-foreground/70">· {hint}</span>}
        </Label>
        {action}
      </div>
      {children}
    </div>
  );
}

function BlurInput({ value, onCommit, ...props }: { value: string; onCommit: (v: string) => void } & Omit<React.ComponentProps<"input">, "value" | "onChange">) {
  const [v, setV] = React.useState(value);
  React.useEffect(() => setV(value), [value]);
  const commit = () => v.trim() !== value && onCommit(v.trim());
  return <Input value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.currentTarget.blur())} {...props} />;
}

function ConnectionCheck() {
  const [state, setState] = React.useState<{ busy?: boolean; ok?: boolean; message?: string }>({});
  const run = async () => {
    setState({ busy: true });
    try {
      const r = await api.checkConnection();
      setState({ ok: r.ok, message: r.message });
    } catch (e) {
      setState({ ok: false, message: String((e as Error).message) });
    }
  };
  return (
    <div className="space-y-2">
      <Button variant="outline" size="sm" shape="pill" onClick={run} disabled={state.busy}>
        {state.busy ? <Spinner /> : <PlugZap />}
        Check connection
        <span className="text-xs font-normal text-muted-foreground">free</span>
      </Button>
      {state.message && (
        <p className={cn("flex items-start gap-2 rounded-lg px-3 py-2 text-sm", state.ok ? "bg-ok/10" : "bg-destructive/10")}>
          {state.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />}
          {state.message}
        </p>
      )}
    </div>
  );
}

/** Vertex delivers Omni 1080p/4K through Cloud Storage; this sets up the bucket. */
function BucketField({ s }: { s: Settings }) {
  const { mutate } = useAppState();
  const [busy, setBusy] = React.useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const r = await api.createBucket();
      mutate(r, { revalidate: false });
      toast.success(r.bucket.created ? `Created gs://${r.bucket.name}` : `Using gs://${r.bucket.name}`, {
        description: "1080p and 4K are available now. Videos pass through it and are deleted from it after download.",
      });
    } catch (e) {
      toast.error("Couldn't set up the bucket", { description: (e as Error).message });
    }
    setBusy(false);
  };
  return (
    <Field label="1080p and 4K delivery" hint="Vertex delivers them through Cloud Storage in your project">
      {s.gcs_bucket ? (
        <p className="text-sm">
          <span className="font-mono text-xs">gs://{s.gcs_bucket}</span>
          <span className="ml-2 text-xs text-muted-foreground">private · files kept at most a day</span>
        </p>
      ) : (
        <Button size="sm" variant="outline" shape="pill" onClick={create} disabled={busy || !s.gcp_project}>
          Create bucket {s.gcp_project ? `in ${s.gcp_project}` : ""}
        </Button>
      )}
    </Field>
  );
}
