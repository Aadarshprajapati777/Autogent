"use client";

import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import { type ReactNode } from "react";

/* ──────────────────────────── Badge ──────────────────────────── */

const badgeColors: Record<string, string> = {
  mint: "bg-mint/15 text-mint border-mint/20",
  blue: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  amber: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  rose: "bg-rose-500/15 text-rose-400 border-rose-500/20",
  violet: "bg-violet-500/15 text-violet-400 border-violet-500/20",
  zinc: "bg-zinc-500/15 text-zinc-400 border-zinc-500/20",
};

export function Badge({
  children,
  color = "zinc",
  className,
}: {
  children: ReactNode;
  color?: keyof typeof badgeColors;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
        badgeColors[color],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ──────────────────────────── Card ──────────────────────────── */

export function Card({
  children,
  className,
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  hover?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-panel p-5",
        hover && "transition hover:border-white/10 hover:bg-white/[.02]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/* ──────────────────────── ProgressBar ──────────────────────── */

export function ProgressBar({
  value,
  color = "mint",
  className,
}: {
  value: number; // 0–1
  color?: "mint" | "blue" | "amber" | "rose" | "violet";
  className?: string;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const colorMap: Record<string, string> = {
    mint: "bg-mint",
    blue: "bg-blue-500",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
    violet: "bg-violet-500",
  };
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-white/5", className)}>
      <div
        className={cn("h-full rounded-full transition-all duration-500", colorMap[color])}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/* ──────────────────────── EmptyState ──────────────────────── */

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line bg-panel/50 p-12 text-center">
      <div className="grid h-14 w-14 place-items-center rounded-2xl bg-white/[.03]">
        <Icon size={24} className="text-zinc-600" />
      </div>
      <p className="mt-4 font-medium text-zinc-400">{title}</p>
      {description && (
        <p className="mt-1 max-w-xs text-sm text-zinc-600">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ──────────────────────── Skeleton ──────────────────────── */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-lg bg-white/5", className)} />;
}

/* ──────────────────────── PageHeader ──────────────────────── */

export function PageHeader({
  icon: Icon,
  title,
  subtitle,
  action,
}: {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-mint/10">
            <Icon size={18} className="text-mint" />
          </div>
          <h1 className="text-2xl font-bold">{title}</h1>
        </div>
        {subtitle && (
          <p className="mt-2 text-sm text-zinc-500">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

/* ──────────────────────── StatCard ──────────────────────── */

export function StatCard({
  icon: Icon,
  label,
  value,
  sublabel,
  accent = "mint",
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  sublabel?: string;
  accent?: "mint" | "blue" | "amber" | "rose" | "violet";
}) {
  const colorMap: Record<string, string> = {
    mint: "text-mint bg-mint/10",
    blue: "text-blue-400 bg-blue-500/10",
    amber: "text-amber-400 bg-amber-500/10",
    rose: "text-rose-400 bg-rose-500/10",
    violet: "text-violet-400 bg-violet-500/10",
  };
  return (
    <Card className="relative overflow-hidden">
      <div className="flex items-center justify-between">
        <div className={cn("grid h-10 w-10 place-items-center rounded-xl", colorMap[accent])}>
          <Icon size={20} />
        </div>
      </div>
      <p className="mt-4 text-3xl font-bold tracking-tight">{value}</p>
      <p className="text-sm text-zinc-500">{label}</p>
      {sublabel && (
        <p className="mt-0.5 text-xs text-zinc-600">{sublabel}</p>
      )}
    </Card>
  );
}

/* ──────────────────────── Avatar ──────────────────────── */

const avatarGradients = [
  "from-violet-500 to-fuchsia-400",
  "from-blue-500 to-cyan-400",
  "from-amber-500 to-orange-400",
  "from-rose-500 to-pink-400",
  "from-emerald-500 to-mint",
  "from-indigo-500 to-violet-400",
];

export function Avatar({
  name,
  size = 40,
  className,
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const initials = name
    .split(" ")
    .map((x) => x[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const idx = name.charCodeAt(0) % avatarGradients.length;
  return (
    <div
      className={cn(
        "grid shrink-0 place-items-center rounded-full bg-gradient-to-br font-bold text-white",
        avatarGradients[idx],
        className,
      )}
      style={{ width: size, height: size, fontSize: size * 0.35 }}
    >
      {initials}
    </div>
  );
}

/* ──────────────────────── SectionTitle ──────────────────────── */

export function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="font-semibold">{children}</h2>
      {action}
    </div>
  );
}
