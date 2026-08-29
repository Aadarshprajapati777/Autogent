"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import type { User, Workspace } from "@/lib/types";

type WorkspaceState = {
  me: User | null;
  workspace: Workspace | null;
  workspaces: Workspace[];
  selectWorkspace: (id: string) => void;
  loading: boolean;
};

const WorkspaceContext = createContext<WorkspaceState | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [me, setMe] = useState<User | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      setMe(null);
      setWorkspace(null);
      setLoading(false);
      return;
    }
    setMe(user);
    const workspaces = user.workspaces ?? [];
    const storedId =
      typeof window !== "undefined"
        ? window.localStorage.getItem("autogent_workspace_id")
        : null;
    const active =
      workspaces.find((w) => w.id === storedId) ?? workspaces[0] ?? null;
    setWorkspace(active);
    setLoading(false);
  }, [user, authLoading]);

  const selectWorkspace = useCallback((id: string) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("autogent_workspace_id", id);
    }
    const ws = me?.workspaces?.find((w) => w.id === id) ?? null;
    setWorkspace(ws);
  }, [me]);

  return (
    <WorkspaceContext.Provider
      value={{
        me,
        workspace,
        workspaces: me?.workspaces ?? [],
        selectWorkspace,
        loading,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("WorkspaceProvider missing");
  return ctx;
}
