"use client";

// Phase 4b: "MCP access" page, the same for every role. Create a personal access token, connect an MCP
// client (Claude Desktop, Cursor, MCP Inspector) and see the calls it made. A token acts as you: what each
// tool returns is decided by your role on the server, call by call.

import { Copy, KeyRound, Plug, ScrollText, Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import {
  Alert,
  Button,
  Card,
  Chip,
  EmptyState,
  SkeletonCard,
} from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import type { Role } from "@/lib/session";

type Token = {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
};
type Tool = { name: string; description: string; read_only: boolean };
type Call = {
  id: number;
  at: string;
  user: string | null;
  via: string;
  name: string;
  arguments: Record<string, unknown>;
  status: string;
  error: string | null;
  latency_ms: number;
};
type Overview = { url: string; tokens: Token[]; tools: Tool[]; calls: Call[] };

const STATUS_TONE: Record<string, string> = {
  ok: "text-ok",
  refused: "text-warn",
  rate_limited: "text-warn",
  error: "text-bad",
};

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleString() : "never";
}

function CopyBox({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-xl bg-surface-2 p-3 pr-10 font-mono text-xs text-fg">
        {text}
      </pre>
      <button
        title="Copy"
        onClick={() => {
          navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="absolute right-2 top-2 rounded-lg p-1.5 text-muted hover:bg-surface hover:text-fg"
      >
        {copied ? (
          <span className="text-[10px]">copied</span>
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}

function Page({ role }: { role: Role }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [name, setName] = useState("Claude Desktop");
  const [created, setCreated] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await apiFetch<Overview>("/mcp-access"));
    } catch (e) {
      setError(
        e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)),
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    const t = await apiFetch<Token & { token: string }>("/mcp-access/tokens", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setCreated(t.token);
    load();
  }

  async function revoke(id: number) {
    await apiFetch(`/mcp-access/tokens/${id}`, { method: "DELETE" });
    load();
  }

  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!data) return <SkeletonCard lines={6} />;

  const token = created ?? "lms_YOUR_TOKEN";
  const stdio = JSON.stringify(
    {
      mcpServers: {
        lms: {
          command: "uv",
          args: [
            "--directory",
            "C:\\path\\to\\lms-genAI\\backend",
            "run",
            "python",
            "-m",
            "app.mcp_server",
          ],
          env: { LMS_TOKEN: token },
        },
      },
    },
    null,
    2,
  );

  return (
    <div className="space-y-6">
      <Card
        title="Personal access tokens"
        subtitle="A token lets an MCP client act as you, with your role's permissions. It is shown once: copy it now."
        icon={<KeyRound className="h-4 w-4" />}
      >
        <div className="flex flex-wrap gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="What is it for?"
            className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg"
          />
          <Button onClick={create} disabled={!name.trim()}>
            Create token
          </Button>
        </div>
        {created && (
          <div className="mt-3 space-y-2">
            <Alert
              tone="ok"
              title="Copy this token now. You won't see it again."
            />
            <CopyBox text={created} />
          </div>
        )}
        <div className="mt-4 divide-y divide-line">
          {data.tokens.length === 0 && (
            <p className="py-2 text-sm text-muted">No tokens yet.</p>
          )}
          {data.tokens.map((t) => (
            <div
              key={t.id}
              className={`flex flex-wrap items-center gap-2 py-2 text-sm ${t.revoked ? "opacity-50" : ""}`}
            >
              <span className="font-medium text-fg">{t.name}</span>
              <Chip mono>{t.prefix}…</Chip>
              <span className="text-xs text-faint">
                last used {when(t.last_used_at)}
              </span>
              {t.revoked ? (
                <span className="ml-auto text-xs text-faint">revoked</span>
              ) : (
                <button
                  onClick={() => revoke(t.id)}
                  className="ml-auto text-xs text-bad hover:underline"
                >
                  Revoke
                </button>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card
        title="Connect a client"
        subtitle="Over HTTP (MCP Inspector, Cursor, VS Code) or as a local program (Claude Desktop)."
        icon={<Plug className="h-4 w-4" />}
      >
        <div className="space-y-4 text-sm text-muted">
          <div className="space-y-1.5">
            <p>
              <span className="font-medium text-fg">Streamable HTTP.</span> URL
              and header:
            </p>
            <CopyBox text={`${data.url}\nAuthorization: Bearer ${token}`} />
            <p className="text-xs">
              Try it with MCP Inspector:{" "}
              <code className="font-mono">
                npx @modelcontextprotocol/inspector
              </code>
              , choose Streamable HTTP, paste the URL, and add the header under
              Authentication.
            </p>
          </div>
          <div className="space-y-1.5">
            <p>
              <span className="font-medium text-fg">
                stdio (Claude Desktop).
              </span>{" "}
              Add this to{" "}
              <code className="font-mono">claude_desktop_config.json</code> with
              your folder, then restart Claude Desktop:
            </p>
            <CopyBox text={stdio} />
          </div>
        </div>
      </Card>

      <Card
        title="Tools"
        subtitle={`What a client sees. Each call is checked against your role (${role}) when it runs.`}
        icon={<Wrench className="h-4 w-4" />}
      >
        <div className="divide-y divide-line">
          {data.tools.map((t) => (
            <div
              key={t.name}
              className="flex flex-wrap items-baseline gap-2 py-2 text-sm"
            >
              <span className="font-mono text-fg">{t.name}</span>
              <span className="text-xs text-faint">
                {t.read_only ? "read-only" : "writes"}
              </span>
              <span className="w-full text-xs text-muted">{t.description}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card
        title={
          role === "admin" ? "Audit log (everyone)" : "Your recent MCP calls"
        }
        subtitle="Every tool call, resource read and refused request, with who made it and how."
        icon={<ScrollText className="h-4 w-4" />}
      >
        {data.calls.length === 0 ? (
          <EmptyState
            title="No calls yet"
            hint="Connect a client with a token, or ask the chat “What should I study today?”."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-faint">
                <tr>
                  <th className="py-1 pr-3 font-medium">When</th>
                  {role === "admin" && (
                    <th className="py-1 pr-3 font-medium">User</th>
                  )}
                  <th className="py-1 pr-3 font-medium">Via</th>
                  <th className="py-1 pr-3 font-medium">Tool / resource</th>
                  <th className="py-1 pr-3 font-medium">Result</th>
                  <th className="py-1 font-medium">ms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line text-muted">
                {data.calls.map((c) => (
                  <tr key={c.id}>
                    <td className="whitespace-nowrap py-1.5 pr-3">
                      {when(c.at)}
                    </td>
                    {role === "admin" && (
                      <td className="py-1.5 pr-3">
                        {c.user ?? "unknown token"}
                      </td>
                    )}
                    <td className="py-1.5 pr-3">{c.via}</td>
                    <td
                      className="py-1.5 pr-3 font-mono text-fg"
                      title={JSON.stringify(c.arguments)}
                    >
                      {c.name}
                    </td>
                    <td
                      className={`py-1.5 pr-3 ${STATUS_TONE[c.status] ?? ""}`}
                      title={c.error ?? ""}
                    >
                      {c.status}
                      {c.error && (
                        <span className="text-faint">
                          {" "}
                          · {c.error.slice(0, 60)}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 font-mono">{c.latency_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export function McpAccess({ role }: { role: Role }) {
  return (
    <PortalShell role={role} title="MCP access" showRoadmap={false}>
      {() => <Page role={role} />}
    </PortalShell>
  );
}
