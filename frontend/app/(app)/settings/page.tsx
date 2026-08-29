"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { Settings } from "lucide-react";
import { cn } from "@/lib/utils";

interface EscalationRule {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  conditions: Record<string, unknown>;
  action: Record<string, unknown>;
}

export default function SettingsPage() {
  const { workspace } = useWorkspace();
  const [rules, setRules] = useState<EscalationRule[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; rules: EscalationRule[] }>(
      `/settings/escalations?workspace_id=${workspace.id}`,
    )
      .then((r) => setRules(r.rules))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [workspace]);

  if (!workspace) return null;

  const toggle = async (rule: EscalationRule) => {
    try {
      await api(`/settings/escalations/${rule.id}?workspace_id=${workspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    }
  };

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <Settings className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">Settings</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Escalation rules and workspace configuration.
      </p>

      <div className="mt-8">
        <h2 className="text-lg font-semibold">Escalation rules</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Rules the agent uses to escalate issues automatically.
        </p>

        <div className="mt-4 space-y-2">
          {loading ? (
            <div className="skeleton h-20 rounded-lg bg-white/5" />
          ) : rules.length === 0 ? (
            <div className="rounded-xl border border-line bg-panel p-8 text-center">
              <p className="text-sm text-zinc-600">No escalation rules</p>
            </div>
          ) : (
            rules.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between rounded-lg border border-line bg-panel px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{r.name}</p>
                  <p className="mt-0.5 text-xs text-zinc-600">
                    Priority {r.priority} ·{" "}
                    {Object.entries(r.conditions)
                      .map(([k, v]) => `${k}=${String(v)}`)
                      .join(", ")}
                  </p>
                </div>
                <button
                  onClick={() => toggle(r)}
                  className={cn(
                    "relative h-6 w-11 shrink-0 rounded-full transition",
                    r.enabled ? "bg-mint" : "bg-zinc-700",
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform",
                      r.enabled ? "translate-x-5" : "translate-x-0.5",
                    )}
                  />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
