"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Meeting, TranscriptChunk, MeetingExtraction } from "@/lib/types";
import { ArrowLeft, FileText, CheckCircle2, AlertTriangle, User, Clock } from "lucide-react";
import { PageHeader, Skeleton, Card, Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import Link from "next/link";

export default function MeetingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { workspace } = useWorkspace();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [extraction, setExtraction] = useState<MeetingExtraction | null>(null);
  const [loading, setLoading] = useState(true);
  const [id, setId] = useState<string>("");

  useEffect(() => {
    params.then((p) => setId(p.id));
  }, [params]);

  const load = () => {
    if (!workspace || !id) return;
    setLoading(true);
    Promise.all([
      api<Meeting>(`/meetings/${id}?workspace_id=${workspace.id}`),
      api<{ chunks: TranscriptChunk[]; status: string }>(
        `/meetings/${id}/transcript?workspace_id=${workspace.id}`,
      ).catch(() => ({ chunks: [], status: null })),
      api<MeetingExtraction>(
        `/meetings/${id}/extraction?workspace_id=${workspace.id}`,
      ).catch(() => null),
    ])
      .then(([m, t, e]) => {
        setMeeting(m);
        setTranscript(t.chunks || []);
        setExtraction(e);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [workspace, id]);

  if (!workspace || loading) {
    return (
      <div className="p-6 lg:p-8">
        <Skeleton className="h-8 w-48" />
        <div className="mt-6 space-y-4">
          <Skeleton className="h-32" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (!meeting) {
    return (
      <div className="p-6 lg:p-8">
        <Link href="/meetings" className="flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-300">
          <ArrowLeft size={14} /> Back to meetings
        </Link>
        <p className="mt-8 text-zinc-500">Meeting not found</p>
      </div>
    );
  }

  const formatTime = (ms: number | null) => {
    if (ms === null) return "";
    const seconds = Math.floor(ms / 1000);
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="p-6 lg:p-8">
      <Link href="/meetings" className="flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-300">
        <ArrowLeft size={14} /> Back to meetings
      </Link>

      <div className="mt-4">
        <PageHeader
          icon={FileText}
          title={meeting.title || "Untitled meeting"}
          subtitle={`${meeting.provider} · ${meeting.status}`}
        />
      </div>

      {meeting.scheduled_at && (
        <div className="mt-3 flex items-center gap-2 text-sm text-zinc-500">
          <Clock size={14} />
          {new Date(meeting.scheduled_at).toLocaleString()}
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {/* Extraction: Summary + Decisions + Tasks */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">AI Summary</h2>

          {extraction?.status === "completed" && extraction.summary ? (
            <Card>
              <p className="text-sm leading-relaxed text-zinc-300">{extraction.summary}</p>
              {extraction.confidence !== null && (
                <div className="mt-3 border-t border-line pt-3">
                  <span className="text-xs text-zinc-600">Confidence: </span>
                  <span className="text-xs font-medium text-mint">
                    {Math.round(extraction.confidence * 100)}%
                  </span>
                </div>
              )}
            </Card>
          ) : extraction?.status === "processing" ? (
            <Card>
              <div className="flex items-center gap-2 text-sm text-zinc-500">
                <div className="h-3 w-3 animate-pulse rounded-full bg-mint" />
                Extracting decisions and tasks...
              </div>
            </Card>
          ) : extraction?.status === "failed" ? (
            <Card>
              <p className="text-sm text-rose-400">Extraction failed. The agent can retry.</p>
            </Card>
          ) : (
            <Card>
              <p className="text-sm text-zinc-500">
                No extraction yet. The agent will process the transcript once the meeting ends.
              </p>
            </Card>
          )}

          {/* Decisions */}
          {extraction?.decisions && extraction.decisions.length > 0 && (
            <div>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-400">
                <CheckCircle2 size={14} className="text-mint" />
                Decisions ({extraction.decisions.length})
              </h3>
              <div className="space-y-2">
                {extraction.decisions.map((d, i) => (
                  <Card key={i}>
                    <p className="text-sm font-medium">{d.title}</p>
                    {d.rationale && (
                      <p className="mt-1 text-xs text-zinc-500">{d.rationale}</p>
                    )}
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* Tasks */}
          {extraction?.tasks && extraction.tasks.length > 0 && (
            <div>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-400">
                <AlertTriangle size={14} className="text-amber-400" />
                Action Items ({extraction.tasks.length})
              </h3>
              <div className="space-y-2">
                {extraction.tasks.map((t, i) => (
                  <Card key={i}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">
                          <span className="text-zinc-600">{t.ref}</span> {t.title}
                        </p>
                        {t.description && (
                          <p className="mt-1 text-xs text-zinc-500">{t.description}</p>
                        )}
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          {t.owner_name && (
                            <span className="flex items-center gap-1 text-xs text-zinc-400">
                              <User size={11} /> {t.owner_name}
                            </span>
                          )}
                          {t.due_at && (
                            <span className="text-xs text-zinc-500">
                              due {new Date(t.due_at).toLocaleDateString()}
                            </span>
                          )}
                          <Badge color={t.state === "auto_approved" ? "mint" : "zinc"}>
                            {t.state === "auto_approved" ? "Auto-approved" : "Pending"}
                          </Badge>
                        </div>
                      </div>
                      <span className="text-xs text-zinc-600">
                        {Math.round(t.confidence * 100)}%
                      </span>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Transcript */}
        <div>
          <h2 className="mb-4 text-lg font-semibold">Transcript</h2>
          {transcript.length === 0 ? (
            <Card>
              <p className="text-sm text-zinc-500">
                No transcript available. The bot will transcribe when it joins the meeting.
              </p>
            </Card>
          ) : (
            <div className="max-h-[600px] space-y-3 overflow-y-auto rounded-xl border border-line p-4">
              {transcript.map((chunk) => (
                <div key={chunk.id} className="flex gap-3">
                  <div className="w-20 shrink-0">
                    <p className="text-xs font-medium text-mint">{chunk.speaker}</p>
                    {chunk.started_ms !== null && (
                      <p className="text-xs text-zinc-600">{formatTime(chunk.started_ms)}</p>
                    )}
                  </div>
                  <p className="flex-1 text-sm leading-relaxed text-zinc-300">{chunk.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
