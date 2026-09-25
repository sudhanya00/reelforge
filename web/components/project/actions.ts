"use client";

import * as React from "react";
import { useSWRConfig } from "swr";
import { toast } from "sonner";
import { useConfirm, useConfirmSpend } from "@/components/confirm";
import { imageUsd, useAppState, videoUsd } from "@/lib/hooks";
import { api, type Plan, type Project } from "@/lib/api";
import { plural } from "@/lib/utils";

/** Every action on a project: confirms bigger spends, reports errors, refreshes data. */
export function useProjectActions(p: Project | undefined) {
  const { data: state } = useAppState();
  const s = state?.settings;
  const confirm = useConfirmSpend();
  const { mutate } = useSWRConfig();
  const id = p?.id ?? "";
  const key = `/api/projects/${id}`;

  return React.useMemo(() => {
    const refresh = (data?: Project) => {
      mutate("/api/jobs");
      mutate("/api/projects");
      return data ? mutate(key, data, { revalidate: false }) : mutate(key);
    };
    const run = async (what: string, fn: () => Promise<unknown>) => {
      try {
        const r = await fn();
        refresh(r && typeof r === "object" && "plan" in r ? (r as Project) : undefined);
        return true;
      } catch (e) {
        toast.error(what, { description: (e as Error).message });
        return false;
      }
    };
    const missingRefs = p?.assets.filter((a) => !a.image && a.status !== "generating") ?? [];
    const missingScenes = p?.scenes.filter((sc) => !sc.takes.length && sc.status !== "generating") ?? [];
    const remainingUsd =
      imageUsd(s, missingRefs.length) + videoUsd(s, missingScenes.reduce((t, sc) => t + sc.duration_s, 0));

    return {
      settings: s,
      missingRefs,
      missingScenes,
      remainingUsd,

      paintMissing: async () => {
        const cost = imageUsd(s, missingRefs.length);
        if (!(await confirm({ title: `Paint ${plural(missingRefs.length, "reference")}?`, usd: cost, action: "Paint" }))) return;
        return run("Couldn't start painting", () => api.makeAssets(id));
      },
      paint: (assetId: string) => run(`Couldn't repaint ${assetId}`, () => api.makeAssets(id, [assetId], true)),
      shoot: async (sceneId: string) => {
        const sc = p?.scenes.find((x) => x.id === sceneId);
        const cost = videoUsd(s, sc?.duration_s ?? 8);
        if (!(await confirm({ title: `Shoot ${sceneId}?`, usd: cost, action: "Shoot" }))) return;
        return run(`Couldn't shoot ${sceneId}`, () => api.shoot(id, sceneId));
      },
      fix: (sceneId: string, take: string, text: string) => run(`Couldn't fix ${sceneId}`, () => api.fix(id, sceneId, take, text)),
      produce: async () => {
        const detail = `${plural(missingRefs.length, "reference")} and ${plural(missingScenes.length, "scene")} at ${s?.resolution}, then the final cut.`;
        if (!(await confirm({ title: "Make everything missing?", usd: remainingUsd, detail, action: "Make it" }))) return;
        return run("Couldn't start", () => api.produce(id));
      },
      stitch: () => run("Couldn't stitch", () => api.stitch(id)),
      select: (sceneId: string, take: string) => run("Couldn't select take", () => api.select(id, sceneId, take)),
      setPrompt: (item: string, prompt: string | null) => run("Couldn't save the prompt", () => api.setPrompt(id, item, prompt)),
      savePlan: (plan: Plan) => run("Couldn't save the plan", () => api.savePlan(id, plan)),
      reveal: () => run("Couldn't open the folder", () => api.reveal(id)),
    };
  }, [p, s, id, key, confirm, mutate]);
}

/** Delete a film (moves it to the Recycle Bin) after confirming. */
export function useDeleteFilm() {
  const confirm = useConfirm();
  const { mutate } = useSWRConfig();
  return React.useCallback(
    async (id: string, title: string, after?: () => void) => {
      const ok = await confirm({
        title: `Delete “${title}”?`,
        detail: "The film, its references and every take move to the Recycle Bin, so you can still restore them from there.",
        action: "Move to Recycle Bin",
        destructive: true,
      });
      if (!ok) return;
      try {
        await api.deleteProject(id);
        toast.success(`Moved “${title}” to the Recycle Bin`);
        after?.();
        mutate("/api/projects");
      } catch (e) {
        toast.error("Couldn't delete the film", { description: (e as Error).message });
      }
    },
    [confirm, mutate],
  );
}
