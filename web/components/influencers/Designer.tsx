"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { ArrowRight, Camera, Eyedropper, LayoutGrid, Lightbulb, PencilRuler, ScanSmiley, ShieldCheck } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Input, Label, LiveBars, Textarea } from "@/components/ui/primitives";
import { JobProgress } from "@/components/progress";
import { useRoute } from "@/components/shell";
import { imageUsd, useAppState, useJobResult, useJobs } from "@/lib/hooks";
import { api, type Job, type Profile, type ProfileKey } from "@/lib/api";
import { PhotoDrop, type Photo } from "./PhotoDrop";

const CONSENT = "These are photos of me, or of someone who agreed to be made into an AI character. They are not a celebrity or public figure.";
const FROM_PHOTOS: ProfileKey[] = ["hair", "skin", "body", "features", "style", "outfit"];
const FROM_BOARD: ProfileKey[] = ["hair", "skin", "body", "style", "outfit", "persona"];
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
  const [fromPhotos, setFromPhotos] = React.useState(false);
  const [photos, setPhotos] = React.useState<Photo[]>([]);
  const [consent, setConsent] = React.useState(false);
  const [reading, setReading] = React.useState<string | null>(null);
  const onRead = React.useCallback((j: Job) => {
    setReading(null);
    if (j.status !== "done") return void toast.error("Couldn't read the photos", { description: j.error ?? undefined });
    const got = (j.result?.fields ?? {}) as Partial<Profile>;
    setProfile((p) => {
      const next = { ...p };
      for (const k of FROM_PHOTOS) if (got[k]) next[k] = got[k]!;
      return next;
    });
  }, []);
  useJobResult(reading, onRead);
  const [board, setBoard] = React.useState<Photo[]>([]);
  const [boardOpen, setBoardOpen] = React.useState(false);
  const [readingBoard, setReadingBoard] = React.useState<string | null>(null);
  const onBoard = React.useCallback((j: Job) => {
    setReadingBoard(null);
    if (j.status !== "done") return void toast.error("Couldn't read the mood board", { description: j.error ?? undefined });
    const got = (j.result?.fields ?? {}) as Partial<Profile>;
    setProfile((p) => {
      const next = { ...p };
      for (const k of FROM_BOARD) if (got[k] && !p[k].trim()) next[k] = got[k]!;
      return next;
    });
    toast.success("Type read from your mood board", { description: "Filled the empty fields. Edit anything, then let AI design the rest." });
  }, []);
  useJobResult(readingBoard, onBoard);
  const readBoard = async () => {
    try {
      const j = await api.describePhotos("inspiration", board.map((x) => x.token));
      setReadingBoard(j.id);
      mutate("/api/jobs");
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };

  const readPhotos = async () => {
    try {
      const j = await api.describePhotos("person", photos.map((x) => x.token));
      setReading(j.id);
      mutate("/api/jobs");
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };
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
        const inf = fromPhotos && photos.length
          ? await api.createInfluencer(profile, photos.map((x) => x.token), consent ? CONSENT : "")
          : await api.createInfluencer(profile);
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
            <Lightbulb className="size-4 shrink-0 text-muted-foreground" />
            <input
              value={concept}
              onChange={(e) => setConcept(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !filling && empty.length && fill()}
              placeholder="A concept, e.g. a retired chemistry teacher who reviews gym supplements"
              className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
            />
            <Button size="sm" shape="pill" variant="secondary" onClick={fill} disabled={filling || !empty.length}>
              {filling ? <LiveBars /> : <PencilRuler />}
              {empty.length === Object.keys(profile).length ? "Design it" : empty.length ? `Fill ${empty.length} empty` : "All filled"}
            </Button>
          </div>
          {filling && job && <JobProgress job={job} className="mt-3 text-live" />}
        </div>

        <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-6 py-6 scrollbar-thin">
          {!id && !fromPhotos && (
            <section className="rounded-xl border p-4">
              <label className="flex cursor-pointer items-center gap-3">
                <LayoutGrid className="size-4 text-muted-foreground" />
                <span className="flex-1">
                  <span className="block text-sm font-semibold">Mood board</span>
                  <span className="block text-xs text-muted-foreground">Images of looks, styles and vibes you like, read into words for the type.</span>
                </span>
                <input type="checkbox" checked={boardOpen} onChange={(e) => setBoardOpen(e.target.checked)} className="size-4 accent-foreground" />
              </label>
              {boardOpen && (
                <div className="mt-4 space-y-3">
                  <PhotoDrop photos={board} onChange={setBoard} max={8} hint="Up to 8: people whose type you like, outfits, makeup, aesthetics. Mixing several gives a clearer type." />
                  <Button size="sm" variant="secondary" shape="pill" onClick={readBoard} disabled={!board.length || !!readingBoard}>
                    {readingBoard ? <LiveBars /> : <Eyedropper />}
                    Read the type
                  </Button>
                  <p className="text-[11px] text-muted-foreground">
                    Fills hair, skin, build, style, outfit and personality. Faces aren&apos;t described and the images are only read, never sent to the image or video models or kept, so your creator gets a face of their own.
                  </p>
                </div>
              )}
            </section>
          )}
          {!id && !boardOpen && (
            <section className="rounded-xl border p-4">
              <label className="flex cursor-pointer items-center gap-3">
                <Camera className="size-4 text-muted-foreground" />
                <span className="flex-1">
                  <span className="block text-sm font-semibold">Start from photos of a real person</span>
                  <span className="block text-xs text-muted-foreground">Yourself, or someone who agreed. Their face and body; the voice is still described in words.</span>
                </span>
                <input type="checkbox" checked={fromPhotos} onChange={(e) => setFromPhotos(e.target.checked)} className="size-4 accent-foreground" />
              </label>
              {fromPhotos && (
                <div className="mt-4 space-y-3">
                  <PhotoDrop photos={photos} onChange={setPhotos} max={6} hint="2-6 photos: a clear front face, a three-quarter view, and one full length. Good light, no filters, no sunglasses." />
                  <label className="flex cursor-pointer items-start gap-2 text-xs">
                    <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 size-4 accent-foreground" />
                    <span>{CONSENT}</span>
                  </label>
                  <Button size="sm" variant="secondary" shape="pill" onClick={readPhotos} disabled={!photos.length || !!reading}>
                    {reading ? <LiveBars /> : <ScanSmiley />}
                    Describe their look from the photos
                  </Button>
                  <p className="text-[11px] text-muted-foreground">Fills hair, skin, build, features and style. Name, age, gender and background are yours to write. Video models may refuse well-known faces.</p>
                </div>
              )}
            </section>
          )}
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
              {fromPhotos ? "Only people who agreed." : "Fictional people only."}{!id && ` Next: their identity pack, 5 photos ≈ ${usd(imageUsd(state?.settings, 5))}.`}
            </span>
          </p>
          <Button variant="ghost" shape="pill" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button shape="pill" onClick={save} disabled={saving || filling || !profile.name.trim() || (fromPhotos && (!photos.length || !consent))}>
            {id ? "Save profile" : "Create"}
            {!id && <ArrowRight />}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
