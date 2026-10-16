"use client";

// Phase 6: ask about the data in plain English (the SQL agent). Same page in every portal.

import { AskData } from "@/components/AskData";
import { PortalShell } from "@/components/PortalShell";

export default function Page() {
  return (
    <PortalShell role="admin" title="Ask the data" showRoadmap={false}>
      {() => <AskData role="admin" />}
    </PortalShell>
  );
}
