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
  is_technical: boolean;
  timezone: string | null;
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
  id: string;
  provider: string;
  state: string;
  external_account_id: string | null;
  last_synced_at: string | null;
}
