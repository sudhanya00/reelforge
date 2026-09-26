// Types + calls for server.py. Keep in sync with its *_view() functions.
import type { CaptionCatalog, CaptionState, CaptionStyle } from "./captions";
import type { EditParams } from "./edit";

export const API = process.env.NEXT_PUBLIC_API ?? "";

export const url = (path: string | null | undefined) => (path ? `${API}${path}` : undefined);

export type Resolution = "360p" | "720p" | "1080p" | "4k";
export type Orientation = "9:16" | "16:9";
export type Backend = "vertex" | "gemini";
type Models = { planner_model: string; image_model: string; video_model: string };

export interface ProviderInfo {
  id: string;
  label: string;
  model: string;
  configured: boolean;
  setup: string;
  caps: {
    resolutions: Resolution[];
    durations: [number, number];
    aspects: string[];
    max_refs: number;
    first_frame: boolean;
    edit: boolean;
    audio: boolean;
    extend: boolean;
  };
  price_per_s: Partial<Record<Resolution, number>>;
  edit_price_per_s: Partial<Record<Resolution, number>>;
}

export interface Settings extends Models {
  backend: Backend;
  gcp_project: string;
  gcp_location: string;
  resolution: Resolution;
  image_size: "1K" | "2K" | "4K";
  orientation: Orientation;
  video_provider: string;
  kling_audio: boolean;
  gcs_bucket: string;
  high_res_ready: boolean;
  providers: ProviderInfo[];
  default_models: Record<Backend, Models>;
  prices: { image: number; video_per_s: Record<Resolution, number> };
}

export interface AppState {
  settings: Settings;
  ffmpeg: boolean;
  fake: boolean;
  projects_dir: string;
  typical_s: Record<string, number>;
  styles: { id: string; label: string; pacing: Pacing }[];
  pacing: { id: Pacing; label: string; brief: string }[];
  planner_version: string;
  stale: boolean;
}

export type Pacing = "calm" | "balanced" | "kinetic";

export interface ProjectSummary {
  id: string;
  title: string;
  logline: string;
  orientation: Orientation;
  poster: string | null;
  refs: [number, number];
  scenes: [number, number];
  final: boolean;
  cost_usd: number;
  updated: number;
  busy: boolean;
}

export type ItemStatus = "missing" | "generating" | "done";

export interface Asset {
  id: string;
  kind: "character" | "prop" | "environment";
  name: string;
  description: string;
  prompt: string;
  default_prompt: string;
  overridden: boolean;
  base: string | null;
  aspect: Orientation;
  image: string | null;
  status: ItemStatus;
  error: string | null;
  library_id: string | null;
}

export interface LibraryCharacter {
  id: string;
  name: string;
  appearance: string;
  costume: string;
  voice: string;
  image: string | null;
  source: { project: string; id: string };
  saved: number;
}

export interface Review {
  summary: string;
  verdict: "keep" | "fix" | "reshoot";
  overall: number;
  scores: Record<string, { score: number; note: string }>;
  issues: { t_start: number; t_end: number; category: string; severity: "minor" | "major" | "fatal"; description: string }[];
  beats_observed: { t_start: number; t_end: number; what: string }[];
  dead_time_s: number;
  fix_instruction: string;
  prompt_advice: string;
  cost_usd: number | null;
}

export interface Take {
  name: string;
  url: string;
  poster: string;
  duration_s: number | null;
  cost_usd: number | null;
  resolution: Resolution | null;
  edited_from: string | null;
  edit: string | null;
  prompt: string | null;
  created: number;
  provider: string;
  model: string | null;
  review: Review | null;
  motion: { dead: [number, number][]; dead_s: number; cuts: number[] } | null;
}

export interface Beat {
  t_start: number;
  t_end: number;
  action: string;
  camera: string;
  cut?: boolean;
  hold?: boolean;
}

export interface PlanScene {
  id: string;
  duration_s: number;
  beats?: Beat[];
  multi_shot?: boolean;
  risks?: { what: string; handling: string }[];
  refs: string[];
  shot: string;
  action: string;
  camera: string;
  lighting: string;
  dialogue?: { speaker: string; line: string }[];
  audio: string;
  continuity: "cut" | "continuous";
}

export interface Scene extends PlanScene {
  prompt: string;
  default_prompt: string;
  overridden: boolean;
  refs_used: string[];
  refs_missing: string[];
  provider: string;
  provider_chosen: boolean;
  /** what it will actually be shot at, after mapping to the provider's limits */
  render: { resolution: Resolution; duration_s: number };
  takes: Take[];
  selected: string | null;
  status: ItemStatus;
  error: string | null;
}

export interface Character { id: string; name: string; appearance: string; costume: string; voice: string }
export interface Prop { id: string; name: string; description: string }
export interface Environment {
  id: string; name: string; description: string; time_and_weather: string; lighting: string; based_on?: string;
}

export interface Plan {
  title: string;
  logline: string;
  style: {
    look: string; color_grade: string; lens: string; avoid: string;
    medium?: string; motion?: string; camera_grammar?: string; sheet_look?: string;
  };
  pacing?: Pacing;
  director_notes?: { scene: string; change: string; reason: string }[];
  brief?: { story: string; style: string; preset: string | null; pacing: Pacing | null };
  planner?: string;
  characters: Character[];
  props: Prop[];
  environments: Environment[];
  scenes: PlanScene[];
  orientation?: Orientation;
  prompt_overrides?: Record<string, string>;
  selected_takes?: Record<string, string>;
}

export interface Costs {
  usd: number;
  calls: number;
  unpriced: number;
  video_s: number;
  by_kind: Record<string, { calls: number; usd: number }>;
}

export interface Project {
  id: string;
  plan: Plan;
  orientation: Orientation;
  assets: Asset[];
  scenes: Scene[];
  final: { url: string; poster: string; duration_s: number | null; updated: number } | null;
  edit: EditState | null;
  costs: Costs;
  busy: string[];
}

export interface Job {
  id: string;
  kind: "plan" | "film" | "assets" | "take" | "edit" | "produce" | "stitch" | "review" | "direct"
    | "design" | "identity" | "script" | "reel" | "place" | "opening" | "export" | "sync" | "describe" | "product" | "casting";
  label: string;
  project: string | null;
  claims: string[];
  status: "running" | "done" | "failed";
  logs: string[];
  error: string | null;
  result: Record<string, unknown> | null;
  started: number;
  finished: number | null;
  progress: {
    kind: string;
    key: string;
    label: string;
    done: number;
    total: number;
    step_started: number;
    expected_s: number;
  } | null;
}

// ---------------------------------------------------------------- influencers

export type ProfileKey =
  | "name" | "handle" | "gender" | "age" | "ethnicity" | "skin" | "hair" | "body" | "features"
  | "style" | "outfit" | "niche" | "persona" | "speech" | "voice" | "setting";
export type Profile = Record<ProfileKey, string>;
export type IdentityView = "face" | "three_quarter" | "profile" | "full_body" | "setting";

export interface InfluencerSummary {
  id: string;
  profile: Profile;
  created: number;
  face: string | null;
  identity_done: number;
  identity_total: number;
  videos_count: number;
  cost_usd: number;
  busy: boolean;
}

export interface IdentityImage {
  view: IdentityView;
  aspect: "3:4" | "9:16";
  from_face: boolean;
  image: string | null;
  status: "generating" | "done" | "missing";
  error: string | null;
  prompt: string;
  overridden: boolean;
  stale: boolean;
}

export interface CastingOption {
  name: string;
  url: string;
  notes: string;
  from: string | null;
  created: number;
}

export interface Segment {
  id: string;
  seconds: number;
  lines: string[];
  delivery: string;
  action: string;
}

export interface VideoSummary {
  id: string;
  title: string;
  hook: string;
  format: string;
  seconds: number;
  final: string | null;
  poster: string | null;
  cost_usd: number;
  busy: boolean;
  updated: number;
}

export interface Turn {
  name: string;
  url: string;
  segment: string;
  duration_s: number | null;
  cost_usd: number | null;
  prompt: string;
  extends: string | null;
}

export interface EditState {
  params: EditParams;
  url: string | null;
  stale: boolean;
  duration_s: number | null;
}

export type ProductUse = "wear" | "hold";

export interface Setup {
  place: string;
  location: string;
  outfit: string;
  position: string;
  light: string;
  products: { id: string; use: ProductUse }[];
}

export interface Product {
  id: string;
  name: string;
  brand: string;
  kind: string;
  description: string;
  notes: string;
  use: ProductUse;
  packshot: string | null;
  photos: string[];
  status: "generating" | "done" | "missing";
  error: string | null;
}

export interface Place {
  id: string;
  name: string;
  description: string;
  image: string | null;
  status: "generating" | "done" | "missing";
  error: string | null;
}

export interface Format {
  id: string;
  label: string;
  blurb: string;
  empty_open: boolean;
}

export interface Video extends VideoSummary {
  caption: string;
  brief: { topic?: string; points?: string; length_s?: number };
  segments: Segment[];
  turns: Turn[];
  extension_mode: "cumulative" | "segments" | null;
  error: string | null;
  costs: { usd: number; calls: number };
  setup: Setup;
  featured: { id: string; name: string; brand: string; use: ProductUse; image: string }[];
  edit: EditState | null;
  captions: CaptionState;
  opening: { opening?: string | null; look?: string | null };
  opening_ok: boolean;
  opening_error: string | null;
  estimate: { seconds: number; turns: number; resolution: Resolution; video_usd: number; images_usd: number; usd: number };
}

export interface Influencer extends InfluencerSummary {
  identity: IdentityImage[];
  identity_usd: number;
  places: Place[];
  sources: { name: string; url: string }[];
  casting: { candidates: CastingOption[]; locked: string | null; busy: boolean };
  consent: { text: string; at: number } | null;
  videos: VideoSummary[];
}

export interface InfluencerList {
  influencers: InfluencerSummary[];
  design_usd: number;
  fields: { id: ProfileKey; label: string }[];
  formats: Format[];
}

export class ApiError extends Error {}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new ApiError(msg);
  }
  return res.json() as Promise<T>;
}

export const fetcher = <T,>(path: string) => call<T>("GET", path);

export const api = {
  saveSettings: (s: Partial<Settings> & { models?: Partial<Record<Backend, Partial<Models>>> }) =>
    call<AppState>("PUT", "/api/settings", s),
  checkConnection: () =>
    call<{ ok: boolean; message: string; models: Record<string, boolean> }>("POST", "/api/settings/check"),
  newFilm: (b: { story: string; style: string; scenes: number; orientation: Orientation; auto: boolean;
                  preset: string | null; pacing: Pacing; cast: string[] }) =>
    call<Job>("POST", "/api/projects", b),
  savePlan: (id: string, plan: Plan) => call<Project>("PUT", `/api/projects/${id}/plan`, { plan }),
  setPrompt: (id: string, item: string, prompt: string | null, provider?: string) =>
    call<Project>("PUT", `/api/projects/${id}/prompt`, { id: item, prompt, provider: provider ?? null }),
  setSceneProvider: (id: string, scene: string, provider: string | null) =>
    call<Project>("PUT", `/api/projects/${id}/scenes/${scene}/provider`, { provider }),
  select: (id: string, scene: string, take: string) =>
    call<Project>("PUT", `/api/projects/${id}/scenes/${scene}/selected`, { take }),
  makeAssets: (id: string, ids?: string[], force = false) =>
    call<Job>("POST", `/api/projects/${id}/assets`, { ids: ids ?? null, force }),
  shoot: (id: string, scene: string) => call<Job>("POST", `/api/projects/${id}/scenes/${scene}/takes`),
  fix: (id: string, scene: string, take: string, instruction: string) =>
    call<Job>("POST", `/api/projects/${id}/scenes/${scene}/takes/${take}/edit`, { instruction }),
  produce: (id: string) => call<Job>("POST", `/api/projects/${id}/produce`),
  direct: (id: string) => call<Job>("POST", `/api/projects/${id}/direct`),
  review: (id: string, scene: string, take: string) =>
    call<Job>("POST", `/api/projects/${id}/scenes/${scene}/takes/${take}/review`),
  stitch: (id: string) => call<Job>("POST", `/api/projects/${id}/stitch`),
  reveal: (id: string) => call<{ ok: boolean }>("POST", `/api/projects/${id}/reveal`),
  saveCharacter: (project: string, id: string) => call<LibraryCharacter>("POST", "/api/library/characters", { project, id }),
  deleteCharacter: (id: string) => call<{ ok: boolean }>("DELETE", `/api/library/characters/${id}`),
  designInfluencer: (profile: Partial<Profile>, concept: string) =>
    call<Job>("POST", "/api/influencers/design", { profile, concept }),
  createInfluencer: (profile: Partial<Profile>, sources: string[] = [], consent = "") =>
    call<Influencer>("POST", "/api/influencers", { profile, sources, consent }),
  castFaces: (id: string, count: number, direction: string) => call<Job>("POST", `/api/influencers/${id}/casting`, { count, direction }),
  refineFace: (id: string, name: string, notes: string) => call<Job>("POST", `/api/influencers/${id}/casting/${name}/refine`, { notes }),
  lockFace: (id: string, name: string) => call<Influencer>("POST", `/api/influencers/${id}/casting/${name}/lock`),
  deleteCandidate: (id: string, name: string) => call<Influencer>("DELETE", `/api/influencers/${id}/casting/${name}`),
  addSources: (id: string, tokens: string[]) => call<Influencer>("POST", `/api/influencers/${id}/sources`, { tokens }),
  deleteSource: (id: string, name: string) => call<Influencer>("DELETE", `/api/influencers/${id}/sources/${name}`),
  uploadImage: async (file: Blob) => {
    const res = await fetch(`${API}/api/uploads`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
    if (!res.ok) throw new ApiError((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return ((await res.json()) as { token: string }).token;
  },
  describePhotos: (what: "person" | "product" | "inspiration", tokens: string[], product?: string) =>
    call<Job>("POST", "/api/describe", { what, tokens, product: product ?? null }),
  createProduct: (b: Partial<Omit<Product, "photos">> & { photos: string[] }) =>
    call<{ product: Product; job: Job }>("POST", "/api/products", b),
  updateProduct: (id: string, b: Partial<Product>) => call<Product>("PUT", `/api/products/${id}`, { ...b, photos: [] }),
  repaintPackshot: (id: string) => call<Job>("POST", `/api/products/${id}/packshot`),
  deleteProduct: (id: string) => call<{ ok: boolean }>("DELETE", `/api/products/${id}`),
  saveInfluencer: (id: string, profile: Partial<Profile>) => call<Influencer>("PUT", `/api/influencers/${id}`, { profile }),
  deleteInfluencer: (id: string) => call<{ ok: boolean }>("DELETE", `/api/influencers/${id}`),
  paintIdentity: (id: string, views?: IdentityView[], force = false) =>
    call<Job>("POST", `/api/influencers/${id}/identity`, { views: views ?? null, force }),
  setIdentityPrompt: (id: string, view: IdentityView, prompt: string | null) =>
    call<Influencer>("PUT", `/api/influencers/${id}/identity/prompt`, { view, prompt }),
  newVideo: (id: string, b: { format: string; topic: string; points: string; length_s: number; place: string; location: string; outfit: string; products: Setup["products"] }) =>
    call<Job>("POST", `/api/influencers/${id}/videos`, b),
  saveScript: (id: string, vid: string, b: { title?: string; caption?: string; segments?: Partial<Segment>[]; format?: string; setup?: Partial<Setup> }) =>
    call<Video>("PUT", `/api/influencers/${id}/videos/${vid}`, b),
  paintOpening: (id: string, vid: string) => call<Job>("POST", `/api/influencers/${id}/videos/${vid}/opening`),
  addPlace: (id: string, name: string, description: string) => call<Job>("POST", `/api/influencers/${id}/places`, { name, description }),
  repaintPlace: (id: string, pid: string) => call<Job>("POST", `/api/influencers/${id}/places/${pid}/paint`),
  deletePlace: (id: string, pid: string) => call<{ ok: boolean }>("DELETE", `/api/influencers/${id}/places/${pid}`),
  shootVideo: (id: string, vid: string) => call<Job>("POST", `/api/influencers/${id}/videos/${vid}/shoot`),
  deleteVideo: (id: string, vid: string) => call<{ ok: boolean }>("DELETE", `/api/influencers/${id}/videos/${vid}`),
  editVideo: (id: string, vid: string, params: EditParams) => call<Job>("PUT", `/api/influencers/${id}/videos/${vid}/edit`, { params }),
  editFilm: (id: string, params: EditParams) => call<Job>("PUT", `/api/projects/${id}/edit`, { params }),
  saveCaptions: (id: string, vid: string, b: Partial<Pick<CaptionState, "enabled" | "style" | "words">> & { reset?: boolean }) =>
    call<Video>("PUT", `/api/influencers/${id}/videos/${vid}/captions`, b),
  syncCaptions: (id: string, vid: string) => call<Job>("POST", `/api/influencers/${id}/videos/${vid}/captions/sync`),
  uploadFont: async (filename: string, bytes: ArrayBuffer) => {
    const res = await fetch(`${API}/api/captions/fonts/upload?filename=${encodeURIComponent(filename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: bytes,
    });
    if (!res.ok) throw new ApiError((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return (await res.json()) as CaptionCatalog & { added: { id: string; label: string } };
  },
  importGoogleFont: (family: string, weight: number) =>
    call<CaptionCatalog & { added: { id: string; label: string } }>("POST", "/api/captions/fonts/google", { family, weight }),
  deleteFont: (id: string) => call<CaptionCatalog>("DELETE", `/api/captions/fonts/${id}`),
  saveCaptionPreset: (name: string, style: CaptionStyle) => call<CaptionCatalog>("POST", "/api/captions/presets", { name, style }),
  deleteCaptionPreset: (id: string) => call<CaptionCatalog>("DELETE", `/api/captions/presets/${id}`),
  createBucket: (name?: string) => call<AppState & { bucket: { name: string; created: boolean } }>("POST", "/api/settings/bucket", { name: name ?? null }),
  deleteProject: (id: string) => call<{ ok: boolean; moved_to: string }>("DELETE", `/api/projects/${id}`),
};
