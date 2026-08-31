"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { ChatMessage, AgentResponse, ActionTrace } from "@/lib/types";
import { Send, Sparkles, Wrench, ChevronDown, CheckCircle2, XCircle, Loader2 } from "lucide-react";
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
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
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

  const suggestions = [
    "Check in with the team on Slack",
    "What do you know about the API project?",
    "Create a task for the auth refactor",
    "Who's working on what right now?",
  ];

  return (
    <div className="flex h-[calc(100vh-70px)] flex-col">
      {/* Header */}
      <div className="border-b border-line px-6 py-4 lg:px-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-mint/10">
              <Sparkles className="h-5 w-5 text-mint" />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Agent</h1>
              <p className="text-xs text-zinc-500">Powered by Gemini 3.5 Flash + Google ADK</p>
            </div>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6 lg:px-8">
        <div className="mx-auto max-w-2xl space-y-6">
          {historyLoading ? (
            <div className="space-y-4">
              <div className="skeleton h-16 rounded-2xl bg-white/5" />
              <div className="skeleton h-24 rounded-2xl bg-white/5" />
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16">
              <div className="grid h-16 w-16 place-items-center rounded-2xl bg-mint/10">
                <Sparkles className="h-8 w-8 text-mint" />
              </div>
              <p className="mt-4 text-lg font-semibold">Start a conversation</p>
              <p className="mt-1 text-sm text-zinc-500">
                The agent uses tools to take real action — not just chat.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => setInput(s)}
                    className="rounded-full border border-line bg-panel px-3.5 py-1.5 text-xs text-zinc-400 transition hover:border-mint/30 hover:text-mint"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)
          )}
          {loading && (
            <div className="flex gap-3">
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-mint/20">
                <Loader2 size={16} className="animate-spin text-mint" />
              </div>
              <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-line bg-panel px-4 py-3">
                <span className="h-2 w-2 animate-bounce rounded-full bg-mint/50 [animation-delay:-0.3s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-mint/50 [animation-delay:-0.15s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-mint/50" />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Input */}
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
        {isUser ? "U" : <Sparkles size={14} />}
      </div>
      <div className={cn("max-w-[80%] space-y-2", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "rounded-tr-sm bg-mint text-canvas"
              : "rounded-tl-sm border border-line bg-panel",
          )}
        >
          {msg.text}
        </div>
        {msg.actions && msg.actions.length > 0 && (
          <div className="space-y-2">
            <p className="px-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-600">
              {msg.actions.length} tool {msg.actions.length === 1 ? "call" : "calls"}
            </p>
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
  const hasError = !!action.error;
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border transition",
        hasError ? "border-rose-500/20 bg-rose-500/[.03]" : "border-line bg-white/[.02]",
      )}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-xs transition hover:bg-white/[.03]"
      >
        {hasError ? (
          <XCircle size={14} className="shrink-0 text-rose-400" />
        ) : (
          <CheckCircle2 size={14} className="shrink-0 text-mint" />
        )}
        <Wrench size={12} className="shrink-0 text-zinc-600" />
        <span className="font-mono font-medium text-zinc-300">{action.tool}</span>
        <span className="text-zinc-600">
          {Object.keys(action.arguments).length} {Object.keys(action.arguments).length === 1 ? "arg" : "args"}
        </span>
        <ChevronDown
          size={14}
          className={cn("ml-auto shrink-0 text-zinc-600 transition-transform", expanded && "rotate-180")}
        />
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-line/50 px-3 py-2.5 font-mono text-[11px]">
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">Arguments</p>
            <pre className="overflow-x-auto rounded bg-black/30 p-2 text-zinc-400">
              {JSON.stringify(action.arguments, null, 2)}
            </pre>
          </div>
          {action.result && (
            <div>
              <p className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">Result</p>
              <pre className="max-h-48 overflow-auto rounded bg-black/30 p-2 text-mint/70">
                {action.result.slice(0, 800)}
              </pre>
            </div>
          )}
          {action.error && (
            <div>
              <p className="mb-1 text-[10px] uppercase tracking-wide text-rose-400/70">Error</p>
              <pre className="overflow-x-auto rounded bg-black/30 p-2 text-rose-400">
                {action.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
