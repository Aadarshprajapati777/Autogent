"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Person } from "@/lib/types";
import { Users } from "lucide-react";

export default function PeoplePage() {
  const { workspace } = useWorkspace();
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; people: Person[] }>(
      `/memory/people?workspace_id=${workspace.id}`,
    )
      .then((r) => setPeople(r.people))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  if (!workspace) return null;

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <Users className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">People</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Profiles the agent has built from interactions.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {loading ? (
          <div className="skeleton h-32 rounded-xl bg-white/5" />
        ) : people.length === 0 ? (
          <div className="col-span-full rounded-xl border border-line bg-panel p-8 text-center">
            <p className="text-sm text-zinc-600">No people yet</p>
            <p className="mt-1 text-xs text-zinc-700">
              The agent creates profiles as it learns about your team.
            </p>
          </div>
        ) : (
          people.map((p) => (
            <div
              key={p.person_id ?? p.name}
              className="rounded-xl border border-line bg-panel p-5"
            >
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-full bg-gradient-to-br from-violet-500 to-orange-300 text-sm font-bold">
                  {p.name.split(" ").map((x) => x[0]).join("").slice(0, 2)}
                </div>
                <div className="min-w-0">
                  <p className="truncate font-medium">{p.name}</p>
                  <p className="truncate text-xs text-zinc-500">{p.role}</p>
                </div>
              </div>
              {p.title && (
                <p className="mt-3 text-xs text-zinc-500">{p.title}</p>
              )}
              {p.skills && p.skills.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {p.skills.map((s) => (
                    <span
                      key={s}
                      className="rounded bg-mint/10 px-1.5 py-0.5 text-xs text-mint/70"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
