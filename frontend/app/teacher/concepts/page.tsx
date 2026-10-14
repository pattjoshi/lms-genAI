"use client";

// Concept graph review: the AI extracted draft concepts and prerequisites from the course files.
// The teacher approves, edits, merges or rejects them. Only approved concepts reach students.

import { Check, GitMerge, Network, Pencil, Plus, Route, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState, SkeletonCard } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { apiFetch, ApiError } from "@/lib/api";

type Option = { id: number; code: string; title: string };
type Explanation = { document_id: number; file_name: string; pages: number[]; section: string | null; evidence: string };
type Concept = {
  uid: string;
  name: string;
  definition: string | null;
  status: "draft" | "approved" | "rejected";
  aliases: string[];
  possible_duplicate_of: string | null;
  mentioned_only: boolean;
  explanations: Explanation[];
};
type Edge = { source: string; target: string; status: "draft" | "approved" | "rejected" };
type Graph = { course: Option; nodes: Concept[]; edges: Edge[] };
type PathStep = { uid: string; name: string; status: string };

const FILTERS = ["all", "draft", "approved", "rejected", "duplicates"] as const;
type Filter = (typeof FILTERS)[number];

const STATUS_STYLE: Record<string, string> = {
  draft: "bg-surface-2 text-muted",
  approved: "bg-ok-soft text-ok",
  rejected: "bg-bad-soft text-bad",
};

const enc = encodeURIComponent;
const input =
  "w-full rounded-lg border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-brand focus:outline-none";

function ConceptCard({
  c,
  graph,
  act,
}: {
  c: Concept;
  graph: Graph;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  const [definition, setDefinition] = useState(c.definition ?? "");
  const [adding, setAdding] = useState("");
  const [mergeInto, setMergeInto] = useState("");
  const [path, setPath] = useState<PathStep[] | null>(null);

  const byUid = useMemo(() => Object.fromEntries(graph.nodes.map((n) => [n.uid, n])), [graph]);
  const prereqs = graph.edges.filter((e) => e.source === c.uid);
  const neededBy = graph.edges.filter((e) => e.target === c.uid && e.status !== "rejected").length;
  const others = graph.nodes.filter((n) => n.uid !== c.uid && n.status !== "rejected");
  const duplicate = c.possible_duplicate_of ? byUid[c.possible_duplicate_of] : null;

  const patch = (body: object) =>
    act(() => apiFetch(`/concepts/${enc(c.uid)}`, { method: "PATCH", body: JSON.stringify(body) }));
  const edge = (prerequisite: string, status: "approved" | "rejected") =>
    act(() =>
      apiFetch(`/concepts/${enc(c.uid)}/prerequisites`, {
        method: "PATCH",
        body: JSON.stringify({ prerequisite, status }),
      }),
    );
  const merge = (into: string) => {
    if (!confirm(`Merge "${c.name}" into "${byUid[into]?.name}"? Its links and names move there.`)) return;
    return act(() => apiFetch(`/concepts/${enc(c.uid)}/merge`, { method: "POST", body: JSON.stringify({ into }) }));
  };

  async function previewPath() {
    if (path) return setPath(null);
    try {
      const res = await apiFetch<{ steps: PathStep[] }>(`/learning-path?concept=${enc(c.uid)}&preview=true`);
      setPath(res.steps);
    } catch {
      setPath([]);
    }
  }

  return (
    <div className={`rounded-xl border p-3 ${c.status === "rejected" ? "border-line opacity-60" : "border-line"}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        {editing ? (
          <input value={name} onChange={(e) => setName(e.target.value)} className={`${input} max-w-xs`} />
        ) : (
          <span className="font-medium text-fg">{c.name}</span>
        )}
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[c.status]}`}>{c.status}</span>
        {c.mentioned_only && (
          <span title="Another concept needs it, but no file of this course explains it">
            <Chip>mentioned only</Chip>
          </span>
        )}
        {c.aliases.length > 0 && <span className="text-xs text-faint">also: {c.aliases.join(", ")}</span>}
        <span className="ml-auto flex gap-1">
          {c.status !== "approved" && (
            <button
              title="Approve"
              onClick={() => patch({ status: "approved" })}
              className="rounded-lg p-1.5 text-ok hover:bg-ok-soft"
            >
              <Check className="h-4 w-4" />
            </button>
          )}
          {c.status !== "rejected" && (
            <button
              title="Reject"
              onClick={() => patch({ status: "rejected" })}
              className="rounded-lg p-1.5 text-bad hover:bg-bad-soft"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          {c.status !== "draft" && (
            <button
              onClick={() => patch({ status: "draft" })}
              className="rounded-lg px-1.5 text-xs text-muted hover:bg-surface-2"
            >
              undo
            </button>
          )}
          <button
            title="Edit name and definition"
            onClick={() => setEditing(!editing)}
            className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            title="Preview the learning path"
            onClick={previewPath}
            className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
          >
            <Route className="h-4 w-4" />
          </button>
        </span>
      </div>

      {editing ? (
        <div className="mt-2 space-y-2">
          <textarea value={definition} onChange={(e) => setDefinition(e.target.value)} rows={2} className={input} />
          <div className="flex gap-2">
            <Button
              onClick={async () => {
                await patch({ name, definition });
                setEditing(false);
              }}
            >
              Save
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        c.definition && <p className="mt-1 text-sm text-muted">{c.definition}</p>
      )}

      {duplicate && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft px-2 py-1 text-xs text-warn">
          Possibly the same as <b>{duplicate.name}</b>
          <button onClick={() => merge(duplicate.uid)} className="font-medium underline">
            merge into it
          </button>
        </div>
      )}

      {c.explanations.map((e) => (
        <p key={e.document_id} className="mt-1 border-l-2 border-line pl-2 text-xs text-faint">
          <span className="not-italic text-muted">
            {e.file_name}
            {e.pages.length > 0 ? ` · page ${e.pages.join(", ")}` : e.section ? ` · ${e.section}` : ""}:
          </span>{" "}
          <i>“{e.evidence}”</i>
        </p>
      ))}

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
        Learn first:
        {prereqs.length === 0 && <span className="text-faint">nothing</span>}
        {prereqs.map((e) => (
          <span
            key={e.target}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${
              e.status === "rejected" ? "border-line text-faint line-through" : "border-line text-fg"
            }`}
            title={e.status === "approved" ? "Added or confirmed by a teacher" : e.status}
          >
            {byUid[e.target]?.name ?? e.target}
            {e.status === "rejected" ? (
              <button title="Restore" onClick={() => edge(e.target, "approved")} className="no-underline">
                <Plus className="h-3 w-3" />
              </button>
            ) : (
              <button title="Remove this prerequisite" onClick={() => edge(e.target, "rejected")}>
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        ))}
        <select
          value={adding}
          onChange={async (e) => {
            setAdding("");
            if (e.target.value) await edge(e.target.value, "approved");
          }}
          className="w-28 rounded-full border border-dashed border-line bg-surface px-2 py-0.5 text-xs text-muted"
        >
          <option value="">+ add</option>
          {others.map((n) => (
            <option key={n.uid} value={n.uid}>
              {n.name}
            </option>
          ))}
        </select>
        {neededBy > 0 && <span className="ml-auto text-faint">needed by {neededBy}</span>}
      </div>

      <div className="mt-2 flex items-center gap-1.5 text-xs text-muted">
        <GitMerge className="h-3.5 w-3.5" />
        <select
          value={mergeInto}
          onChange={async (e) => {
            setMergeInto("");
            if (e.target.value) await merge(e.target.value);
          }}
          className="w-44 rounded-lg border border-line bg-surface px-2 py-0.5 text-xs text-muted"
        >
          <option value="">Same concept as…</option>
          {others.map((n) => (
            <option key={n.uid} value={n.uid}>
              {n.name}
            </option>
          ))}
        </select>
      </div>

      {path && (
        <div className="mt-2 rounded-lg bg-surface-2/60 p-2 text-xs text-muted">
          {path.length === 0 ? (
            "No path: approve this concept first, or it has no visible prerequisites."
          ) : (
            <>
              Path a student would get{path.some((s) => s.status === "draft") && " (drafts included in preview)"}:{" "}
              {path.map((s, i) => (
                <span key={s.uid}>
                  {i > 0 && " → "}
                  <span className={s.status === "draft" ? "italic" : "text-fg"}>{s.name}</span>
                </span>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ConceptReview() {
  const options = useApi<Option[]>("/documents/options");
  const [courseId, setCourseId] = useState<number | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [filter, setFilter] = useState<Filter>("draft");
  const [q, setQ] = useState("");

  useEffect(() => {
    if (courseId === null && options.data?.length) setCourseId(options.data[0].id);
  }, [options.data, courseId]);

  const load = useCallback(async () => {
    if (courseId === null) return;
    try {
      setGraph(await apiFetch<Graph>(`/concepts/courses/${courseId}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    }
  }, [courseId]);

  useEffect(() => {
    setGraph(null);
    load();
  }, [load]);

  const act = useCallback(
    async (fn: () => Promise<unknown>) => {
      try {
        await fn();
        await load();
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
      }
    },
    [load],
  );

  const counts = useMemo(() => {
    const c = { all: 0, draft: 0, approved: 0, rejected: 0, duplicates: 0 };
    for (const n of graph?.nodes ?? []) {
      c.all++;
      c[n.status]++;
      if (n.possible_duplicate_of) c.duplicates++;
    }
    return c;
  }, [graph]);

  const shown = (graph?.nodes ?? []).filter((n) => {
    if (filter === "duplicates" ? !n.possible_duplicate_of : filter !== "all" && n.status !== filter) return false;
    const text = q.trim().toLowerCase();
    return !text || [n.name, ...n.aliases, n.definition ?? ""].some((s) => s.toLowerCase().includes(text));
  });

  return (
    <>
      <Card
        title="Review the concept graph"
        subtitle="The AI extracted these from your files. Approve what's right, fix or reject the rest. Only approved concepts appear in students' learning paths."
        icon={<Network className="h-4 w-4" />}
        action={
          counts.draft > 0 && (
            <Button
              variant="ghost"
              onClick={() => {
                if (confirm(`Approve all ${counts.draft} drafts in this course?`))
                  act(() => apiFetch(`/concepts/courses/${courseId}/approve-drafts`, { method: "POST" }));
              }}
            >
              <Check className="h-4 w-4" /> Approve all drafts
            </Button>
          )
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={courseId ?? ""}
            onChange={(e) => setCourseId(Number(e.target.value))}
            className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg"
          >
            {options.data?.map((o) => (
              <option key={o.id} value={o.id}>
                {o.code} · {o.title}
              </option>
            ))}
          </select>
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  filter === f ? "bg-brand text-brand-fg" : "bg-surface-2 text-muted hover:text-fg"
                }`}
              >
                {f === "duplicates" ? "possible duplicates" : f} ({counts[f]})
              </button>
            ))}
          </div>
          <label className="relative ml-auto">
            <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-faint" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className={`${input} pl-8`} />
          </label>
        </div>
        {(error || options.error) && (
          <div className="mt-3">
            <Alert title={(error ?? options.error)!.message} detail={(error ?? options.error)!.detail} />
          </div>
        )}
      </Card>

      {!graph && !error && <SkeletonCard lines={5} />}
      {graph && graph.nodes.length === 0 && (
        <EmptyState
          title="No concepts yet"
          hint="Upload files in Course files; concepts are extracted after indexing. Older files: uv run python -m app.graph.backfill"
        />
      )}
      {graph && graph.nodes.length > 0 && (
        <div className="space-y-3">
          {shown.length === 0 && <EmptyState title="Nothing in this filter" />}
          {shown.map((c) => (
            <ConceptCard key={`${c.uid}-${c.name}-${c.definition}`} c={c} graph={graph} act={act} />
          ))}
        </div>
      )}
    </>
  );
}

export default function ConceptGraphPage() {
  return (
    <PortalShell role="teacher" title="Concept graph" showRoadmap={false}>
      {() => <ConceptReview />}
    </PortalShell>
  );
}
