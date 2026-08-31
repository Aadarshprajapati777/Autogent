export interface Workspace {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  workspaces?: Workspace[];
}

export interface Fact {
  fact_id: string;
  subject: string;
  predicate: string;
  value: string;
  fact_kind: string;
  topics: string[];
  project: string | null;
  speaker: string | null;
  confidence: number;
  created_at: string | null;
}

export interface Person {
  person_id?: string;
  name: string;
  role: string;
  title: string | null;
  skills: string[];
  languages?: string[];
  is_technical: boolean;
  experience_years?: number | null;
  availability_hours_per_week?: number | null;
  timezone: string | null;
  interests?: string[];
  career_goals?: string | null;
  resume_summary?: string | null;
}

export interface Task {
  id: string;
  title: string;
  state: string;
  priority: number;
  due_at: string | null;
  owner_id: string | null;
  last_activity_at: string | null;
}

export interface ChatMessage {
  role: string;
  text: string;
  actions?: ActionTrace[];
  created_at?: string;
}

export interface ActionTrace {
  tool: string;
  arguments: Record<string, unknown>;
  result: string | null;
  error: string | null;
}

export interface AgentResponse {
  answer: string;
  actions: ActionTrace[];
  error: string | null;
}

export interface Integration {
  id: string | null;
  provider: string;
  state: string;
  external_account_id: string | null;
  last_synced_at: string | null;
  managed?: boolean;
  config?: Record<string, unknown>;
}

export interface IntegrationResource {
  id: string;
  name: string;
  type?: string;
  key?: string;
  default_branch?: string;
  num_members?: number;
  url?: string;
}

export interface Meeting {
  id: string;
  title: string | null;
  provider: string;
  status: string;
  scheduled_at: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface TranscriptChunk {
  id: string;
  speaker: string;
  text: string;
  started_ms: number | null;
  ended_ms: number | null;
}

export interface MeetingExtraction {
  status: string | null;
  summary: string | null;
  confidence: number | null;
  decisions: { title: string; rationale: string | null; confidence: number }[];
  tasks: {
    ref: string;
    title: string;
    description: string | null;
    owner_name: string | null;
    state: string;
    confidence: number;
    due_at: string | null;
  }[];
}
