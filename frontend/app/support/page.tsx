"use client";

import { Inbox } from "lucide-react";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Alert, Card, EmptyState, SkeletonCard } from "@/components/ui";
import { useApi } from "@/components/useApi";

function SupportHome() {
  const { data, error } = useApi<{ tickets: unknown[]; note: string }>("/portal/support/summary");
  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!data) return <SkeletonCard />;
  return (
    <Card
      title="Ticket queue"
      subtitle="Support sees a student's data only through a ticket"
      icon={<Inbox className="h-4 w-4" />}
    >
      <EmptyState title="No tickets yet" hint={data.note} />
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
