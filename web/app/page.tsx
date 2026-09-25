"use client";

import { Suspense } from "react";
import { Nav, useRoute } from "@/components/shell";
import { Library } from "@/components/library/Library";
import { Workspace } from "@/components/project/Workspace";

function Routed() {
  const { project } = useRoute();
  return (
    <>
      <Nav />
      <main className="flex grow flex-col">{project ? <Workspace key={project} id={project} /> : <Library />}</main>
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
