"use client";

import { Suspense } from "react";
import { Nav, useRoute } from "@/components/shell";
import { Library } from "@/components/library/Library";
import { Workspace } from "@/components/project/Workspace";
import { Influencers } from "@/components/influencers/Influencers";
import { InfluencerPage } from "@/components/influencers/InfluencerPage";

function Routed() {
  const { project, influencer, mode } = useRoute();
  return (
    <>
      <Nav />
      <main className="flex grow flex-col">
        {project ? (
          <Workspace key={project} id={project} />
        ) : influencer ? (
          <InfluencerPage key={influencer} id={influencer} />
        ) : mode === "influencers" ? (
          <Influencers />
        ) : (
          <Library />
        )}
      </main>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Routed />
    </Suspense>
  );
}
