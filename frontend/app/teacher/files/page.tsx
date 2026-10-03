"use client";

// Course files: upload, watch each file move through the pipeline, preview the chunks
// the AI will search, and re-process or delete files.

import { Eye, FileText, Layers, RotateCw, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState, SkeletonCard } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { apiFetch, ApiError } from "@/lib/api";

type Option = { id: number; code: string; title: string; modules: { id: number; title: string }[] };

type Doc = {
  id: number;
  file_name: string;
  file_type: string;
  size_bytes: number;
  status: string;
  error: string | null;
  num_pages: number | null;
  num_chunks: number;
  embed_tokens: number;
  embed_cost_usd: number;
  course_code: string | null;
  module_title: string | null;
};

type ChunkRow = {
  index: number;
  text: string;
  chars: number;
  page: number | null;
  section: string | null;
  topic: string | null;
  difficulty: string | null;
  topic_score: number | null;
};

const STEPS = ["uploaded", "parsing", "chunking", "embedding", "tagging", "indexing", "ready"];
const PROCESSING = new Set(STEPS.slice(0, -1));
const ACCEPT = ".pdf,.docx,.html,.htm,.txt";

function StatusBadge({ doc }: { doc: Doc }) {
  if (doc.status === "ready")
    return <span className="rounded-full bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">ready</span>;
  if (doc.status === "failed")
    return <span className="rounded-full bg-bad-soft px-2 py-0.5 text-xs font-medium text-bad">failed</span>;
  const step = STEPS.indexOf(doc.status);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand-ink">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
      {doc.status} {step}/{STEPS.length - 1}
    </span>
  );
}

function UploadForm({ options, onUploaded }: { options: Option[]; onUploaded: () => void }) {
  const [courseId, setCourseId] = useState(options[0]?.id ?? 0);
  const course = options.find((o) => o.id === courseId);
  const [moduleId, setModuleId] = useState(course?.modules[0]?.id ?? 0);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [inputKey, setInputKey] = useState(0);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("course_id", String(courseId));
    form.append("module_id", String(moduleId));
    try {
      await apiFetch("/documents", { method: "POST", body: form });
      setFile(null);
      setInputKey((k) => k + 1); // reset the file input
      onUploaded();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    } finally {
      setBusy(false);
    }
  }

  const select =
    "w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg focus:border-brand focus:outline-none";
  return (
    <Card
      title="Upload a course file"
      subtitle="PDF, DOCX, HTML or TXT · max 10 MB · parsed, chunked, embedded and tagged automatically"
      icon={<Upload className="h-4 w-4" />}
    >
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_1.4fr_auto] md:items-end">
        <label className="text-xs font-medium text-muted">
          Course
          <select
            value={courseId}
            onChange={(e) => {
              const id = Number(e.target.value);
              setCourseId(id);
              setModuleId(options.find((o) => o.id === id)?.modules[0]?.id ?? 0);
            }}
            className={`mt-1 ${select}`}
          >
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.code} · {o.title}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-muted">
          Module
          <select value={moduleId} onChange={(e) => setModuleId(Number(e.target.value))} className={`mt-1 ${select}`}>
            {course?.modules.map((m) => (
              <option key={m.id} value={m.id}>
                {m.title}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-muted">
          File
          <input
            key={inputKey}
            type="file"
            accept={ACCEPT}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full rounded-xl border border-dashed border-line bg-surface-2/50 px-3 py-1.5 text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-brand-soft file:px-3 file:py-1 file:text-sm file:font-medium file:text-brand-ink"
          />
        </label>
        <Button onClick={upload} disabled={!file || busy}>
          <Upload className="h-4 w-4" />
          {busy ? "Uploading…" : "Upload"}
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <Alert title={error.message} detail={error.detail} />
        </div>
      )}
    </Card>
  );
}

function ChunkPreview({ docId, onClose }: { docId: number; onClose: () => void }) {
  const { data, error } = useApi<{ document: Doc; chunks: ChunkRow[] }>(`/documents/${docId}/chunks`);
  return (
    <Card
      title={data ? `What the AI sees: ${data.document.file_name}` : "Chunks"}
      subtitle="Each chunk is embedded and stored in Qdrant with these tags. Low-confidence tags are worth a look."
      icon={<Layers className="h-4 w-4" />}
      action={
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      }
    >
      {error && <Alert title={error.message} />}
      {!data && !error && <SkeletonCard />}
      {data && (
        <div className="space-y-3">
          {data.chunks.length === 0 && <EmptyState title="No chunks yet" hint="The file may still be processing." />}
          {data.chunks.map((c) => {
            const uncertain = c.topic_score !== null && c.topic_score < 1 && c.topic_score < 0.3;
            return (
              <div key={c.index} className="rounded-xl border border-line p-3">
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  <Chip mono>#{c.index}</Chip>
                  {c.page && <Chip>page {c.page}</Chip>}
                  {c.section && !c.page && <Chip>{c.section}</Chip>}
                  {c.topic && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        uncertain ? "bg-warn-soft text-warn" : "bg-brand-soft text-brand-ink"
                      }`}
                      title={
                        c.topic_score === 1 ? "Matched by heading" : `Embedding similarity ${c.topic_score?.toFixed(2)}`
                      }
                    >
                      {c.topic}
                      {uncertain && " · low confidence"}
                    </span>
                  )}
                  {c.difficulty && <Chip>{c.difficulty}</Chip>}
                  <span className="ml-auto font-mono text-xs text-faint">{c.chars} chars</span>
                </div>
                <p className="whitespace-pre-wrap text-sm text-muted">{c.text}</p>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function CourseFiles() {
  const options = useApi<Option[]>("/documents/options");
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [preview, setPreview] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await apiFetch<Doc[]>("/documents"));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    }
  }, []);

  const processing = useMemo(() => docs?.some((d) => PROCESSING.has(d.status)) ?? false, [docs]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll every 2s only while something is processing.
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [processing, load]);

  async function act(doc: Doc, action: "reprocess" | "delete") {
    if (action === "delete" && !confirm(`Delete ${doc.file_name}? Its chunks are removed from the AI's knowledge.`))
      return;
    try {
      if (action === "delete") await apiFetch(`/documents/${doc.id}`, { method: "DELETE" });
      else await apiFetch(`/documents/${doc.id}/reprocess`, { method: "POST" });
      if (preview === doc.id) setPreview(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    }
  }

  const totals = (docs ?? []).reduce(
    (t, d) => ({ chunks: t.chunks + d.num_chunks, tokens: t.tokens + d.embed_tokens, cost: t.cost + d.embed_cost_usd }),
    { chunks: 0, tokens: 0, cost: 0 },
  );

  return (
    <>
      {options.error && <Alert title={options.error.message} />}
      {options.data && <UploadForm options={options.data} onUploaded={load} />}

      <Card
        title="Your course files"
        subtitle={`${docs?.length ?? 0} files · ${totals.chunks} chunks · ${totals.tokens.toLocaleString()} embedding tokens · $${totals.cost.toFixed(5)}`}
        icon={<FileText className="h-4 w-4" />}
      >
        {error && <Alert title={error.message} />}
        {!docs && !error && <SkeletonCard lines={4} />}
        {docs?.length === 0 && (
          <EmptyState title="No files yet" hint="Upload one above, or run: uv run python -m app.ingest.load_samples" />
        )}
        {docs && docs.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-2/70 text-xs text-muted">
                <tr>
                  {["File", "Module", "Status", "Chunks", "Tokens", "Cost", ""].map((h) => (
                    <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {docs.map((d) => (
                  <tr key={d.id} className="align-top text-fg">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] uppercase text-muted">
                          {d.file_type}
                        </span>
                        <span className="font-medium">{d.file_name}</span>
                      </div>
                      {d.error && <p className="mt-1 max-w-md text-xs text-bad">{d.error}</p>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-muted">
                      {d.course_code} · {d.module_title}
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusBadge doc={d} />
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs">{d.num_chunks}</td>
                    <td className="px-3 py-2.5 font-mono text-xs">{d.embed_tokens}</td>
                    <td className="px-3 py-2.5 font-mono text-xs">${d.embed_cost_usd.toFixed(6)}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex justify-end gap-1">
                        <button
                          title="View chunks"
                          onClick={() => setPreview(d.id)}
                          disabled={d.status !== "ready"}
                          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30"
                        >
                          <Eye className="h-4 w-4" />
                        </button>
                        <button
                          title="Re-process"
                          onClick={() => act(d, "reprocess")}
                          disabled={PROCESSING.has(d.status)}
                          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30"
                        >
                          <RotateCw className="h-4 w-4" />
                        </button>
                        <button
                          title="Delete"
                          onClick={() => act(d, "delete")}
                          disabled={PROCESSING.has(d.status)}
                          className="rounded-lg p-1.5 text-muted hover:bg-bad-soft hover:text-bad disabled:opacity-30"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {preview !== null && <ChunkPreview key={preview} docId={preview} onClose={() => setPreview(null)} />}
    </>
  );
}

export default function TeacherFilesPage() {
  return (
    <PortalShell role="teacher" title="Course files" showRoadmap={false}>
      {() => <CourseFiles />}
    </PortalShell>
  );
}
