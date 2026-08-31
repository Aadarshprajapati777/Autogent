"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Integration, IntegrationResource } from "@/lib/types";
import { Link2, Check, Plug, Zap, Settings2, X, RefreshCw } from "lucide-react";
import { PageHeader, EmptyState, Skeleton, Card } from "@/components/ui";
import { cn } from "@/lib/utils";

const providers: Record<
  string,
  {
    label: string;
    color: string;
    emoji: string;
    description: string;
    available?: boolean;
    managed?: boolean;
    resourceLabel?: string;
  }
> = {
  slack: {
    label: "Slack",
    color: "bg-purple-500",
    emoji: "💬",
    description: "DMs, channels, check-ins",
    available: true,
  },
  github: {
    label: "GitHub",
    color: "bg-zinc-700",
    emoji: "🐙",
    description: "Commits, PRs, issues",
    available: true,
    resourceLabel: "repos",
  },
  jira: {
    label: "Jira",
    color: "bg-blue-600",
    emoji: "📋",
    description: "Tickets and sprints",
    available: true,
    resourceLabel: "projects",
  },
  linear: {
    label: "Linear",
    color: "bg-indigo-600",
    emoji: "📐",
    description: "Issues and projects",
    available: true,
    resourceLabel: "teams",
  },
  recall: {
    label: "Recall.ai",
    color: "bg-orange-500",
    emoji: "🎥",
    description: "Meeting transcription",
    available: true,
    managed: true,
  },
  google_calendar: {
    label: "Google Calendar",
    color: "bg-blue-500",
    emoji: "📅",
    description: "Events and scheduling",
    available: false,
  },
  microsoft_calendar: {
    label: "Microsoft Calendar",
    color: "bg-blue-700",
    emoji: "📆",
    description: "Outlook events",
    available: false,
  },
  notion: {
    label: "Notion",
    color: "bg-zinc-800",
    emoji: "📝",
    description: "Docs and wikis",
    available: false,
  },
};

// Providers that support resource selection after connecting.
// Slack is NOT here — the bot is installed workspace-wide and can
// interact with any channel/user without pre-selection.
const CONFIGURABLE_PROVIDERS = ["github", "jira", "linear"];

export default function IntegrationsPage() {
  const { workspace } = useWorkspace();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [configProvider, setConfigProvider] = useState<string | null>(null);
  const [resources, setResources] = useState<IntegrationResource[]>([]);
  const [selectedResources, setSelectedResources] = useState<string[]>([]);
  const [loadingResources, setLoadingResources] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [syncing, setSyncing] = useState(false);

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

  const syncPeople = async () => {
    if (!workspace) return;
    setSyncing(true);
    try {
      const res = await api<{ synced: boolean; results: Record<string, unknown> }>(
        `/integrations/sync?workspace_id=${workspace.id}`,
        { method: "POST" },
      );
      const results = res.results;
      const summary = Object.entries(results)
        .map(([provider, r]) => {
          const data = r as { created?: number; updated?: number; error?: string };
          return data.error
            ? `${provider}: error`
            : `${provider}: ${data.created || 0} new, ${data.updated || 0} updated`;
        })
        .join(", ");
      alert(`People sync complete: ${summary}`);
    } catch {
      alert("Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    load();
  }, [workspace]);

  if (!workspace) return null;

  const connect = async (provider: string) => {
    try {
      const res = await api<{ authorize_url: string }>(
        `/integrations/${provider}/connect?workspace_id=${workspace.id}`,
      );
      window.location.href = res.authorize_url;
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to connect");
    }
  };

  const disconnect = async (provider: string) => {
    if (!confirm("Disconnect this integration?")) return;
    try {
      await api(`/integrations/${provider}?workspace_id=${workspace.id}`, {
        method: "DELETE",
      });
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to disconnect");
    }
  };

  const openConfig = async (provider: string) => {
    setConfigProvider(provider);
    setLoadingResources(true);
    setResources([]);
    setSelectedResources([]);
    try {
      // Load available resources and current config in parallel
      const [resData, cfgData] = await Promise.all([
        api<{ provider: string; resources: IntegrationResource[] }>(
          `/integrations/${provider}/resources?workspace_id=${workspace.id}`,
        ),
        api<{ provider: string; config: Record<string, unknown> }>(
          `/integrations/${provider}/config?workspace_id=${workspace.id}`,
        ).catch(() => ({ provider, config: {} })),
      ]);
      setResources(resData.resources);
      // Load currently selected resources from config
      const config = cfgData.config as Record<string, unknown> | undefined;
      const current = (config?.selected_resources as string[]) || [];
      setSelectedResources(current);
    } catch (err) {
      // Error loading resources — show empty
    } finally {
      setLoadingResources(false);
    }
  };

  const toggleResource = (id: string) => {
    setSelectedResources((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id],
    );
  };

  const saveConfig = async () => {
    if (!configProvider) return;
    setSavingConfig(true);
    try {
      await api(`/integrations/${configProvider}/config?workspace_id=${workspace.id}`, {
        method: "PUT",
        body: JSON.stringify({ selected_resources: selectedResources }),
      });
      setConfigProvider(null);
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingConfig(false);
    }
  };

  const connected = new Map(integrations.map((i) => [i.provider, i]));
  const connectedCount = integrations.filter(
    (i) => i.state === "connected",
  ).length;

  const cfg = configProvider ? providers[configProvider] : null;

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={Link2}
        title="Integrations"
        subtitle="Connect the agent to your tools"
      />

      {/* Summary */}
      <div className="mt-6 flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
          <Zap size={16} className="text-mint" />
          <span className="text-sm text-zinc-400">Connected</span>
          <span className="text-sm font-bold">{connectedCount}</span>
          <span className="text-sm text-zinc-600">
            / {Object.keys(providers).length}
          </span>
        </div>
        {connectedCount > 0 && (
          <button
            onClick={syncPeople}
            disabled={syncing}
            className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm text-zinc-400 transition hover:border-mint/50 hover:text-mint disabled:opacity-50"
          >
            <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
            {syncing ? "Syncing..." : "Sync People"}
          </button>
        )}
      </div>

      {loading ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(providers).map(([provider, cfg]) => {
            const integration = connected.get(provider);
            const isConnected = integration?.state === "connected";
            const isAvailable = cfg.available !== false;
            const isManaged = cfg.managed === true;
            const isConfigurable =
              isConnected && CONFIGURABLE_PROVIDERS.includes(provider);
            const integrationConfig = integration?.config as Record<string, unknown> | undefined;
            const selectedCount = integrationConfig?.selected_resources
              ? (integrationConfig.selected_resources as string[]).length
              : 0;
            return (
              <Card
                key={provider}
                className={cn("flex flex-col", !isAvailable && "opacity-50")}
                hover={isAvailable && !isManaged}
              >
                {/* Header */}
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "grid h-11 w-11 place-items-center rounded-xl text-xl",
                      cfg.color,
                      !isAvailable && "grayscale",
                    )}
                  >
                    {cfg.emoji}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "font-semibold",
                        !isAvailable && "text-zinc-500",
                      )}
                    >
                      {cfg.label}
                    </p>
                    <p className="truncate text-xs text-zinc-500">
                      {cfg.description}
                    </p>
                  </div>
                  {isConnected && (
                    <div className="grid h-6 w-6 place-items-center rounded-full bg-mint/15">
                      <Check size={14} className="text-mint" />
                    </div>
                  )}
                </div>

                {/* Status */}
                <div className="mt-3 flex items-center gap-2">
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full",
                      isConnected
                        ? "bg-mint"
                        : isAvailable
                          ? "bg-zinc-700"
                          : "bg-zinc-800",
                    )}
                  />
                  <span className="text-xs text-zinc-500">
                    {isConnected
                      ? "Connected"
                      : isAvailable
                        ? "Not connected"
                        : "Coming soon"}
                  </span>
                  {isConfigurable && selectedCount > 0 && (
                    <span className="text-xs text-mint">
                      · {selectedCount} {cfg.resourceLabel} tracked
                    </span>
                  )}
                  {integration?.last_synced_at && (
                    <span className="text-xs text-zinc-600">
                      · synced{" "}
                      {new Date(integration.last_synced_at).toLocaleDateString()}
                    </span>
                  )}
                </div>

                {/* Action */}
                <div className="mt-4 flex-1" />
                <div className="border-t border-line pt-4">
                  {isManaged ? (
                    <div className="w-full rounded-lg border border-line bg-panel/50 py-2 text-center text-xs text-zinc-500">
                      {isConnected ? "Active" : "Not connected"}
                    </div>
                  ) : isConnected ? (
                    <div className="flex gap-2">
                      {isConfigurable && (
                        <button
                          onClick={() => openConfig(provider)}
                          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line py-2 text-sm text-zinc-400 transition hover:border-mint/50 hover:text-mint"
                        >
                          <Settings2 size={14} /> Configure
                        </button>
                      )}
                      <button
                        onClick={() => disconnect(integration!.provider)}
                        className="rounded-lg border border-line px-3 py-2 text-sm text-zinc-400 transition hover:border-rose-500/50 hover:text-rose-400"
                      >
                        Disconnect
                      </button>
                    </div>
                  ) : isAvailable ? (
                    <button
                      onClick={() => connect(provider)}
                      className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-mint py-2 text-sm font-medium text-canvas transition hover:brightness-110"
                    >
                      <Plug size={14} /> Connect
                    </button>
                  ) : (
                    <button
                      disabled
                      className="w-full cursor-not-allowed rounded-lg border border-line py-2 text-sm text-zinc-600"
                    >
                      Coming soon
                    </button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Resource selection modal */}
      {configProvider && cfg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-line bg-panel p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "grid h-10 w-10 place-items-center rounded-xl text-lg",
                    cfg.color,
                  )}
                >
                  {cfg.emoji}
                </div>
                <div>
                  <h3 className="font-semibold">Select {cfg.resourceLabel}</h3>
                  <p className="text-xs text-zinc-500">
                    Choose which {cfg.resourceLabel} the agent should track
                  </p>
                </div>
              </div>
              <button
                onClick={() => setConfigProvider(null)}
                className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-canvas hover:text-zinc-300"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 max-h-80 overflow-y-auto rounded-lg border border-line">
              {loadingResources ? (
                <div className="p-4">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="mb-2 h-10" />
                  ))}
                </div>
              ) : resources.length === 0 ? (
                <div className="p-6 text-center text-sm text-zinc-500">
                  No {cfg.resourceLabel} found. Make sure the integration has
                  access to the right resources.
                </div>
              ) : (
                <div className="divide-y divide-line">
                  {resources.map((res) => {
                    const isSelected = selectedResources.includes(res.id);
                    return (
                      <button
                        key={res.id}
                        onClick={() => toggleResource(res.id)}
                        className={cn(
                          "flex w-full items-center gap-3 p-3 text-left transition",
                          isSelected ? "bg-mint/10" : "hover:bg-canvas/50",
                        )}
                      >
                        <div
                          className={cn(
                            "grid h-5 w-5 place-items-center rounded border",
                            isSelected
                              ? "border-mint bg-mint text-canvas"
                              : "border-zinc-600",
                          )}
                        >
                          {isSelected && <Check size={12} />}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">
                            {res.name}
                          </p>
                          {res.key && (
                            <p className="text-xs text-zinc-500">{res.key}</p>
                          )}
                          {res.default_branch && (
                            <p className="text-xs text-zinc-500">
                              branch: {res.default_branch}
                            </p>
                          )}
                        </div>
                        {res.num_members !== undefined && (
                          <span className="text-xs text-zinc-500">
                            {res.num_members} members
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-zinc-500">
                {selectedResources.length} selected
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setConfigProvider(null)}
                  className="rounded-lg border border-line px-4 py-2 text-sm text-zinc-400 transition hover:bg-canvas"
                >
                  Cancel
                </button>
                <button
                  onClick={saveConfig}
                  disabled={savingConfig}
                  className="rounded-lg bg-mint px-4 py-2 text-sm font-medium text-canvas transition hover:brightness-110 disabled:opacity-50"
                >
                  {savingConfig ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
