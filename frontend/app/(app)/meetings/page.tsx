"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { CalendarDays, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

interface Meeting {
  id: string;
  title: string | null;
  provider: string;
  status: string;
  scheduled_at: string | null;
}

export default function MeetingsPage() {
  const { workspace } = useWorkspace();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [joinUrl, setJoinUrl] = useState("");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; meetings: Meeting[] }>(
      `/meetings?workspace_id=${workspace.id}`,
    )
      .then((r) => setMeetings(r.meetings))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [workspace]);

  if (!workspace) return null;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!joinUrl.trim()) return;
    setCreating(true);
    try {
      await api("/meetings", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          join_url: joinUrl,
          title: title || undefined,
        }),
      });
      setJoinUrl("");
      setTitle("");
      setShowForm(false);
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create meeting");
    } finally {
      setCreating(false);
    }
  };

  const statusColors: Record<string, string> = {
    scheduled: "bg-zinc-500/15 text-zinc-400",
    live: "bg-mint/15 text-mint",
    completed: "bg-blue-500/15 text-blue-400",
    failed: "bg-rose-500/15 text-rose-400",
  };

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-5 w-5 text-mint" />
          <h1 className="text-2xl font-bold">Meetings</h1>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-2 rounded-lg bg-mint px-4 py-2 text-sm font-medium text-canvas transition hover:brightness-110"
        >
          <Plus size={16} />
          New meeting
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={create}
          className="mt-4 space-y-3 rounded-xl border border-line bg-panel p-5"
        >
          <div>
            <label className="mb-1.5 block text-sm text-zinc-400">Join URL</label>
            <input
              value={joinUrl}
              onChange={(e) => setJoinUrl(e.target.value)}
              required
              placeholder="https://meet.google.com/..."
              className="w-full rounded-lg border border-line bg-canvas px-4 py-2.5 text-sm outline-none focus:border-mint/50"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm text-zinc-400">Title (optional)</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Weekly sync"
              className="w-full rounded-lg border border-line bg-canvas px-4 py-2.5 text-sm outline-none focus:border-mint/50"
            />
          </div>
          <button
            type="submit"
            disabled={creating}
            className="rounded-lg bg-mint px-4 py-2 text-sm font-medium text-canvas transition hover:brightness-110 disabled:opacity-50"
          >
            {creating ? "Creating..." : "Create + send bot"}
          </button>
        </form>
      )}

      <div className="mt-6 space-y-2">
        {loading ? (
          <div className="skeleton h-16 rounded-lg bg-white/5" />
        ) : meetings.length === 0 ? (
          <div className="rounded-xl border border-line bg-panel p-8 text-center">
            <p className="text-sm text-zinc-600">No meetings yet</p>
          </div>
        ) : (
          meetings.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between rounded-lg border border-line bg-panel px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium">{m.title || "Untitled meeting"}</p>
                {m.scheduled_at && (
                  <p className="mt-0.5 text-xs text-zinc-600">
                    {new Date(m.scheduled_at).toLocaleString()}
                  </p>
                )}
              </div>
              <span
                className={cn(
                  "rounded-md px-2 py-0.5 text-xs font-medium",
                  statusColors[m.status] ?? "bg-zinc-500/15 text-zinc-400",
                )}
              >
                {m.status}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
