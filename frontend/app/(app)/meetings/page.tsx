"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { CalendarDays, Plus, Video, Clock, CheckCircle2, XCircle, Radio } from "lucide-react";
import { PageHeader, EmptyState, Skeleton, Badge, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import Link from "next/link";

interface Meeting {
  id: string;
  title: string | null;
  provider: string;
  status: string;
  scheduled_at: string | null;
}

const statusConfig: Record<string, { icon: typeof Radio; color: "zinc" | "mint" | "blue" | "rose"; label: string }> = {
  scheduled: { icon: Clock, color: "zinc", label: "Scheduled" },
  live: { icon: Radio, color: "mint", label: "Live" },
  completed: { icon: CheckCircle2, color: "blue", label: "Completed" },
  failed: { icon: XCircle, color: "rose", label: "Failed" },
};

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

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={CalendarDays}
        title="Meetings"
        subtitle="Send the Recall.ai bot to transcribe and extract action items"
        action={
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-2 rounded-lg bg-mint px-4 py-2 text-sm font-medium text-canvas transition hover:brightness-110"
          >
            <Plus size={16} /> New meeting
          </button>
        }
      />

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

      {loading ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : meetings.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={Video}
            title="No meetings yet"
            description="Add a meeting URL and the Recall.ai bot will join, transcribe, and extract action items automatically."
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {meetings.map((m) => {
            const cfg = statusConfig[m.status] ?? statusConfig.scheduled;
            return (
              <Link key={m.id} href={`/meetings/${m.id}`}>
              <Card key={m.id} hover>
                {/* Status icon */}
                <div className="flex items-center justify-between">
                  <div className={cn(
                    "grid h-10 w-10 place-items-center rounded-xl",
                    cfg.color === "mint" && "bg-mint/10",
                    cfg.color === "blue" && "bg-blue-500/10",
                    cfg.color === "rose" && "bg-rose-500/10",
                    cfg.color === "zinc" && "bg-white/5",
                  )}>
                    <cfg.icon size={18} className={cn(
                      cfg.color === "mint" && "text-mint",
                      cfg.color === "blue" && "text-blue-400",
                      cfg.color === "rose" && "text-rose-400",
                      cfg.color === "zinc" && "text-zinc-400",
                      m.status === "live" && "animate-pulse",
                    )} />
                  </div>
                  <Badge color={cfg.color}>{cfg.label}</Badge>
                </div>

                <p className="mt-3 font-medium leading-snug">{m.title || "Untitled meeting"}</p>

                {m.scheduled_at && (
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-zinc-600">
                    <CalendarDays size={12} />
                    {new Date(m.scheduled_at).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </div>
                )}

                <div className="mt-3 border-t border-line pt-3">
                  <span className="text-xs text-zinc-600">Provider: </span>
                  <span className="text-xs font-medium text-zinc-400">{m.provider}</span>
                </div>
              </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
