"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { ArrowRight, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Input, Label, LiveBars, Textarea } from "@/components/ui/primitives";
import { JobProgress } from "@/components/progress";
import { useRoute } from "@/components/shell";
import { imageUsd, useAppState, useJobs } from "@/lib/hooks";
import { api, type Profile, type ProfileKey } from "@/lib/api";
import { cn, usd } from "@/lib/utils";

type Field = { key: ProfileKey; label: string; placeholder: string; picks?: string[]; long?: boolean };

const SECTIONS: { title: string; hint: string; fields: Field[] }[] = [
  {
    title: "Who",
    hint: "",
    fields: [
      { key: "name", label: "Name", placeholder: "Mira Sol" },
      { key: "handle", label: "Handle", placeholder: "@mirasol" },
      { key: "gender", label: "Gender", placeholder: "woman", picks: ["woman", "man", "non-binary"] },
      { key: "age", label: "Age", placeholder: "27", picks: ["19", "24", "29", "35", "45", "60"] },
      { key: "ethnicity", label: "Ethnicity", placeholder: "Filipino" },
    ],
  },
  {
    title: "Look",
    hint: "Be concrete: this is what keeps them recognisable.",
    fields: [
      { key: "hair", label: "Hair", placeholder: "shoulder-length black hair, loose waves, a few greys at the temple" },
      { key: "skin", label: "Skin", placeholder: "warm tan, light freckles across the nose, a small scar on the chin" },
      { key: "body", label: "Body type", placeholder: "petite", picks: ["petite", "slim", "average", "athletic", "curvy", "muscular", "plus-size"] },
      { key: "features", label: "Distinctive features", placeholder: "small mole above the lip, round tortoiseshell glasses", long: true },
    ],
  },
  {
    title: "Style",
    hint: "Each video picks its own outfit; this is their taste and everyday default.",
    fields: [
      { key: "style", label: "Fashion style", placeholder: "thrifted casual, earth tones" },
      { key: "outfit", label: "Go-to outfit", placeholder: "oversized olive knit cardigan over a white tee", long: true },
    ],
  },
  {
    title: "Persona",
    hint: "How they come across on camera, and how they actually talk.",
    fields: [
      {
        key: "niche", label: "Type of influencer", placeholder: "budget cooking",
        picks: ["fitness", "beauty", "food", "tech", "travel", "fashion", "lifestyle", "personal finance", "gaming", "parenting"],
      },
      { key: "persona", label: "Personality", placeholder: "warm, a little chaotic, laughs at her own mistakes", long: true },
      { key: "speech", label: "How they talk", placeholder: "fast, says 'okay so' a lot, ends with 'love you, bye'", long: true },
      { key: "voice", label: "Voice", placeholder: "bright alto, light Manila accent, high energy" },
    ],
  },
  {
    title: "Home",
    hint: "Their place, for at-home videos. Add other places (gym, café, car…) later.",
    fields: [{ key: "setting", label: "Home", placeholder: "a small studio-apartment kitchen: green kettle, fairy lights, plants on the sill", long: true }],
  },
];

const EMPTY = Object.fromEntries(SECTIONS.flatMap((s) => s.fields.map((f) => [f.key, ""]))) as Profile;

/** Design a new influencer, or edit one (`initial` + `id`). */
export function Designer({
  open,
  onOpenChange,
  initial,
  id,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initial?: Profile;
  id?: string;
}) {
  const { data: state } = useAppState();
  const { jobs } = useJobs();
  const { goInf } = useRoute();
  const { mutate } = useSWRConfig();
  const [profile, setProfile] = React.useState<Profile>(initial ?? EMPTY);
  const [concept, setConcept] = React.useState("");
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const job = jobs.find((j) => j.id === jobId);
  const filling = !!jobId && (!job || job.status === "running");

  React.useEffect(() => {
    if (open) setProfile(initial ?? EMPTY);
  }, [open, initial]);

  // AI suggestions land only in fields that are still empty
  React.useEffect(() => {
    if (!job || job.status === "running") return;
    setJobId(null);
    if (job.status === "failed") {
      toast.error("Couldn't design", { description: job.error ?? undefined });
      return;
    }
    const got = (job.result?.profile ?? {}) as Partial<Profile>;
    setProfile((p) => {
      const next = { ...p };
      for (const k of Object.keys(next) as ProfileKey[]) if (!next[k].trim() && got[k]) next[k] = got[k]!;
      return next;
    });
  }, [job]);

  const set = (k: ProfileKey, v: string) => setProfile((p) => ({ ...p, [k]: v }));
  const empty = (Object.keys(profile) as ProfileKey[]).filter((k) => !profile[k].trim());
  const lookChanged = !!initial && (["gender", "age", "ethnicity", "hair", "skin", "body", "features", "outfit", "setting"] as ProfileKey[]).some((k) => initial[k] !== profile[k]);

  const fill = async () => {
    try {
      const j = await api.designInfluencer(profile, concept);
      setJobId(j.id);
      mutate("/api/jobs");
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      if (id) {
        await api.saveInfluencer(id, profile);
        mutate((key) => typeof key === "string" && key.startsWith("/api/influencers"));
        toast.success("Profile saved", lookChanged ? { description: "Their look changed: repaint the identity pack so videos match." } : undefined);
        onOpenChange(false);
      } else {
        const inf = await api.createInfluencer(profile);
        mutate("/api/influencers");
        onOpenChange(false);
        goInf(inf.id, "identity");
      }
    } catch (e) {
      toast.error("Couldn't save", { description: (e as Error).message });
    }
    setSaving(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="right" className="w-[min(720px,calc(100vw-1rem))] gap-0 p-0">
        <div className="border-b px-6 pt-6 pb-5">
          <DialogTitle>{id ? `Edit ${initial?.name}` : "Design an influencer"}</DialogTitle>
          <DialogDescription className="mt-1">
            {id ? "Changes apply to new videos. If you change their look, repaint the identity pack." : "Fill in what you care about. AI completes the rest in the same spirit."}
          </DialogDescription>
          <div className="mt-4 flex items-center gap-2 rounded-xl border bg-card p-1.5 pl-3.5 focus-within:ring-[3px] focus-within:ring-ring/30">
            <Sparkles className="size-4 shrink-0 text-muted-foreground" />
            <input
              value={concept}
              onChange={(e) => setConcept(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !filling && empty.length && fill()}
              placeholder="A concept, e.g. a retired chemistry teacher who reviews gym supplements"
              className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
            />
            <Button size="sm" shape="pill" variant="secondary" onClick={fill} disabled={filling || !empty.length}>
              {filling ? <LiveBars /> : <Sparkles />}
              {empty.length === Object.keys(profile).length ? "Design it" : empty.length ? `Fill ${empty.length} empty` : "All filled"}
            </Button>
          </div>
          {filling && job && <JobProgress job={job} className="mt-3 text-live" />}
        </div>

        <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-6 py-6 scrollbar-thin">
          {SECTIONS.map((sec) => (
            <section key={sec.title}>
              <div className="mb-3 flex items-baseline gap-2">
                <h3 className="text-sm font-semibold">{sec.title}</h3>
                {sec.hint && <span className="text-xs text-muted-foreground">{sec.hint}</span>}
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-3.5">
                {sec.fields.map((f) => (
                  <div key={f.key} className={cn("space-y-1.5", (f.long || f.picks) && "col-span-2")}>
                    <Label htmlFor={`f-${f.key}`}>{f.label}</Label>
                    {f.long ? (
                      <Textarea id={`f-${f.key}`} value={profile[f.key]} onChange={(e) => set(f.key, e.target.value)} placeholder={`e.g. ${f.placeholder}`} className="min-h-9" rows={1} />
                    ) : (
                      <Input id={`f-${f.key}`} value={profile[f.key]} onChange={(e) => set(f.key, e.target.value)} placeholder={`e.g. ${f.placeholder}`} />
                    )}
                    {f.picks && (
                      <div className="flex flex-wrap gap-1">
                        {f.picks.map((v) => (
                          <button
                            key={v}
                            onClick={() => set(f.key, profile[f.key] === v ? "" : v)}
                            className={cn(
                              "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                              profile[f.key] === v ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                            )}
                          >
                            {v}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>

        <div className="flex items-center gap-3 border-t px-6 py-4">
          <p className="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="size-3.5 shrink-0" />
            <span className="truncate">
              Fictional people only.{!id && ` Next: their identity pack, 5 photos ≈ ${usd(imageUsd(state?.settings, 5))}.`}
            </span>
          </p>
          <Button variant="ghost" shape="pill" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button shape="pill" onClick={save} disabled={saving || filling || !profile.name.trim()}>
            {id ? "Save profile" : "Create"}
            {!id && <ArrowRight />}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
