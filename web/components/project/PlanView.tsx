"use client";

import * as React from "react";
import { Braces, Clapperboard, MapPin, Mic, Package, Palette, Plus, Trash2, Users } from "@/components/icons";
import { Badge, InlineText, Segmented, Textarea, Tip } from "@/components/ui/primitives";
import type { Beat, Pacing, Plan, PlanScene, Project } from "@/lib/api";
import { useAppState } from "@/lib/hooks";
import { useProjectActions } from "./actions";
import { BeatsEditor, DirectorNotes } from "./Beats";
import { cn } from "@/lib/utils";

type Update = (fn: (p: Plan) => void) => void;

export function PlanView({ p, draft, setDraft }: { p: Project; draft: Plan; setDraft: (p: Plan | null) => void }) {
  const [raw, setRaw] = React.useState(false);
  const act = useProjectActions(p);
  const { data: state } = useAppState();
  const update: Update = (fn) => {
    const next = structuredClone(draft);
    fn(next);
    setDraft(next);
  };

  const sections = [
    { id: "style", label: "Style", icon: Palette },
    { id: "cast", label: "Cast", icon: Users, n: draft.characters.length },
    { id: "props", label: "Props", icon: Package, n: draft.props.length },
    { id: "locations", label: "Locations", icon: MapPin, n: draft.environments.length },
    { id: "scenes", label: "Scenes", icon: Clapperboard, n: draft.scenes.length },
  ];

  return (
    <div className="grid gap-10 xl:grid-cols-[180px_1fr]">
      <aside className="hidden xl:block">
        <nav className="sticky top-24 space-y-0.5">
          {sections.map((s) => (
            <a key={s.id} href={`#${s.id}`} className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <s.icon className="size-4" />
              {s.label}
              {s.n != null && <span className="ml-auto text-xs tabular">{s.n}</span>}
            </a>
          ))}
          <button onClick={() => setRaw(!raw)} className={cn("mt-4 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors hover:bg-accent", raw ? "text-foreground" : "text-muted-foreground")}>
            <Braces className="size-4" />
            Raw JSON
          </button>
        </nav>
      </aside>

      <div className="min-w-0 space-y-12">
        <DirectorNotes p={p} plan={p.plan} dirty={JSON.stringify(draft) !== JSON.stringify(p.plan)} onDirect={act.direct} />
        <p className="-mt-2 text-sm text-muted-foreground">
          This is the production plan every image and clip is built from. Edit anything by clicking it — prompts are rebuilt from it, so the look stays consistent.
          {Object.keys(p.plan.prompt_overrides ?? {}).length > 0 && " Items with a custom prompt keep their custom prompt."}
        </p>

        {raw ? <RawEditor draft={draft} setDraft={setDraft} /> : (
          <>
            <Section id="style" title="Style" hint="Applied to every image and clip">
              <Card className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                {STYLE_FIELDS.filter(([k]) => k in draft.style).map(([k, label]) => (
                  <Field key={k} label={label}>
                    <InlineText value={draft.style[k] ?? ""} onChange={(v) => update((d) => void (d.style[k] = v))} />
                  </Field>
                ))}
              </Card>
              {state && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <span className="text-xs font-medium text-muted-foreground">Pacing</span>
                  <Segmented<Pacing>
                    size="sm"
                    value={draft.pacing ?? "balanced"}
                    onChange={(v) => update((d) => void (d.pacing = v))}
                    options={state.pacing.map((x) => ({ value: x.id, label: x.label, title: x.brief }))}
                  />
                  <span className="text-xs text-muted-foreground">{state.pacing.find((x) => x.id === (draft.pacing ?? "balanced"))?.brief}</span>
                </div>
              )}
            </Section>

            <Section id="cast" title="Cast" hint="Each gets a turnaround reference sheet">
              <div className="grid gap-4 lg:grid-cols-2">
                {draft.characters.map((c, i) => (
                  <Card key={c.id}>
                    <CardHead name={c.name} id={c.id} onName={(v) => update((d) => void (d.characters[i].name = v))} />
                    <Field label="Appearance"><InlineText value={c.appearance} onChange={(v) => update((d) => void (d.characters[i].appearance = v))} /></Field>
                    <Field label="Costume"><InlineText value={c.costume} onChange={(v) => update((d) => void (d.characters[i].costume = v))} /></Field>
                    <Field label={<><Mic className="size-3" /> Voice</>}><InlineText value={c.voice} onChange={(v) => update((d) => void (d.characters[i].voice = v))} /></Field>
                  </Card>
                ))}
              </div>
            </Section>

            {draft.props.length > 0 && (
              <Section id="props" title="Props" hint="Recurring objects that must look the same in every shot">
                <div className="grid gap-4 lg:grid-cols-2">
                  {draft.props.map((pr, i) => (
                    <Card key={pr.id}>
                      <CardHead name={pr.name} id={pr.id} onName={(v) => update((d) => void (d.props[i].name = v))} />
                      <InlineText value={pr.description} onChange={(v) => update((d) => void (d.props[i].description = v))} className="text-sm" />
                    </Card>
                  ))}
                </div>
              </Section>
            )}

            <Section id="locations" title="Locations" hint="Variants reuse their base plate so the place stays the same">
              <div className="grid gap-4 lg:grid-cols-2">
                {draft.environments.map((e, i) => (
                  <Card key={e.id}>
                    <CardHead name={e.name} id={e.id} onName={(v) => update((d) => void (d.environments[i].name = v))}>
                      {e.based_on && <Badge tone="outline">variant of {e.based_on}</Badge>}
                    </CardHead>
                    <Field label="Time & weather"><InlineText value={e.time_and_weather} onChange={(v) => update((d) => void (d.environments[i].time_and_weather = v))} /></Field>
                    <Field label="Description"><InlineText value={e.description} onChange={(v) => update((d) => void (d.environments[i].description = v))} /></Field>
                    <Field label="Lighting"><InlineText value={e.lighting} onChange={(v) => update((d) => void (d.environments[i].lighting = v))} /></Field>
                  </Card>
                ))}
              </div>
            </Section>

            <Section id="scenes" title="Scenes" hint="One clip each. One clear action, one camera move.">
              <ol className="space-y-4">
                {draft.scenes.map((sc, i) => (
                  <SceneEditor key={sc.id} sc={sc} i={i} plan={draft} update={update} />
                ))}
              </ol>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}

const STYLE_FIELDS = [
  ["medium", "Medium"], ["look", "Look"], ["color_grade", "Colour grade"], ["lens", "Lens"],
  ["motion", "Motion"], ["camera_grammar", "Camera grammar"], ["sheet_look", "Reference sheets"], ["avoid", "Avoid"],
] as const;

function SceneEditor({ sc, i, plan, update }: { sc: PlanScene; i: number; plan: Plan; update: Update }) {
  const set = <K extends keyof PlanScene>(k: K, v: PlanScene[K]) => update((d) => void (d.scenes[i][k] = v));
  const groups = [
    { label: "Location", items: plan.environments.map((e) => ({ id: e.id, name: e.name })) },
    { label: "Cast", items: plan.characters.map((c) => ({ id: c.id, name: c.name })) },
    { label: "Props", items: plan.props.map((x) => ({ id: x.id, name: x.name })) },
  ];
  const toggleRef = (id: string) =>
    update((d) => {
      const refs = d.scenes[i].refs;
      d.scenes[i].refs = refs.includes(id) ? refs.filter((r) => r !== id) : [...refs, id];
    });
  const envCount = sc.refs.filter((r) => plan.environments.some((e) => e.id === r)).length;

  return (
    <li className="relative grid grid-cols-[48px_1fr] gap-4">
      <div className="flex flex-col items-center">
        <span className="flex size-10 items-center justify-center rounded-full border bg-card font-mono text-xs font-semibold">{String(i + 1).padStart(2, "0")}</span>
        {i < plan.scenes.length - 1 && <span className={cn("mt-2 w-px grow", plan.scenes[i + 1]?.continuity === "continuous" ? "bg-foreground/40" : "bg-border")} />}
      </div>
      <Card className="mb-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{sc.id}</span>
          {sc.beats?.length ? (
            <Tip content="Set by the beats">
              <span className="flex h-7 items-center rounded-full bg-muted px-2.5 text-xs font-medium tabular">
                {Math.max(2, Math.ceil(sc.beats.at(-1)!.t_end - 1e-6))}s
              </span>
            </Tip>
          ) : (
            <div className="flex h-7 items-center rounded-full bg-muted px-2 text-xs font-medium">
              <input
                type="number"
                min={2}
                max={10}
                value={sc.duration_s}
                onChange={(e) => set("duration_s", Math.max(2, Math.min(10, Number(e.target.value) || 6)))}
                className="w-7 bg-transparent text-center tabular outline-none"
              />
              s
            </div>
          )}
          <Segmented
            size="sm"
            value={sc.continuity}
            onChange={(v) => set("continuity", v)}
            options={[
              { value: "cut", label: "Cut" },
              { value: "continuous", label: "Continuous", disabled: i === 0, title: "Starts on the last frame of the previous scene" },
            ]}
          />
        </div>
        <InlineText value={sc.action} onChange={(v) => set("action", v)} className="text-[15px] font-medium" />
        {sc.beats && (
          <BeatsEditor
            sc={sc}
            onChange={(beats: Beat[], multi?: boolean) =>
              update((d) => {
                const s2 = d.scenes[i];
                s2.beats = beats;
                if (multi !== undefined) s2.multi_shot = multi;
                if (beats.length) s2.duration_s = Math.max(2, Math.ceil(beats.at(-1)!.t_end - 1e-6));
              })
            }
          />
        )}
        <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <Field label={sc.beats ? "Opening framing" : "Shot"}><InlineText value={sc.shot} onChange={(v) => set("shot", v)} className="text-sm" /></Field>
          <Field label="Camera"><InlineText value={sc.camera} onChange={(v) => set("camera", v)} className="text-sm" /></Field>
          <Field label="Lighting"><InlineText value={sc.lighting} onChange={(v) => set("lighting", v)} className="text-sm" /></Field>
          <Field label="Sound"><InlineText value={sc.audio} onChange={(v) => set("audio", v)} className="text-sm" /></Field>
        </div>

        <Field label="Dialogue">
          <div className="space-y-1.5">
            {(sc.dialogue ?? []).map((d, j) => (
              <div key={j} className="group flex items-start gap-2">
                <select
                  value={d.speaker}
                  onChange={(e) => update((p) => void (p.scenes[i].dialogue![j].speaker = e.target.value))}
                  className="mt-0.5 h-7 rounded-md border bg-transparent px-1.5 text-xs font-medium outline-none dark:bg-input/30"
                >
                  {plan.characters.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                  {!plan.characters.some((c) => c.name === d.speaker) && <option value={d.speaker}>{d.speaker}</option>}
                </select>
                <InlineText value={d.line} onChange={(v) => update((p) => void (p.scenes[i].dialogue![j].line = v))} className="text-sm italic" />
                <button onClick={() => update((p) => void p.scenes[i].dialogue!.splice(j, 1))} className="mt-1 rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive" aria-label="Remove line">
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
            <button
              onClick={() => update((p) => void (p.scenes[i].dialogue = [...(p.scenes[i].dialogue ?? []), { speaker: plan.characters[0]?.name ?? "", line: "" }]))}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <Plus className="size-3.5" /> Add a line
            </button>
          </div>
        </Field>

        <Field label={<>In this shot {envCount !== 1 && <span className="font-normal text-live">· pick exactly one location</span>}</>}>
          <div className="flex flex-wrap gap-1.5">
            {groups.flatMap((g) =>
              g.items.map((it) => {
                const on = sc.refs.includes(it.id);
                return (
                  <Tip key={it.id} content={`${g.label} · ${it.id}`}>
                    <button
                      onClick={() => toggleRef(it.id)}
                      className={cn(
                        "rounded-full border px-2.5 py-1 text-xs transition-colors",
                        on ? "border-foreground/20 bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                      )}
                    >
                      {it.name}
                    </button>
                  </Tip>
                );
              }),
            )}
          </div>
        </Field>
      </Card>
    </li>
  );
}

function RawEditor({ draft, setDraft }: { draft: Plan; setDraft: (p: Plan | null) => void }) {
  const [text, setText] = React.useState(() => JSON.stringify(draft, null, 2));
  const [err, setErr] = React.useState<string | null>(null);
  return (
    <div className="space-y-2">
      <Textarea
        value={text}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          try {
            setDraft(JSON.parse(e.target.value));
            setErr(null);
          } catch (x) {
            setErr((x as Error).message);
          }
        }}
        className="min-h-[70vh] font-mono text-xs leading-relaxed"
      />
      {err && <p className="text-xs text-destructive">{err}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- bits

function Section({ id, title, hint, children }: { id: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24">
      <div className="mb-4 flex items-baseline gap-3">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("space-y-3 rounded-xl border bg-card p-5", className)}>{children}</div>;
}

function CardHead({ name, id, onName, children }: { name: string; id: string; onName: (v: string) => void; children?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <InlineText multiline={false} value={name} onChange={onName} className="font-semibold" />
      {children}
      <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{id}</span>
    </div>
  );
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}
