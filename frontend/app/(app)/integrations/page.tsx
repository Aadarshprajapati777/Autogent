"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Integration } from "@/lib/types";
import { Link2 } from "lucide-react";
import { cn } from "@/lib/utils";

const providerLabels: Record<string, string> = {
  slack: "Slack",
  github: "GitHub",
  jira: "Jira",
  linear: "Linear",
  google_calendar: "Google Calendar",
  microsoft_calendar: "Microsoft Calendar",
  notion: "Notion",
  recall: "Recall.ai",
};

export default function IntegrationsPage() {
  const { workspace } = useWorkspace();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; integrations: Integration[] }>(
      `/integrations?workspace_id=${workspace.id}`,
    )
      .then((r) => setIntegrations(r.integrations))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [workspace]);

  if (!workspace) return null;

  const connect = async (provider: string) => {
    try {
      const res = await api<{ auth_url: string }>(
        `/integrations/${provider}/connect?workspace_id=${workspace.id}`,
      );
      window.location.href = res.auth_url;
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to connect");
    }
  };

  const disconnect = async (id: string) => {
    if (!confirm("Disconnect this integration?")) return;
    try {
      await api(`/integrations/${id}/disconnect`, { method: "POST" });
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to disconnect");
    }
  };

  const connected = new Map(integrations.map((i) => [i.provider, i]));

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <Link2 className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">Integrations</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Connect the agent to your tools.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {loading ? (
          <div className="skeleton h-28 rounded-xl bg-white/5" />
        ) : (
          Object.entries(providerLabels).map(([provider, label]) => {
            const integration = connected.get(provider);
            const isConnected = integration?.state === "connected";
            return (
              <div
                key={provider}
                className="flex items-center justify-between rounded-xl border border-line bg-panel p-5"
              >
                <div>
                  <p className="font-medium">{label}</p>
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {isConnected ? "Connected" : "Not connected"}
                  </p>
                </div>
                {isConnected ? (
                  <button
                    onClick={() => disconnect(integration!.id)}
                    className="rounded-lg border border-line px-4 py-2 text-sm text-zinc-400 transition hover:border-rose-500/50 hover:text-rose-400"
                  >
                    Disconnect
                  </button>
                ) : (
                  <button
                    onClick={() => connect(provider)}
                    className={cn(
                      "rounded-lg bg-mint px-4 py-2 text-sm font-medium text-canvas transition hover:brightness-110",
                    )}
                  >
                    Connect
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
