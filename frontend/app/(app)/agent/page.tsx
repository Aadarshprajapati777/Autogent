"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { ChatMessage, AgentResponse, ActionTrace } from "@/lib/types";
import { Send, Sparkles, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";

export default function AgentPage() {
  const { workspace } = useWorkspace();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!workspace) return;
    setHistoryLoading(true);
    api<{ count: number; messages: ChatMessage[] }>(
      `/agent/history?workspace_id=${workspace.id}`,
    )
      .then((r) => setMessages(r.messages))
      .catch(() => {})
      .finally(() => setHistoryLoading(false));
  }, [workspace]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  if (!workspace) return null;

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const res = await api<AgentResponse>("/agent/chat", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, message: text }),
      });
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.answer, actions: res.actions },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: `Error: ${err instanceof Error ? err.message : "failed"}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-70px)] flex-col">
      <div className="border-b border-line px-6 py-4 lg:px-8">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-mint" />
          <h1 className="text-lg font-semibold">Agent</h1>
        </div>
        <p className="mt-0.5 text-sm text-zinc-500">
          Ask the agent to do work — it calls tools to act.
        </p>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6 lg:px-8">
        <div className="mx-auto max-w-2xl space-y-4">
          {historyLoading ? (
            <div className="skeleton h-20 rounded-lg bg-white/5" />
          ) : messages.length === 0 ? (
            <div className="rounded-xl border border-line bg-panel p-6 text-center">
              <Sparkles className="mx-auto h-8 w-8 text-mint" />
              <p className="mt-3 font-medium">Start a conversation</p>
              <p className="mt-1 text-sm text-zinc-500">
                Try: &ldquo;Check in with the team on Slack&rdquo; or &ldquo;What do you know about
                the API project?&rdquo;
              </p>
            </div>
          ) : (
            messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)
          )}
          {loading && (
            <div className="flex gap-3">
              <div className="skeleton h-8 w-8 shrink-0 rounded-full bg-mint/20" />
              <div className="skeleton h-12 flex-1 rounded-lg bg-white/5" />
            </div>
          )}
        </div>
      </div>

      <form
        onSubmit={send}
        className="border-t border-line px-6 py-4 lg:px-8"
      >
        <div className="mx-auto flex max-w-2xl gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Message the agent..."
            className="flex-1 rounded-xl border border-line bg-panel px-4 py-3 text-sm outline-none transition focus:border-mint/50"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-mint text-canvas transition hover:brightness-110 disabled:opacity-50"
          >
            <Send size={18} />
          </button>
        </div>
      </form>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-bold",
          isUser ? "bg-zinc-700 text-white" : "bg-mint/20 text-mint",
        )}
      >
        {isUser ? "U" : "A"}
      </div>
      <div className={cn("max-w-[80%] space-y-2", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm",
            isUser
              ? "rounded-tr-sm bg-mint text-canvas"
              : "rounded-tl-sm border border-line bg-panel",
          )}
        >
          {msg.text}
        </div>
        {msg.actions && msg.actions.length > 0 && (
          <div className="space-y-1.5">
            {msg.actions.map((action, i) => (
              <ActionCard key={i} action={action} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ActionCard({ action }: { action: ActionTrace }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <button
      onClick={() => setExpanded((v) => !v)}
      className="w-full rounded-lg border border-line bg-white/[.02] px-3 py-2 text-left text-xs transition hover:bg-white/[.04]"
    >
      <div className="flex items-center gap-2">
        <Wrench size={12} className={action.error ? "text-rose-400" : "text-mint"} />
        <span className="font-mono font-medium">{action.tool}</span>
        <span className="text-zinc-600">
          {Object.keys(action.arguments).length} args
        </span>
      </div>
      {expanded && (
        <div className="mt-2 space-y-1 font-mono text-[11px] text-zinc-500">
          <pre className="overflow-x-auto rounded bg-black/30 p-2">
            {JSON.stringify(action.arguments, null, 2)}
          </pre>
          {action.result && (
            <pre className="overflow-x-auto rounded bg-black/30 p-2 text-mint/70">
              {action.result.slice(0, 500)}
            </pre>
          )}
          {action.error && (
            <pre className="overflow-x-auto rounded bg-black/30 p-2 text-rose-400">
              {action.error}
            </pre>
          )}
        </div>
      )}
    </button>
  );
}
