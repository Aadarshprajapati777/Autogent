"use client";

import { AuthProvider } from "@/components/auth-provider";
import { WorkspaceProvider } from "@/components/workspace-provider";
import { AuthGuard } from "@/components/auth-guard";
import { AppShell } from "@/components/app-shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <WorkspaceProvider>
        <AuthGuard>
          <AppShell>{children}</AppShell>
        </AuthGuard>
      </WorkspaceProvider>
    </AuthProvider>
  );
}
