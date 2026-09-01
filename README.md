# Autogent

**An autonomous AI project manager that runs in the background — built on Gemini 3.5 Flash, Google ADK, and Google Cloud.**

Autogent doesn't wait for you to ask. It onboards engineers, runs check-ins, tracks work, ingests meetings, monitors for risks, and escalates issues — all on its own, every 30 minutes. When you do message it, it uses a tool-calling agent loop to search memory, look up people and projects, check Slack, create tasks in Jira or Linear, and take real action across your integrations.

> Built for the **All Things Agentic Hackathon** — Track: **The Taskmaster**.
>
> **Live demo:** [https://autogent-frontend-802301600867.us-central1.run.app](https://autogent-frontend-802301600867.us-central1.run.app)
>
> **Backend API:** [https://autogent-backend-802301600867.us-central1.run.app](https://autogent-backend-802301600867.us-central1.run.app)

---

## Table of Contents

- [The Problem](#the-problem)
- [What Autogent Does](#what-autogent-does)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Features Walkthrough](#features-walkthrough)
- [Agent Tools](#agent-tools)
- [Deployment](#deployment)
- [Local Development](#local-development)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Findings & Learnings](#findings--learnings)

---

## The Problem

Engineering teams waste hours on project management overhead — status updates, check-ins, meeting notes, task tracking, bottleneck identification. Founders and engineering managers become human routers: asking "what's the status?", writing Jira tickets, chasing blocked work, and trying to remember who said what in which meeting.

Existing tools are passive. Jira doesn't tell you it's stuck. Slack doesn't extract decisions. Meeting transcripts don't become assigned tasks. Nobody proactively checks in on the engineer who's been silent for three days.

## What Autogent Does

Autogent is an AI project manager that operates autonomously across your existing tools:

| Capability | How it works |
|---|---|
| **Autonomous onboarding** | When Slack is connected, the agent detects team members and runs a guided onboarding DM — asking about role, skills, and timezone. No human prompt needed. |
| **Proactive check-ins** | A background scheduler checks in with engineers on Slack every 30 minutes, captures updates, extracts facts into memory, and updates task status. |
| **Meeting ingestion** | A Recall.ai bot joins meetings, transcribes them, and Gemini extracts decisions, action items, risks, and commitments — grounded in exact transcript evidence. |
| **Unified people graph** | Syncs and merges identities across Slack, GitHub, Jira, and Linear into a single person record — so the agent knows that `@sudhir` on Slack is the same person as `sudhirKsah` on GitHub and can assign tasks to the right account on the right platform. |
| **Cross-platform task creation** | When a decision is made in a meeting, the agent creates a Jira issue or Linear ticket and assigns it to the correct person using their provider-specific ID. |
| **Long-term memory** | Every conversation, meeting, and check-in is distilled into atomic facts with semantic embeddings. The agent searches this memory to answer questions and make informed decisions. |
| **Analytics & bottleneck detection** | A real-time dashboard shows project progress, team skills, reliability scores, blocked tasks, overdue work, and risk alerts. Ask the agent "where are we stuck?" and it queries the database to answer. |
| **Risk monitoring** | Detects overdue tasks, silent engineers, and blockers — then escalates to founders when issues are serious. |

### What makes it autonomous

The backend runs a **background scheduler** that fires every 30 minutes and executes a full PM cycle — no human interaction required:

1. **Auto-onboarding** — onboard new team members who haven't been introduced
2. **Proactive check-ins** — DM engineers who are due for a status update
3. **Project kickoff** — break down newly described projects into concrete tasks
4. **State inference** — infer project health and person credibility from stored facts
5. **Monitoring** — detect overdue work, silence, blockers, and single points of failure
6. **Task re-scoring** — re-prioritize tasks based on new information
7. **Escalation** — escalate stale alerts per workspace rules
8. **Weekly reports** — generate and deliver weekly digests

When you do interact with the agent via chat, it has 36 tools at its disposal and decides which to call based on your question — whether that's searching memory, listing Jira issues, checking Slack messages, or pulling analytics data.

---

## Tech Stack

### Google Cloud & AI (hackathon requirements)

| Requirement | What we use |
|---|---|
| **Gemini 3.5+** | `gemini-3.5-flash` via Vertex AI — used for the agent's reasoning, meeting extraction, state inference, and all PM intelligence services |
| **Google Agent Framework** | **Google ADK** (Agent Development Kit) — the chat agent runs through ADK's `LlmAgent` + `Runner` with `FunctionTool`-wrapped tools |
| **Google Cloud infrastructure** | **Cloud Run** (backend + frontend), **Cloud SQL** for PostgreSQL, **Artifact Registry** for container images, **Vertex AI** for Gemini access |
| **GenAI SDK** | `google-genai` SDK v2.20.0 — used directly for structured JSON output in extraction, state inference, and reports |

### Full stack

- **Backend**: FastAPI, async SQLAlchemy, PostgreSQL + pgvector, Redis, Alembic
- **Agent**: Google ADK (`LlmAgent` + `Runner` + `FunctionTool`), 36 registered tools
- **LLM**: Gemini 3.5 Flash (primary, via Vertex AI), Cerebras (fallback)
- **Embeddings**: fastembed with `BAAI/bge-small-en-v1.5` (384-dim, pgvector)
- **Auth**: HS256 JWT (email/password with bcrypt), password reset via email
- **Frontend**: Next.js 16, React 19, Tailwind CSS v4, TypeScript
- **Meetings**: Recall.ai (bot joins, transcribes, webhooks trigger extraction)
- **Integrations**: Slack, GitHub, Jira, Linear, Recall.ai

---

## Architecture

```mermaid
graph TB
    subgraph User["User"]
        UI[Next.js Frontend<br/>Cloud Run]
    end

    subgraph Slack["Slack Workspace"]
        SLACK[Slack API<br/>DMs, channels, events]
    end

    subgraph External["External Integrations"]
        GH[GitHub API]
        JIRA[Jira API]
        LINEAR[Linear API]
        RECALL[Recall.ai<br/>Meeting bot]
    end

    subgraph Backend["Autogent Backend — FastAPI on Cloud Run"]
        direction TB

        subgraph API["API Layer"]
            AGENT[Agent Chat<br/>/api/v1/agent/chat]
            AUTH[Auth<br/>signup, login, reset]
            INT[Integrations<br/>OAuth callbacks]
            MTG[Meetings<br/>list, detail, transcripts]
            AN[Analytics<br/>dashboard data]
            WB[Webhooks<br/>Recall.ai events]
        end

        subgraph AgentCore["Agent Layer — Google ADK"]
            ADK[ADK LlmAgent<br/>gemini-3.5-flash]
            TOOLS[36 Tools<br/>memory, people, tasks,<br/>slack, github, jira, linear,<br/>meetings, analytics]
        end

        subgraph Services["PM Services"]
            SYNC[People Sync<br/>unified identity graph]
            EXT[Meeting Extraction<br/>decisions, tasks, risks]
            ONBOARD[Slack Onboarding<br/>auto-DM new members]
            SCHED[Scheduler<br/>30-min autonomous cycle]
        end
    end

    subgraph Data["Data Layer"]
        DB[(Cloud SQL<br/>PostgreSQL 17)]
        PGV[pgvector<br/>384-dim embeddings]
    end

    subgraph GCP["Google Cloud"]
        CR[Cloud Run]
        CS[Cloud SQL]
        VA[Vertex AI<br/>Gemini 3.5 Flash]
        AR[Artifact Registry]
    end

    UI -->|REST API| AGENT
    UI -->|REST API| AUTH
    UI -->|REST API| INT
    UI -->|REST API| MTG
    UI -->|REST API| AN

    SLACK -->|OAuth + Events| INT
    GH -->|OAuth| INT
    JIRA -->|OAuth| INT
    LINEAR -->|OAuth| INT
    RECALL -->|Webhook| WB

    AGENT --> ADK
    ADK --> TOOLS
    ADK -->|function calling| VA

    TOOLS -->|read/write| DB
    INT --> SYNC
    SYNC --> DB
    WB --> EXT
    EXT -->|Gemini structured output| VA
    EXT --> DB
    SCHED --> ONBOARD
    SCHED -->|check-ins| SLACK
    ONBOARD -->|DMs| SLACK
    TOOLS -->|create issues| JIRA
    TOOLS -->|create issues| LINEAR
    TOOLS -->|send messages| SLACK
    TOOLS -->|create issues| GH

    PGV --> DB
    CR --> AR
    CR --> CS
```

### How the agent works

```
User message: "How are our projects going? Where are we stuck?"
    │
    ▼
POST /api/v1/agent/chat
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  ADK Runner (Google Agent Development Kit)                │
│                                                           │
│  1. LlmAgent (model=gemini-3.5-flash)                     │
│     receives: system instruction + conversation history   │
│                                                           │
│  2. Gemini decides which tools to call:                   │
│     → analytics_overview()                                │
│     → analytics_bottlenecks()                             │
│     → people_list()                                       │
│                                                           │
│  3. ADK executes each FunctionTool → Autogent tool        │
│     (queries Cloud SQL, returns structured data)          │
│                                                           │
│  4. Tool results fed back to Gemini                       │
│                                                           │
│  5. Gemini synthesizes a natural-language answer           │
│     with specific names, numbers, and project status      │
└──────────────────────────────────────────────────────────┘
    │
    ▼
AgentResponse { answer, actions[], error }
```

The agent's 36 tools span memory, people, tasks, Slack, GitHub, Jira, Linear, meetings, and analytics. The system prompt instructs it to use tools rather than guess — it won't claim a task is overdue without calling `analytics_bottlenecks` first.

### Meeting ingestion pipeline

```
Recall.ai bot joins meeting
    │
    ▼
Webhook → /api/v1/recall/webhooks
    │
    ├── bot.joined → update meeting status
    ├── bot.transcript.completed → fetch transcript chunks
    │
    ▼
Gemini structured extraction (grounded in transcript evidence)
    │
    ├── Summary
    ├── Decisions (with confidence)
    ├── Action items → task candidates
    │   ├── Owner resolved via people graph
    │   ├── High confidence (≥0.85) → auto-materialized as tasks
    │   └── Lower confidence → pending approval
    ├── Risks
    └── Questions
    │
    ▼
Frontend: /meetings/[id] shows transcript, summary, decisions, tasks
```

Every extracted item references exact transcript chunk IDs. The model is instructed not to invent owners, deadlines, or risks — everything must be grounded in what was actually said.

---

## Features Walkthrough

### 1. Landing Page & Authentication

A professional public landing page showcases the product's features, integrations, and value proposition. Full authentication flow includes signup, login, forgot password (with email reset), and error pages — all with a polished dark UI.

### 2. Dashboard

Overview cards showing active projects, team size, open tasks, alerts, and meetings. Quick access to recent activity and agent actions.

### 3. Agent Chat

The core interaction point. Chat with the agent at `/agent` and it will:
- Answer questions using real database queries (not hallucinated)
- Create tasks in Jira, Linear, or GitHub based on your conversation
- Send Slack messages to team members
- Search memory for past decisions and commitments
- Pull analytics on project health, bottlenecks, and team skills

Each response shows the tool calls it made, so you can see the agent's reasoning chain.

### 4. Meetings

- Schedule a Recall.ai bot to join any meeting
- View full transcripts with speaker names and timestamps
- See AI-extracted summary, decisions, action items, risks, and questions
- Approve or reject extracted task candidates
- High-confidence tasks are auto-materialized; lower-confidence ones await approval

### 5. People

- Unified people graph merging identities across Slack, GitHub, Jira, and Linear
- Each person shows their role, skills, timezone, integration links, and onboarding status
- The agent uses this graph to resolve "assign this to Sudhir" into the correct Jira account ID or Linear user ID

### 6. Tasks

- All tasks created by the agent, from meetings, or manually
- Track state: open, in progress, blocked, completed, overdue
- Priority, deadlines, and execution scores
- Comments and activity history

### 7. Approvals

- Task candidates extracted from meetings with confidence < 0.85 await your approval
- Review the evidence (transcript quotes) before approving or rejecting

### 8. Analytics

A visual dashboard showing:
- **Completion rate**, team size, open alerts, meetings this week
- **Task velocity** chart (created vs completed over 14 days)
- **Task status breakdown** (completed, in progress, open, blocked, overdue)
- **Project progress cards** with health badges (on track, at risk, blocked)
- **Team skills** — who is good at what, with skill bars
- **Reliability leaderboard** — ranked team members by commitment completion rate
- **Bottlenecks** — overdue and blocked tasks highlighted
- **Risk alerts** — active alerts with severity levels
- **Integration coverage** — how many team members are linked to each platform
- **Knowledge activity** — facts learned per day chart

### 9. Memory

- Searchable fact store with semantic + keyword search
- Facts typed by kind: decision, commitment, blocker, skill, status update, risk, etc.
- Every fact has provenance (which meeting or conversation it came from)

### 10. Integrations

- Connect Slack, GitHub, Jira, and Linear via OAuth
- Each integration shows connection status and available actions
- Disconnect/reconnect triggers people sync and onboarding (for Slack)

### 11. Settings

- Configure escalation rules
- Set monitoring schedule
- Manage workspace preferences

---

## Agent Tools

The ADK agent has 36 tools at its disposal:

| Category | Tools |
|---|---|
| **Analytics** | `analytics_overview`, `analytics_project_health`, `analytics_team_skills`, `analytics_bottlenecks` |
| **Memory** | `memory_add_fact`, `memory_search_facts`, `memory_list_facts`, `memory_invalidate_fact`, `memory_ingest_message` |
| **People** | `people_upsert`, `people_get`, `people_list` |
| **Projects** | `projects_upsert`, `projects_list` |
| **Tasks** | `tasks_create`, `tasks_list`, `tasks_update_state`, `tasks_comment` |
| **Slack** | `slack_send_message`, `slack_list_channels`, `slack_join_channel`, `slack_check_in`, `slack_recent_messages` |
| **GitHub** | `github_list_repos`, `github_recent_activity`, `github_create_issue` |
| **Jira** | `jira_list_projects`, `jira_list_issues`, `jira_create_issue` |
| **Linear** | `linear_list_teams`, `linear_list_issues`, `linear_create_issue` |
| **Meetings** | `meetings_list`, `meeting_get_transcript`, `meeting_get_extraction`, `meeting_extract` |

The agent resolves people across platforms automatically. When you say "create a Linear issue for Sudhir", the agent:
1. Calls `people_list` to find Sudhir
2. Reads his `linear_id` from the unified people graph
3. Calls `linear_create_issue` with the correct `assigneeId`

---

## Deployment

Autogent is deployed on Google Cloud Run with Cloud SQL for PostgreSQL.

### Current deployment

| Service | URL |
|---|---|
| Frontend | `https://autogent-frontend-802301600867.us-central1.run.app` |
| Backend | `https://autogent-backend-802301600867.us-central1.run.app` |
| Cloud SQL | `autogent-db` — PostgreSQL 17, `us-central1` |

### Deploy from scratch

#### Prerequisites

1. A Google Cloud project with billing enabled
2. `gcloud` CLI installed and authenticated (`gcloud auth login`)
3. Apply hackathon credits to the billing account
4. Enable APIs:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  sqladmin.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  aiplatform.googleapis.com
```

#### Deploy the backend

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1

# Create Artifact Registry repository
gcloud artifacts repositories create autogent \
  --repository-format=docker --location=$REGION --project=$PROJECT_ID

# Build and push the backend image
gcloud builds submit ./backend \
  --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/autogent/autogent-backend:latest" \
  --project=$PROJECT_ID

# Create Cloud SQL instance
gcloud sql instances create autogent-db \
  --database-version=POSTGRES_17 \
  --tier=db-perf-optimized-N-2 \
  --region=$REGION --project=$PROJECT_ID

# Create database and user
gcloud sql databases create autogent --instance=autogent-db --project=$PROJECT_ID
gcloud sql users create autogent --instance=autogent-db \
  --password="your-secure-password" --project=$PROJECT_ID

# Get the Cloud SQL connection name
CLOUD_SQL_CONNECTION=$(gcloud sql instances describe autogent-db \
  --project=$PROJECT_ID --format="value(connectionName)")

# Deploy to Cloud Run
gcloud run deploy autogent-backend \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/autogent/autogent-backend:latest" \
  --region=$REGION --project=$PROJECT_ID \
  --port=8000 --cpu=2 --memory=2Gi \
  --min-instances=0 --max-instances=3 --timeout=300 \
  --add-cloudsql-instances="$CLOUD_SQL_CONNECTION" \
  --set-env-vars="ENVIRONMENT=production,\
DATABASE_URL=postgresql+psycopg://autogent:your-password@/autogent?host=/cloudsql/${CLOUD_SQL_CONNECTION},\
AI_PROVIDER=gemini,GEMINI_MODEL=gemini-3.5-flash,USE_ADK_AGENT=true,\
USE_VERTEX_AI=true,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,\
JWT_SECRET_KEY=your-jwt-secret,CREDENTIAL_ENCRYPTION_KEY=your-fernet-key,\
FRONTEND_URL=https://autogent-frontend-xxx.run.app,\
BACKEND_URL=https://autogent-backend-xxx.run.app,\
SLACK_CLIENT_ID=...,SLACK_CLIENT_SECRET=...,SLACK_SIGNING_SECRET=...,\
GITHUB_CLIENT_ID=...,GITHUB_CLIENT_SECRET=...,\
JIRA_CLIENT_ID=...,JIRA_CLIENT_SECRET=...,\
LINEAR_CLIENT_ID=...,LINEAR_CLIENT_SECRET=...,\
RECALL_API_KEY=...,RECALL_REGION=us-west-2" \
  --allow-unauthenticated --no-use-http2
```

The backend Dockerfile runs `alembic upgrade head` on startup, so database migrations are applied automatically.

#### Deploy the frontend

```bash
BACKEND_URL=https://autogent-backend-xxx.run.app

gcloud builds submit ./frontend \
  --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/autogent/autogent-frontend:latest" \
  --project=$PROJECT_ID

gcloud run deploy autogent-frontend \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/autogent/autogent-frontend:latest" \
  --region=$REGION --project=$PROJECT_ID \
  --port=3000 --cpu=1 --memory=1Gi \
  --min-instances=0 --max-instances=3 \
  --set-env-vars="NEXT_PUBLIC_API_URL=${BACKEND_URL}/api/v1,NODE_ENV=production" \
  --allow-unauthenticated
```

#### Update OAuth redirect URLs

After deployment, update the callback URLs in each integration's developer console:

| Provider | Redirect URL |
|---|---|
| Slack | `https://autogent-backend-xxx.run.app/api/v1/integrations/slack/callback` |
| GitHub | `https://autogent-backend-xxx.run.app/api/v1/integrations/github/callback` |
| Jira | `https://autogent-backend-xxx.run.app/api/v1/integrations/jira/callback` |
| Linear | `https://autogent-backend-xxx.run.app/api/v1/integrations/linear/callback` |
| Recall.ai | `https://autogent-backend-xxx.run.app/api/v1/recall/webhooks` |

### Cost notes

- Cloud Run scales to zero when idle — you only pay for actual requests
- Cloud SQL `db-perf-optimized-N-2` is covered by hackathon credits
- Gemini 3.5 Flash is cost-effective for agentic workloads
- Set `--min-instances=0` to avoid charges when the app is not receiving traffic

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 17 (with pgvector extension)
- Redis 7

### 1. Start PostgreSQL + Redis

```bash
docker compose up -d db redis
```

This starts a `pgvector/pgvector:pg17` container on port 5432 and Redis on 6379.

### 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit .env with your keys
python run_dev.py                 # starts uvicorn on :8000
```

**Required `.env` settings:**

```bash
AI_PROVIDER=gemini
GEMINI_MODEL=gemini-3.5-flash
USE_ADK_AGENT=true
USE_VERTEX_AI=true
GOOGLE_CLOUD_PROJECT=your-project-id

DATABASE_URL=postgresql+psycopg://autogent:autogent@127.0.0.1:5432/autogent
REDIS_URL=redis://127.0.0.1:6379

JWT_SECRET_KEY=change-me-to-a-random-32-plus-char-string
CREDENTIAL_ENCRYPTION_KEY=  # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The backend runs migrations on startup.

### 3. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env             # then edit if needed
npm run dev                      # starts Next.js on :3000
```

**Frontend `.env`:**

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

### 4. Open the app

Navigate to [http://localhost:3000](http://localhost:3000), sign up, create a workspace, and start chatting with the agent at `/agent`.

---

## Testing

### Run the test suite

```bash
cd backend
source venv/bin/activate
pip install pytest pytest-asyncio          # if not already installed
python -m pytest tests/ -v
```

The suite includes 13 unit tests covering config validation, pagination helpers, and webhook signature verification. Tests are lightweight — no database or external services required.

```
tests/
├── conftest.py           # pytest config, sys.path setup
├── test_config.py        # 9 tests — environment validation, JWT secret rules, pagination
└── test_webhooks.py      # 4 tests — GitHub webhook signature verification (valid, invalid, prod/dev behavior)
```

### What's covered

| Test file | Tests | What it validates |
|---|---|---|
| `test_config.py` | 9 | Dev defaults allowed; production rejects missing/short/dev JWT secrets; invalid environment rejected; pagination defaults, custom values, and `has_more` logic |
| `test_webhooks.py` | 4 | GitHub webhook HMAC-SHA256 verification — valid signature accepted, invalid rejected, missing secret rejected in production but allowed in dev |

### Manual API testing

The backend exposes interactive API docs at:

- **Swagger UI:** `https://autogent-backend-802301600867.us-central1.run.app/docs`
- **ReDoc:** `https://autogent-backend-802301600867.us-central1.run.app/redoc`

Key endpoints to test manually:

```bash
# Health check
curl https://autogent-backend-802301600867.us-central1.run.app/health

# Sign up (creates user + workspace)
curl -X POST https://autogent-backend-802301600867.us-central1.run.app/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123","display_name":"Test User"}'

# Login (returns JWT)
curl -X POST https://autogent-backend-802301600867.us-central1.run.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}'

# Use the token for authenticated endpoints
TOKEN="your-jwt-token"
curl https://autogent-backend-802301600867.us-central1.run.app/api/v1/analytics?workspace_id=YOUR_WS_ID \
  -H "Authorization: Bearer $TOKEN"

# Agent chat
curl -X POST https://autogent-backend-802301600867.us-central1.run.app/api/v1/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"YOUR_WS_ID","message":"How are things going?"}'
```

### Frontend build verification

```bash
cd frontend
npm install
npm run build        # production build — catches type errors and import issues
npm run lint         # ESLint
```

### Database verification

After running migrations or seeding, verify the schema:

```bash
# Connect to local PostgreSQL
psql postgresql://autogent:autogent@127.0.0.1:5432/autogent

# Check key tables
SELECT count(*) FROM memory_people;
SELECT count(*) FROM memory_tasks;
SELECT count(*) FROM meetings;
SELECT count(*) FROM memory_facts;

# Verify pgvector extension
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

---

## Project Structure

```
Autogent/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   │   ├── adk_agent.py      # Google ADK integration (LlmAgent + Runner)
│   │   │   ├── gemini_llm.py     # Gemini 3.5 Flash client (google-genai SDK)
│   │   │   ├── llm.py            # LLM client (Gemini primary, Cerebras fallback)
│   │   │   ├── loop.py           # Custom ReAct loop (fallback when ADK disabled)
│   │   │   ├── prompts.py        # PM intelligence prompts
│   │   │   ├── parsing.py        # JSON response parser
│   │   │   └── registry.py       # Tool registry + ToolContext
│   │   ├── api/v1/               # FastAPI routes
│   │   │   ├── agent.py          # Agent chat endpoint
│   │   │   ├── analytics.py      # Analytics dashboard API
│   │   │   ├── auth.py           # Signup, login, password reset
│   │   │   ├── integrations.py   # OAuth flow for Slack, GitHub, Jira, Linear
│   │   │   ├── meetings.py       # Meeting list, detail, transcripts
│   │   │   ├── recall_webhooks.py # Recall.ai webhook handler
│   │   │   └── ...
│   │   ├── db/                   # SQLAlchemy async session
│   │   ├── models/               # core, memory, work, meetings, integrations
│   │   ├── schemas/              # Pydantic extraction schemas
│   │   ├── services/
│   │   │   ├── people_sync.py    # Unified people graph sync
│   │   │   ├── meeting_extraction.py # Gemini-powered transcript extraction
│   │   │   ├── slack_onboarding.py   # Auto-onboard new Slack members
│   │   │   ├── recall_client.py  # Recall.ai API client
│   │   │   └── ...
│   │   ├── tools/                # 36 agent tools
│   │   │   ├── analytics.py      # analytics_overview, project_health, team_skills, bottlenecks
│   │   │   ├── memory.py         # fact storage and semantic search
│   │   │   ├── people.py         # people lookup with integration identities
│   │   │   ├── tasks.py          # task CRUD
│   │   │   ├── slack.py          # Slack messaging, channels, check-ins
│   │   │   ├── github.py         # GitHub repos, activity, issues
│   │   │   ├── jira.py           # Jira projects, issues, creation
│   │   │   ├── linear.py         # Linear teams, issues, creation
│   │   │   └── meetings.py       # meeting transcript and extraction tools
│   │   ├── config.py             # Pydantic settings
│   │   └── main.py               # FastAPI app + lifespan + CORS
│   ├── alembic/                  # database migrations
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── (app)/                # authenticated app shell
│   │   │   ├── agent/            # chat UI with tool call traces
│   │   │   ├── analytics/        # analytics dashboard
│   │   │   ├── dashboard/        # overview stats
│   │   │   ├── tasks/            # task list
│   │   │   ├── approvals/        # approve/reject extracted tasks
│   │   │   ├── meetings/         # meeting list + detail with transcripts
│   │   │   ├── memory/           # searchable fact store
│   │   │   ├── people/           # team profiles with integration links
│   │   │   ├── integrations/     # connect/disconnect providers
│   │   │   └── settings/         # escalation rules
│   │   ├── login/                # auth pages
│   │   ├── signup/
│   │   ├── forgot-password/
│   │   ├── reset-password/
│   │   └── page.tsx              # public landing page
│   ├── components/               # UI components, providers, app shell
│   ├── lib/                      # api client, types, utils
│   ├── Dockerfile
│   └── .env.example
├── deploy/
│   ├── cloud-run.sh              # backend deployment script
│   └── cloud-run-frontend.sh     # frontend deployment script
├── docker-compose.yml            # local dev: PostgreSQL + pgvector + Redis
└── README.md
```

---

## Configuration

See `backend/.env.example` for the full list. Key settings:

| Variable | Description |
|----------|-------------|
| `AI_PROVIDER` | LLM provider: `gemini`, `cerebras`, or `openai` |
| `GEMINI_MODEL` | Gemini model ID (default: `gemini-3.5-flash`) |
| `USE_VERTEX_AI` | Set to `true` for Vertex AI access |
| `GOOGLE_CLOUD_PROJECT` | Required when `USE_VERTEX_AI=true` |
| `USE_ADK_AGENT` | Use Google ADK as the agent framework (default: `true`) |
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | JWT signing secret (use a random 32+ char string) |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for encrypting integration tokens |
| `FRONTEND_URL` | Frontend URL for CORS |
| `BACKEND_URL` | Backend URL for OAuth redirect URIs |
| `SLACK_CLIENT_ID` | Slack OAuth app credentials |
| `GITHUB_CLIENT_ID` | GitHub OAuth app credentials |
| `JIRA_CLIENT_ID` | Jira OAuth app credentials |
| `LINEAR_CLIENT_ID` | Linear OAuth app credentials |
| `RECALL_API_KEY` | Recall.ai API key for meeting bot |

---

## Findings & Learnings

- **Grounded extraction is critical.** Early versions of meeting extraction produced plausible but fabricated owners and deadlines. Grounding every extracted item in exact transcript chunk IDs — and instructing the model not to invent — dramatically improved reliability.
- **Identity resolution is the foundation.** Without a unified people graph, the agent can't assign tasks correctly. Matching by email first, then name, then provider-specific IDs ensures that "Sudhir on Slack" and "sudhirKsah on GitHub" become one person.
- **ADK's tool-calling loop is effective but needs guardrails.** The agent will happily call 10 tools in one turn if allowed. Setting a step budget and writing a precise system prompt that tells the agent which tools to use for which questions keeps responses focused.
- **Structured output beats freeform text.** Using Gemini's structured JSON output for extraction and state inference produces consistently parseable results, while freeform text often requires fallback parsing.
- **Cloud Run cold starts are acceptable for a demo.** With `min-instances=0`, the first request after idle takes a few seconds. For a hackathon demo, this is fine. For production, set `min-instances=1`.
