"use client";

// Admins give roles. Sign-up only ever creates students; teachers, support and admins are made here
// (the very first admin with `python -m app.accounts create-admin`). The backend enforces every rule.

import { KeyRound, Plus, Search, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Avatar, Button, Card, EmptyState, Skeleton } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import { ROLE_LABEL, type Role, type SessionUser } from "@/lib/session";

type Row = {
  id: number;
  full_name: string;
  email: string;
  role: Role;
  city: string;
  is_active: boolean;
  joined_at: string;
  has_password: boolean;
  google_linked: boolean;
  last_login_at: string | null;
};
type Page = { users: Row[]; total: number; page: number; page_size: number; by_role: Record<Role, number> };

const ROLES: Role[] = ["student", "teacher", "support", "admin"];
const field =
  "w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-brand focus:outline-none";

function when(iso: string | null) {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function AddUser({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ full_name: "", email: "", role: "teacher" as Role, password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/admin/users", { method: "POST", body: JSON.stringify(form) });
      setForm({ full_name: "", email: "", role: "teacher", password: "" });
      setOpen(false);
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}>
          <UserPlus className="h-4 w-4" /> Add a user
        </Button>
      </div>
    );
  }
  return (
    <Card title="Add a user" subtitle="Give them this first password and ask them to change it after logging in.">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        {error && (
          <div className="sm:col-span-2" role="alert">
            <Alert title={error} />
          </div>
        )}
        <label className="text-sm text-muted">
          Full name
          <input className={`${field} mt-1`} required minLength={2} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </label>
        <label className="text-sm text-muted">
          Email
          <input type="email" className={`${field} mt-1`} required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </label>
        <label className="text-sm text-muted">
          Role
          <select className={`${field} mt-1`} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-muted">
          First password
          <input type="text" autoComplete="off" className={`${field} mt-1 font-mono`} required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" disabled={busy}>
            <Plus className="h-4 w-4" /> {busy ? "Adding…" : "Add user"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

function Users({ me }: { me: SessionUser }) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams({ page: String(page) });
    if (q.trim()) params.set("q", q.trim());
    if (role) params.set("role", role);
    apiFetch<Page>(`/admin/users?${params}`)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [q, role, page]);

  useEffect(() => {
    const t = setTimeout(load, 200); // wait for typing to pause
    return () => clearTimeout(t);
  }, [load]);

  async function change(user: Row, body: Partial<Pick<Row, "role" | "is_active">>) {
    setRowError(null);
    try {
      const updated = await apiFetch<Row>(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setData((d) => d && { ...d, users: d.users.map((u) => (u.id === updated.id ? updated : u)) });
    } catch (e) {
      setRowError(e instanceof ApiError ? e.message : String(e));
    }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <AddUser onAdded={load} />
      <Card
        title="Users and roles"
        subtitle="Change a role and it applies on their next click. Deactivating someone signs them out everywhere."
        icon={<KeyRound className="h-4 w-4" />}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
            <input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
              placeholder="Search by name or email"
              aria-label="Search users"
              className={`${field} pl-9`}
            />
          </div>
          <div role="radiogroup" aria-label="Filter by role" className="flex flex-wrap gap-1.5">
            {(["", ...ROLES] as const).map((r) => (
              <button
                key={r || "all"}
                type="button"
                role="radio"
                aria-checked={role === r}
                onClick={() => {
                  setRole(r);
                  setPage(1);
                }}
                className={`rounded-full border px-3 py-1 text-xs font-medium ${
                  role === r ? "border-brand bg-brand-soft text-brand-ink" : "border-line text-muted hover:text-fg"
                }`}
              >
                {r ? ROLE_LABEL[r] : "All"}
                {data && r && <span className="ml-1 opacity-70">{data.by_role[r]}</span>}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="mt-4">
            <Alert title={error} />
          </div>
        )}
        {rowError && (
          <div className="mt-4" role="alert">
            <Alert title={rowError} />
          </div>
        )}

        <div className="mt-4 overflow-x-auto">
          {!data && !error && <Skeleton className="h-64 rounded-xl" />}
          {data && data.users.length === 0 && <EmptyState title="No users match" hint="Try another search or role." />}
          {data && data.users.length > 0 && (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-3 font-medium">Person</th>
                  <th className="py-2 pr-3 font-medium">Role</th>
                  <th className="py-2 pr-3 font-medium">Sign-in</th>
                  <th className="py-2 pr-3 font-medium">Last login</th>
                  <th className="py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => {
                  const self = u.id === me.id;
                  return (
                    <tr key={u.id} className={`border-b border-line/70 ${u.is_active ? "" : "opacity-60"}`}>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-2.5">
                          <Avatar name={u.full_name} role={u.role} size="sm" />
                          <div className="min-w-0">
                            <p className="truncate font-medium text-fg">
                              {u.full_name} {self && <span className="text-xs text-faint">(you)</span>}
                            </p>
                            <p className="truncate text-xs text-muted">{u.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="py-2.5 pr-3">
                        <select
                          aria-label={`Role of ${u.full_name}`}
                          value={u.role}
                          disabled={self}
                          onChange={(e) => change(u, { role: e.target.value as Role })}
                          className="rounded-lg border border-line bg-surface px-2 py-1 text-sm text-fg disabled:opacity-60"
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABEL[r]}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2.5 pr-3 text-xs text-muted">
                        {[u.has_password && "Password", u.google_linked && "Google"].filter(Boolean).join(" + ") ||
                          "Demo only"}
                      </td>
                      <td className="py-2.5 pr-3 text-xs text-muted">{when(u.last_login_at)}</td>
                      <td className="py-2.5">
                        <button
                          type="button"
                          disabled={self}
                          onClick={() => change(u, { is_active: !u.is_active })}
                          className={`rounded-full px-2.5 py-0.5 text-xs font-medium disabled:cursor-not-allowed ${
                            u.is_active ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"
                          }`}
                          title={u.is_active ? "Click to deactivate" : "Click to reactivate"}
                        >
                          {u.is_active ? "Active" : "Deactivated"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {data && pages > 1 && (
          <div className="mt-4 flex items-center justify-between text-sm text-muted">
            <span>
              Page {data.page} of {pages} · {data.total} users
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
              <Button variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}

export default function AdminUsersPage() {
  return (
    <PortalShell role="admin" title="Users & roles" showRoadmap={false}>
      {(me) => <Users me={me} />}
    </PortalShell>
  );
}
