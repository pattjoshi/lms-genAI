"use client";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Card, ErrorBox, Loading } from "@/components/ui";
import { useApi } from "@/components/useApi";

function SupportHome() {
  const { data, error } = useApi<{ tickets: unknown[]; note: string }>("/portal/support/summary");
  if (error) return <ErrorBox message={error.message} detail={error.detail} />;
  if (!data) return <Loading />;
  return (
    <Card title="Ticket queue" subtitle="Support sees a student's data only through a ticket">
      <p className="text-sm text-slate-600">{data.note}</p>
    </Card>
  );
}

export default function SupportPage() {
  return (
    <PortalShell role="support">
      {() => (
        <>
          <SupportHome />
          <PermissionTestCard />
          <AiHelloCard />
        </>
      )}
    </PortalShell>
  );
}
