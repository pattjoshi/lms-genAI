"use client";

// Phase 6: ask about the data in plain English (the SQL agent). Same page in every portal.

import { AskData } from "@/components/AskData";
import { PortalShell } from "@/components/PortalShell";

export default function Page() {
  return (
    <PortalShell role="support" title="Ask the data" showRoadmap={false}>
      {() => <AskData role="support" />}
    </PortalShell>
  );
}
