"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { Plus, Sparkles, UserRound, Video as VideoIcon } from "lucide-react";
import { Badge, LiveBars, Meter } from "@/components/ui/primitives";
import { useRoute } from "@/components/shell";
import { useInfluencers } from "@/lib/hooks";
import { url, type InfluencerSummary } from "@/lib/api";
import { usd } from "@/lib/utils";
import { Designer } from "./Designer";
import { ProductsSection } from "./Products";

export function Influencers() {
  const { data } = useInfluencers();
  const list = data?.influencers ?? [];
  const [designing, setDesigning] = React.useState(false);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-6 pt-16 pb-24">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="mx-auto max-w-2xl text-center">
        <h1 className="text-4xl font-semibold tracking-tight text-balance">Your creators</h1>
        <p className="mt-3 text-balance text-muted-foreground">
          Design a creator once, from scratch or from photos: their look, personality and voice. Then make videos in any format and place, wearing or holding your products, while they always look and sound like themselves.
        </p>
      </motion.div>

      <div className="mt-12 grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-5">
        <motion.button
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={() => setDesigning(true)}
          className="group flex aspect-[3/4] flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-accent/40 hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <span className="flex size-12 items-center justify-center rounded-full bg-foreground text-background transition-transform group-hover:scale-105">
            <Plus className="size-5" />
          </span>
          <span className="text-sm font-medium">Design an influencer</span>
          <span className="flex items-center gap-1 text-xs">
            <Sparkles className="size-3" />
            AI fills in whatever you skip
          </span>
        </motion.button>
        <AnimatePresence mode="popLayout">
          {list.map((i, n) => (
            <InfluencerCard key={i.id} i={i} index={n} />
          ))}
        </AnimatePresence>
      </div>

      {data && data.design_usd > 0 && (
        <p className="mt-8 text-center text-xs text-muted-foreground tabular">{usd(data.design_usd)} spent on AI design suggestions</p>
      )}

      <ProductsSection />

      <Designer open={designing} onOpenChange={setDesigning} />
    </div>
  );
}

function InfluencerCard({ i, index }: { i: InfluencerSummary; index: number }) {
  const { goInf } = useRoute();
  const p = i.profile;
  const ready = i.identity_done === i.identity_total;
  return (
    <motion.button
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.35, delay: Math.min(index, 8) * 0.03 }}
      onClick={() => goInf(i.id, ready ? "videos" : "identity")}
      className="group overflow-hidden rounded-xl border bg-card text-left transition-all hover:-translate-y-0.5 hover:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.25)] focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <div className="relative aspect-[3/4] overflow-hidden bg-muted">
        {i.face ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url(i.face)} alt="" className="size-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" />
        ) : (
          <div className="flex size-full items-center justify-center bg-gradient-to-br from-muted to-muted/40">
            <UserRound className="size-10 text-muted-foreground/40" />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-3 pt-12 text-white">
          <h3 className="truncate font-medium tracking-tight">{p.name}</h3>
          <p className="truncate text-xs text-white/75">{p.handle || p.niche}</p>
        </div>
        {i.busy && (
          <Badge tone="live" className="absolute top-3 left-3 bg-background/85 backdrop-blur">
            <LiveBars className="h-2.5" bars={4} />
            Generating
          </Badge>
        )}
      </div>
      <div className="space-y-3 p-3.5">
        {!ready && <Meter label="Identity pack" value={i.identity_done} total={i.identity_total} />}
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="truncate">{p.niche}</span>
          <span className="ml-auto flex shrink-0 items-center gap-1 tabular">
            <VideoIcon className="size-3.5" />
            {i.videos_count}
          </span>
          <span className="shrink-0 tabular">{usd(i.cost_usd)}</span>
        </div>
      </div>
    </motion.button>
  );
}
