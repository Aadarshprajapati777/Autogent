import Link from "next/link";
import {
  Sparkles,
  Brain,
  CalendarDays,
  CheckSquare,
  ShieldCheck,
  Users,
  Zap,
  Bot,
  MessageSquare,
  GitBranch,
  ArrowRight,
  Check,
  Cloud,
  Database,
  Workflow,
  Clock,
  TrendingUp,
} from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      {/* ─────────────────── Nav ─────────────────── */}
      <nav className="sticky top-0 z-50 border-b border-line/50 bg-canvas/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2.5 font-semibold">
            <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-mint font-black text-canvas">
              A
            </span>
            Autogent
          </Link>
          <div className="hidden items-center gap-8 md:flex">
            <a href="#features" className="text-sm text-zinc-400 transition hover:text-zinc-100">
              Features
            </a>
            <a href="#integrations" className="text-sm text-zinc-400 transition hover:text-zinc-100">
              Integrations
            </a>
            <a href="#how-it-works" className="text-sm text-zinc-400 transition hover:text-zinc-100">
              How it works
            </a>
            <a href="#stack" className="text-sm text-zinc-400 transition hover:text-zinc-100">
              Stack
            </a>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="text-sm text-zinc-400 transition hover:text-zinc-100"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="rounded-lg bg-mint px-4 py-2 text-sm font-medium text-canvas transition hover:brightness-110"
            >
              Get started
            </Link>
          </div>
        </div>
      </nav>

      {/* ─────────────────── Hero ─────────────────── */}
      <section className="grid-bg relative overflow-hidden border-b border-line">
        <div className="absolute left-1/2 top-0 h-[400px] w-[600px] -translate-x-1/2 rounded-full bg-mint/10 blur-[120px]" />
        <div className="relative mx-auto max-w-6xl px-6 py-24 lg:py-32">
          <div className="flex flex-col items-center text-center">
            <div className="flex items-center gap-2 rounded-full border border-line bg-panel px-4 py-1.5 text-xs text-zinc-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-mint" />
              Powered by Gemini 3.5 Flash + Google ADK
            </div>
            <h1 className="mt-8 max-w-4xl text-5xl font-bold leading-[1.05] tracking-tight lg:text-7xl">
              The AI project manager
              <br />
              <span className="bg-gradient-to-r from-mint via-emerald-300 to-mint bg-clip-text text-transparent">
                that actually does work
              </span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg text-zinc-400">
              Autogent doesn&apos;t just chat. It joins your meetings, tracks tasks, checks in with
              your team on Slack, escalates risks, and manages your projects — autonomously, 24/7.
            </p>
            <div className="mt-10 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/signup"
                className="group flex items-center gap-2 rounded-xl bg-mint px-6 py-3.5 font-semibold text-canvas transition hover:brightness-110"
              >
                Start free
                <ArrowRight
                  size={18}
                  className="transition-transform group-hover:translate-x-0.5"
                />
              </Link>
              <a
                href="#how-it-works"
                className="flex items-center gap-2 rounded-xl border border-line bg-panel px-6 py-3.5 font-semibold text-zinc-300 transition hover:border-mint/30"
              >
                See how it works
              </a>
            </div>
            <div className="mt-12 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-zinc-600">
              <span className="flex items-center gap-1.5">
                <Check size={14} className="text-mint" /> No credit card required
              </span>
              <span className="flex items-center gap-1.5">
                <Check size={14} className="text-mint" /> Set up in 2 minutes
              </span>
              <span className="flex items-center gap-1.5">
                <Check size={14} className="text-mint" /> Runs on Google Cloud
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────── Stats strip ─────────────────── */}
      <section className="border-b border-line bg-panel/30">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-px px-6 lg:grid-cols-4">
          {[
            { label: "Autonomous tools", value: "21+" },
            { label: "Integrations", value: "8" },
            { label: "Agent cycle", value: "30 min" },
            { label: "LLM provider", value: "Gemini 3.5" },
          ].map((s) => (
            <div key={s.label} className="py-8 text-center">
              <p className="text-3xl font-bold text-mint">{s.value}</p>
              <p className="mt-1 text-sm text-zinc-500">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ─────────────────── Features ─────────────────── */}
      <section id="features" className="border-b border-line py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-wide text-mint">
              Features
            </p>
            <h2 className="mt-3 text-4xl font-bold tracking-tight">
              Everything a PM does — automated
            </h2>
            <p className="mt-4 text-lg text-zinc-400">
              Autogent combines an autonomous agent loop with real integrations to manage your
              engineering team like a dedicated project manager would.
            </p>
          </div>

          <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            <FeatureCard
              icon={Bot}
              title="Autonomous agent"
              description="A ReAct-style agent powered by Google ADK that reasons, calls tools, and takes real actions — not just generates text."
              accent="mint"
            />
            <FeatureCard
              icon={CalendarDays}
              title="Meeting intelligence"
              description="Recall.ai bot joins your meetings, transcribes them, and automatically extracts action items, decisions, and commitments."
              accent="blue"
            />
            <FeatureCard
              icon={CheckSquare}
              title="Task management"
              description="Tasks are created from meetings and conversations, assigned to owners, tracked through states, and escalated when overdue."
              accent="violet"
            />
            <FeatureCard
              icon={Brain}
              title="Persistent memory"
              description="pgvector-backed memory stores facts, people, projects, and decisions. The agent remembers everything across sessions."
              accent="amber"
            />
            <FeatureCard
              icon={ShieldCheck}
              title="Approval workflow"
              description="High-impact actions go through an approval queue. You stay in control while the agent handles the busywork."
              accent="rose"
            />
            <FeatureCard
              icon={Users}
              title="Team awareness"
              description="The agent builds profiles of your team — skills, timezones, workloads — and uses them to make smarter decisions."
              accent="mint"
            />
          </div>
        </div>
      </section>

      {/* ─────────────────── How it works ─────────────────── */}
      <section id="how-it-works" className="border-b border-line bg-panel/20 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-wide text-mint">
              How it works
            </p>
            <h2 className="mt-3 text-4xl font-bold tracking-tight">
              From signup to autonomous PM in 3 steps
            </h2>
          </div>

          <div className="mt-12 grid gap-6 md:grid-cols-3">
            <StepCard
              step="01"
              icon={MessageSquare}
              title="Connect your tools"
              description="Link Slack, GitHub, Jira, Google Calendar, and more. The agent uses these integrations to act on your behalf."
            />
            <StepCard
              step="02"
              icon={Workflow}
              title="The agent goes to work"
              description="Every 30 minutes, the agent runs an autonomous cycle: checks in with the team, reviews tasks, updates memory, and escalates risks."
            />
            <StepCard
              step="03"
              icon={TrendingUp}
              title="You stay informed"
              description="Get Slack notifications for escalations, review task approvals in the dashboard, and ask the agent anything in chat."
            />
          </div>

          {/* Agent cycle visualization */}
          <div className="mt-12 rounded-2xl border border-line bg-canvas p-6 lg:p-8">
            <p className="text-sm font-semibold text-zinc-400">The autonomous PM cycle</p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              {[
                "Check Slack for updates",
                "Review task statuses",
                "Detect blocked/overdue items",
                "Check in with team members",
                "Update memory & facts",
                "Escalate risks to founders",
                "Create task candidates",
              ].map((step, i) => (
                <div key={step} className="flex items-center gap-3">
                  <span className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm text-zinc-300">
                    <span className="grid h-5 w-5 place-items-center rounded-md bg-mint/15 text-[10px] font-bold text-mint">
                      {i + 1}
                    </span>
                    {step}
                  </span>
                  {i < 6 && <ArrowRight size={14} className="text-zinc-700" />}
                </div>
              ))}
              <span className="flex items-center gap-1.5 text-xs text-zinc-600">
                <Clock size={12} /> repeats every 30 min
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────── Integrations ─────────────────── */}
      <section id="integrations" className="border-b border-line py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-wide text-mint">
              Integrations
            </p>
            <h2 className="mt-3 text-4xl font-bold tracking-tight">
              Connects to the tools your team already uses
            </h2>
            <p className="mt-4 text-lg text-zinc-400">
              Real OAuth integrations — not mock demos. The agent reads, writes, and acts through
              these connections.
            </p>
          </div>

          <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <IntegrationCard emoji="💬" name="Slack" desc="DMs, channels, check-ins" color="bg-purple-500" />
            <IntegrationCard emoji="🐙" name="GitHub" desc="Commits, PRs, issues" color="bg-zinc-700" />
            <IntegrationCard emoji="📋" name="Jira" desc="Tickets & sprints" color="bg-blue-600" />
            <IntegrationCard emoji="📐" name="Linear" desc="Issues & projects" color="bg-indigo-600" />
            <IntegrationCard emoji="📅" name="Google Calendar" desc="Events & scheduling" color="bg-blue-500" />
            <IntegrationCard emoji="📆" name="Microsoft Calendar" desc="Outlook events" color="bg-blue-700" />
            <IntegrationCard emoji="📝" name="Notion" desc="Docs & wikis" color="bg-zinc-800" />
            <IntegrationCard emoji="🎥" name="Recall.ai" desc="Meeting transcription" color="bg-orange-500" />
          </div>
        </div>
      </section>

      {/* ─────────────────── Stack ─────────────────── */}
      <section id="stack" className="border-b border-line bg-panel/20 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-wide text-mint">
              Built on Google Cloud
            </p>
            <h2 className="mt-3 text-4xl font-bold tracking-tight">
              Production-grade architecture
            </h2>
            <p className="mt-4 text-lg text-zinc-400">
              Autogent is built with the All Things Agentic stack — Google ADK, Gemini 3.5 Flash,
              and Cloud Run.
            </p>
          </div>

          <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            <StackCard
              icon={Sparkles}
              title="Gemini 3.5 Flash"
              subtitle="LLM Provider"
              description="Google&apos;s latest multimodal model powers reasoning, tool selection, and natural language understanding."
            />
            <StackCard
              icon={Bot}
              title="Google ADK"
              subtitle="Agent Framework"
              description="The Agent Development Kit provides the LlmAgent, Runner, and session management for the ReAct loop."
            />
            <StackCard
              icon={Cloud}
              title="Cloud Run"
              subtitle="Infrastructure"
              description="Backend and frontend deploy as containerized services on Google Cloud Run with autoscaling."
            />
            <StackCard
              icon={Database}
              title="Cloud SQL + pgvector"
              subtitle="Database"
              description="Managed PostgreSQL with pgvector for semantic memory search and embeddings."
            />
          </div>

          {/* Architecture flow */}
          <div className="mt-12 rounded-2xl border border-line bg-canvas p-6 lg:p-8">
            <p className="text-sm font-semibold text-zinc-400">Request flow</p>
            <div className="mt-6 flex flex-wrap items-center gap-3 text-sm">
              {[
                { label: "Next.js Frontend", icon: MessageSquare, color: "text-mint" },
                { label: "FastAPI", icon: Zap, color: "text-amber-400" },
                { label: "ADK Agent", icon: Bot, color: "text-blue-400" },
                { label: "Gemini 3.5", icon: Sparkles, color: "text-violet-400" },
                { label: "21 Tools", icon: GitBranch, color: "text-mint" },
                { label: "PostgreSQL", icon: Database, color: "text-rose-400" },
              ].map((node, i) => (
                <div key={node.label} className="flex items-center gap-3">
                  <span className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
                    <node.icon size={16} className={node.color} />
                    {node.label}
                  </span>
                  {i < 5 && <ArrowRight size={14} className="text-zinc-700" />}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────── CTA ─────────────────── */}
      <section className="border-b border-line py-24">
        <div className="mx-auto max-w-4xl px-6 text-center">
          <div className="relative overflow-hidden rounded-3xl border border-mint/20 bg-gradient-to-b from-mint/5 to-transparent p-12 lg:p-16">
            <div className="absolute left-1/2 top-0 h-[200px] w-[400px] -translate-x-1/2 rounded-full bg-mint/10 blur-[100px]" />
            <div className="relative">
              <h2 className="text-4xl font-bold tracking-tight lg:text-5xl">
                Stop managing. Start shipping.
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-lg text-zinc-400">
                Let Autogent handle the standups, check-ins, and task tracking. Your team focuses
                on what matters — building.
              </p>
              <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <Link
                  href="/signup"
                  className="group flex items-center gap-2 rounded-xl bg-mint px-6 py-3.5 font-semibold text-canvas transition hover:brightness-110"
                >
                  Get started free
                  <ArrowRight
                    size={18}
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </Link>
                <Link
                  href="/login"
                  className="rounded-xl border border-line bg-panel px-6 py-3.5 font-semibold text-zinc-300 transition hover:border-mint/30"
                >
                  Sign in
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────── Footer ─────────────────── */}
      <footer className="py-12">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 sm:flex-row">
          <div className="flex items-center gap-2.5 text-sm text-zinc-500">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-mint font-black text-canvas">
              A
            </span>
            Autogent — Autonomous AI Project Manager
          </div>
          <p className="text-xs text-zinc-600">
            Built for the All Things Agentic Hackathon · Powered by Google Cloud
          </p>
        </div>
      </footer>
    </main>
  );
}

/* ─────────────────── Sub-components ─────────────────── */

function FeatureCard({
  icon: Icon,
  title,
  description,
  accent,
}: {
  icon: typeof Sparkles;
  title: string;
  description: string;
  accent: "mint" | "blue" | "violet" | "amber" | "rose";
}) {
  const colorMap: Record<string, string> = {
    mint: "text-mint bg-mint/10",
    blue: "text-blue-400 bg-blue-500/10",
    violet: "text-violet-400 bg-violet-500/10",
    amber: "text-amber-400 bg-amber-500/10",
    rose: "text-rose-400 bg-rose-500/10",
  };
  return (
    <div className="group rounded-2xl border border-line bg-panel p-6 transition hover:border-white/10 hover:bg-white/[.02]">
      <div className={`grid h-12 w-12 place-items-center rounded-xl ${colorMap[accent]}`}>
        <Icon size={24} />
      </div>
      <h3 className="mt-5 text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-zinc-400">{description}</p>
    </div>
  );
}

function StepCard({
  step,
  icon: Icon,
  title,
  description,
}: {
  step: string;
  icon: typeof Sparkles;
  title: string;
  description: string;
}) {
  return (
    <div className="relative rounded-2xl border border-line bg-panel p-6">
      <span className="absolute right-6 top-6 text-5xl font-black text-white/5">{step}</span>
      <div className="grid h-12 w-12 place-items-center rounded-xl bg-mint/10">
        <Icon size={24} className="text-mint" />
      </div>
      <h3 className="mt-5 text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-zinc-400">{description}</p>
    </div>
  );
}

function IntegrationCard({
  emoji,
  name,
  desc,
  color,
}: {
  emoji: string;
  name: string;
  desc: string;
  color: string;
}) {
  return (
    <div className="group flex items-center gap-3 rounded-xl border border-line bg-panel p-4 transition hover:border-white/10 hover:bg-white/[.02]">
      <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-xl text-2xl ${color}`}>
        {emoji}
      </div>
      <div className="min-w-0">
        <p className="font-semibold">{name}</p>
        <p className="truncate text-xs text-zinc-500">{desc}</p>
      </div>
    </div>
  );
}

function StackCard({
  icon: Icon,
  title,
  subtitle,
  description,
}: {
  icon: typeof Sparkles;
  title: string;
  subtitle: string;
  description: string;
}) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-6">
      <div className="grid h-12 w-12 place-items-center rounded-xl bg-mint/10">
        <Icon size={24} className="text-mint" />
      </div>
      <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-zinc-600">
        {subtitle}
      </p>
      <h3 className="mt-1 text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-zinc-400">{description}</p>
    </div>
  );
}
