// Types + calls for server.py. Keep in sync with its *_view() functions.

export const API = process.env.NEXT_PUBLIC_API ?? "";

export const url = (path: string | null | undefined) => (path ? `${API}${path}` : undefined);

export type Resolution = "360p" | "720p" | "1080p" | "4k";
export type Orientation = "9:16" | "16:9";
export type Backend = "vertex" | "gemini";
type Models = { planner_model: string; image_model: string; video_model: string };

export interface Settings extends Models {
  backend: Backend;
  gcp_project: string;
  gcp_location: string;
  resolution: Resolution;
  image_size: "1K" | "2K" | "4K";
  orientation: Orientation;
  default_models: Record<Backend, Models>;
  prices: { image: number; video_per_s: Record<Resolution, number> };
}

export interface AppState {
  settings: Settings;
  ffmpeg: boolean;
  fake: boolean;
  projects_dir: string;
}

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
}

export interface PlanScene {
  id: string;
  duration_s: number;
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
  style: { look: string; color_grade: string; lens: string; avoid: string };
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
  costs: Costs;
  busy: string[];
}

export interface Job {
  id: string;
  kind: "plan" | "film" | "assets" | "take" | "edit" | "produce" | "stitch";
  label: string;
  project: string | null;
  claims: string[];
  status: "running" | "done" | "failed";
  logs: string[];
  error: string | null;
  result: Record<string, unknown> | null;
  started: number;
  finished: number | null;
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
  newFilm: (b: { story: string; style: string; scenes: number; orientation: Orientation; auto: boolean }) =>
    call<Job>("POST", "/api/projects", b),
  savePlan: (id: string, plan: Plan) => call<Project>("PUT", `/api/projects/${id}/plan`, { plan }),
  setPrompt: (id: string, item: string, prompt: string | null) =>
    call<Project>("PUT", `/api/projects/${id}/prompt`, { id: item, prompt }),
  select: (id: string, scene: string, take: string) =>
    call<Project>("PUT", `/api/projects/${id}/scenes/${scene}/selected`, { take }),
  makeAssets: (id: string, ids?: string[], force = false) =>
    call<Job>("POST", `/api/projects/${id}/assets`, { ids: ids ?? null, force }),
  shoot: (id: string, scene: string) => call<Job>("POST", `/api/projects/${id}/scenes/${scene}/takes`),
  fix: (id: string, scene: string, take: string, instruction: string) =>
    call<Job>("POST", `/api/projects/${id}/scenes/${scene}/takes/${take}/edit`, { instruction }),
  produce: (id: string) => call<Job>("POST", `/api/projects/${id}/produce`),
  stitch: (id: string) => call<Job>("POST", `/api/projects/${id}/stitch`),
  reveal: (id: string) => call<{ ok: boolean }>("POST", `/api/projects/${id}/reveal`),
};
