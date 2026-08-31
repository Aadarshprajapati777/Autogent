"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Person } from "@/lib/types";
import {
  Users,
  Clock,
  Code2,
  UserPlus,
  Upload,
  X,
  Trash2,
  Download,
  FileText,
} from "lucide-react";
import {
  PageHeader,
  EmptyState,
  Skeleton,
  Avatar,
  Badge,
  Card,
} from "@/components/ui";

const ROLES = [
  "founder",
  "engineer",
  "marketer",
  "manager",
  "designer",
  "other",
];

interface PersonForm {
  name: string;
  role: string;
  title: string;
  skills: string;
  is_technical: boolean;
  timezone: string;
  languages: string;
  experience_years: string;
  availability_hours_per_week: string;
  interests: string;
  career_goals: string;
  resume_summary: string;
}

const EMPTY_FORM: PersonForm = {
  name: "",
  role: "other",
  title: "",
  skills: "",
  is_technical: false,
  timezone: "",
  languages: "",
  experience_years: "",
  availability_hours_per_week: "",
  interests: "",
  career_goals: "",
  resume_summary: "",
};

function parseList(s: string): string[] {
  return s
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

export default function PeoplePage() {
  const { workspace } = useWorkspace();
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [form, setForm] = useState<PersonForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [importText, setImportText] = useState("");
  const [importResult, setImportResult] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const loadPeople = () => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; people: Person[] }>(
      `/memory/people?workspace_id=${workspace.id}`,
    )
      .then((r) => setPeople(r.people))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!workspace) return;
    loadPeople();
    // eslint-disable-next-line react-hooks/set-state-in-effect
  }, [workspace]);

  if (!workspace) return null;

  const technical = people.filter((p) => p.is_technical);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api("/memory/people", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          name: form.name.trim(),
          role: form.role,
          title: form.title.trim() || null,
          skills: parseList(form.skills),
          languages: parseList(form.languages),
          is_technical: form.is_technical,
          experience_years: form.experience_years
            ? parseFloat(form.experience_years)
            : null,
          availability_hours_per_week: form.availability_hours_per_week
            ? parseFloat(form.availability_hours_per_week)
            : null,
          timezone: form.timezone.trim() || null,
          interests: parseList(form.interests),
          career_goals: form.career_goals.trim() || null,
          resume_summary: form.resume_summary.trim() || null,
        }),
      });
      setForm(EMPTY_FORM);
      setShowAdd(false);
      loadPeople();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add person");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (personId: string, name: string) => {
    if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
    try {
      await api(
        `/memory/people/${personId}?workspace_id=${workspace.id}`,
        { method: "DELETE" },
      );
      loadPeople();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete");
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setImportText(String(ev.target?.result ?? ""));
      setImportResult(null);
    };
    reader.readAsText(file);
  };

  const parseCsv = (text: string): PersonForm[] => {
    const lines = text.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length === 0) return [];
    // Detect header
    const firstLine = lines[0].toLowerCase();
    const hasHeader =
      firstLine.includes("name") || firstLine.includes("role");
    const rows = hasHeader ? lines.slice(1) : lines;
    const headers = hasHeader
      ? lines[0].split(",").map((h) => h.trim().toLowerCase())
      : ["name", "role", "title", "skills", "timezone"];

    return rows.map((line) => {
      const cells = line.split(",").map((c) => c.trim());
      const get = (key: string) => {
        const idx = headers.indexOf(key);
        return idx >= 0 ? cells[idx] ?? "" : "";
      };
      return {
        name: get("name"),
        role: get("role") || "other",
        title: get("title"),
        skills: get("skills"),
        is_technical: get("is_technical") === "true" || get("technical") === "true",
        timezone: get("timezone"),
        languages: get("languages"),
        experience_years: get("experience_years") || get("experience"),
        availability_hours_per_week: get("availability") || get("availability_hours_per_week"),
        interests: get("interests"),
        career_goals: get("career_goals") || get("goals"),
        resume_summary: get("resume_summary") || get("resume"),
      };
    });
  };

  const handleImport = async () => {
    const parsed = parseCsv(importText);
    const valid = parsed.filter((p) => p.name.trim());
    if (valid.length === 0) {
      setImportResult("No valid rows found. Ensure each row has a name.");
      return;
    }
    setImporting(true);
    setImportResult(null);
    try {
      const payload = valid.map((p) => ({
        workspace_id: workspace.id,
        name: p.name.trim(),
        role: ROLES.includes(p.role) ? p.role : "other",
        title: p.title.trim() || null,
        skills: parseList(p.skills),
        languages: parseList(p.languages),
        is_technical: p.is_technical,
        experience_years: p.experience_years ? parseFloat(p.experience_years) : null,
        availability_hours_per_week: p.availability_hours_per_week
          ? parseFloat(p.availability_hours_per_week)
          : null,
        timezone: p.timezone.trim() || null,
        interests: parseList(p.interests),
        career_goals: p.career_goals.trim() || null,
        resume_summary: p.resume_summary.trim() || null,
      }));
      const res = await api<{ created: number; updated: number; errors: any[] }>(
        "/memory/people/bulk",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspace.id,
            people: payload,
          }),
        },
      );
      setImportResult(
        `Imported ${res.created} new, updated ${res.updated}.` +
          (res.errors.length ? ` ${res.errors.length} errors.` : ""),
      );
      loadPeople();
    } catch (err) {
      setImportResult(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  };

  const downloadTemplate = () => {
    const csv = "name,role,title,skills,timezone,is_technical,languages,experience_years,availability_hours_per_week,interests,career_goals,resume_summary\n" +
      "Alice Johnson,engineer,Senior Backend Engineer,Python;FastAPI;PostgreSQL,Asia/Kolkata,true,English;Hindi,5,40,systems design,tech lead,Backend engineer with 5 years experience\n" +
      "Bob Smith,manager,Product Manager,roadmaps;analytics,America/New_York,false,English,8,40,user research,head of product,PM with 8 years in B2B SaaS\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "people-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={Users}
        title="People"
        subtitle="Profiles the agent has built from interactions"
        action={
          <div className="flex gap-2">
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm font-medium text-zinc-300 transition hover:border-white/20 hover:text-white"
            >
              <Upload size={15} />
              Import CSV
            </button>
            <button
              onClick={() => {
                setForm(EMPTY_FORM);
                setError(null);
                setShowAdd(true);
              }}
              className="flex items-center gap-2 rounded-lg bg-mint px-3 py-2 text-sm font-semibold text-black transition hover:bg-mint/90"
            >
              <UserPlus size={15} />
              Add Person
            </button>
          </div>
        }
      />

      {/* Stats */}
      <div className="mt-6 flex gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
          <Users size={16} className="text-mint" />
          <span className="text-sm text-zinc-400">Total</span>
          <span className="text-sm font-bold">{people.length}</span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
          <Code2 size={16} className="text-blue-400" />
          <span className="text-sm text-zinc-400">Technical</span>
          <span className="text-sm font-bold">{technical.length}</span>
        </div>
      </div>

      {loading ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : people.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={Users}
            title="No people yet"
            description="Add team members manually or import from CSV. The agent also creates profiles as it learns about your team."
            action={
              <div className="flex gap-2">
                <button
                  onClick={() => setShowImport(true)}
                  className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm font-medium text-zinc-300 transition hover:border-white/20"
                >
                  <Upload size={14} /> Import CSV
                </button>
                <button
                  onClick={() => setShowAdd(true)}
                  className="flex items-center gap-2 rounded-lg bg-mint px-3 py-2 text-sm font-semibold text-black transition hover:bg-mint/90"
                >
                  <UserPlus size={14} /> Add Person
                </button>
              </div>
            }
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {people.map((p) => (
            <Card key={p.person_id ?? p.name} hover>
              {/* Header */}
              <div className="flex items-center gap-3">
                <Avatar name={p.name} size={48} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{p.name}</p>
                  <p className="truncate text-sm text-zinc-500">{p.role}</p>
                </div>
                {p.is_technical && (
                  <Badge color="blue">
                    <Code2 size={10} /> Eng
                  </Badge>
                )}
                {p.person_id && (
                  <button
                    onClick={() => handleDelete(p.person_id!, p.name)}
                    className="text-zinc-600 transition hover:text-rose-400"
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>

              {/* Title */}
              {p.title && (
                <p className="mt-3 text-sm text-zinc-400">{p.title}</p>
              )}

              {/* Meta */}
              <div className="mt-3 space-y-1.5">
                {p.timezone && (
                  <div className="flex items-center gap-2 text-xs text-zinc-600">
                    <Clock size={12} />
                    {p.timezone}
                  </div>
                )}
              </div>

              {/* Skills */}
              {p.skills && p.skills.length > 0 && (
                <div className="mt-3 border-t border-line pt-3">
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-600">
                    Skills
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {p.skills.map((s) => (
                      <span
                        key={s}
                        className="rounded-md bg-mint/10 px-2 py-0.5 text-xs text-mint/80"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* Add Person Modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-zinc-900 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">Add Person</h2>
              <button
                onClick={() => setShowAdd(false)}
                className="text-zinc-500 transition hover:text-white"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleAdd} className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Name *">
                  <input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Jane Doe"
                    className={inputCls}
                    required
                  />
                </Field>
                <Field label="Role">
                  <select
                    value={form.role}
                    onChange={(e) => setForm({ ...form, role: e.target.value })}
                    className={inputCls}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              <Field label="Title">
                <input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Senior Engineer"
                  className={inputCls}
                />
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Skills (comma separated)">
                  <input
                    value={form.skills}
                    onChange={(e) => setForm({ ...form, skills: e.target.value })}
                    placeholder="Python, React, SQL"
                    className={inputCls}
                  />
                </Field>
                <Field label="Languages (comma separated)">
                  <input
                    value={form.languages}
                    onChange={(e) => setForm({ ...form, languages: e.target.value })}
                    placeholder="English, Hindi"
                    className={inputCls}
                  />
                </Field>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Timezone">
                  <input
                    value={form.timezone}
                    onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                    placeholder="Asia/Kolkata"
                    className={inputCls}
                  />
                </Field>
                <Field label="Experience (years)">
                  <input
                    type="number"
                    step="0.5"
                    value={form.experience_years}
                    onChange={(e) => setForm({ ...form, experience_years: e.target.value })}
                    placeholder="5"
                    className={inputCls}
                  />
                </Field>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Availability (hrs/week)">
                  <input
                    type="number"
                    value={form.availability_hours_per_week}
                    onChange={(e) => setForm({ ...form, availability_hours_per_week: e.target.value })}
                    placeholder="40"
                    className={inputCls}
                  />
                </Field>
                <Field label="Technical?">
                  <label className="flex h-[38px] items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.is_technical}
                      onChange={(e) => setForm({ ...form, is_technical: e.target.checked })}
                      className="h-4 w-4 accent-mint"
                    />
                    <span className="text-sm text-zinc-400">Is engineer/technical</span>
                  </label>
                </Field>
              </div>

              <Field label="Interests (comma separated)">
                <input
                  value={form.interests}
                  onChange={(e) => setForm({ ...form, interests: e.target.value })}
                  placeholder="systems design, open source"
                  className={inputCls}
                />
              </Field>

              <Field label="Career goals">
                <input
                  value={form.career_goals}
                  onChange={(e) => setForm({ ...form, career_goals: e.target.value })}
                  placeholder="Become a tech lead"
                  className={inputCls}
                />
              </Field>

              <Field label="Resume summary">
                <textarea
                  value={form.resume_summary}
                  onChange={(e) => setForm({ ...form, resume_summary: e.target.value })}
                  placeholder="Brief bio or summary..."
                  rows={3}
                  className={inputCls}
                />
              </Field>

              {error && (
                <p className="text-sm text-rose-400">{error}</p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAdd(false)}
                  className="rounded-lg border border-line px-4 py-2 text-sm text-zinc-400 transition hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-lg bg-mint px-4 py-2 text-sm font-semibold text-black transition hover:bg-mint/90 disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save Person"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Import CSV Modal */}
      {showImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-line bg-zinc-900 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">Import People from CSV</h2>
              <button
                onClick={() => setShowImport(false)}
                className="text-zinc-500 transition hover:text-white"
              >
                <X size={20} />
              </button>
            </div>

            <div className="mt-4 space-y-4">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => fileRef.current?.click()}
                  className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm font-medium text-zinc-300 transition hover:border-white/20"
                >
                  <FileText size={14} /> Choose CSV file
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <button
                  onClick={downloadTemplate}
                  className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm font-medium text-zinc-300 transition hover:border-white/20"
                >
                  <Download size={14} /> Download template
                </button>
              </div>

              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-600">
                  CSV content (or paste here)
                </p>
                <textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  rows={8}
                  placeholder="name,role,title,skills,timezone,is_technical,languages,experience_years,availability_hours_per_week,interests,career_goals,resume_summary&#10;Alice Johnson,engineer,Senior Engineer,Python;SQL,Asia/Kolkata,true,English,5,40,systems design,tech lead,Bio here"
                  className={inputCls + " font-mono text-xs"}
                />
              </div>

              <div className="rounded-lg border border-line bg-panel/50 p-3 text-xs text-zinc-500">
                <p className="font-semibold text-zinc-400">Expected columns:</p>
                <p className="mt-1">
                  name (required), role, title, skills, timezone, is_technical,
                  languages, experience_years, availability_hours_per_week,
                  interests, career_goals, resume_summary
                </p>
                <p className="mt-2 text-zinc-600">
                  Lists (skills, languages, interests) can be semicolon or comma
                  separated within a cell. The first row should be a header.
                </p>
              </div>

              {importResult && (
                <p className="text-sm text-mint">{importResult}</p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowImport(false)}
                  className="rounded-lg border border-line px-4 py-2 text-sm text-zinc-400 transition hover:text-white"
                >
                  Close
                </button>
                <button
                  onClick={handleImport}
                  disabled={importing || !importText.trim()}
                  className="rounded-lg bg-mint px-4 py-2 text-sm font-semibold text-black transition hover:bg-mint/90 disabled:opacity-50"
                >
                  {importing ? "Importing..." : "Import"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm text-zinc-200 outline-none transition focus:border-mint/50 placeholder:text-zinc-600";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-zinc-600">
        {label}
      </label>
      {children}
    </div>
  );
}
