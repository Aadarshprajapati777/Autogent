# Autogent

An agentic execution platform. One backend owns the agent loop, tools, and
memory — no separate memory service. The agent calls tools (Slack, memory,
profile, GitHub, tasks, ...) to do real work, and the Next.js frontend is the
interface to it.

## Services

| Service | Port | Directory | What it does |
|---------|------|-----------|--------------|
| Frontend | 3000 | `frontend/` | Next.js 16 dashboard + agent chat |
| Backend | 8000 | `backend/` | FastAPI: API, agent loop, tools, memory |

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────┐
│  Frontend   │────▶│              Backend                  │
│  Next.js 16 │     │  FastAPI + SQLAlchemy + async PG      │
│  Clerk auth │     │                                      │
│  Tailwind v4│     │  ┌──────────┐   ┌─────────────────┐  │
└─────────────┘     │  │ Agent    │──▶│ Tool Registry   │  │
                    │  │ Loop     │   │ - memory        │  │
                    │  │ (Cerebras)│  │ - people        │  │
                    │  └──────────┘   │ - tasks         │  │
                    │                 │ - slack         │  │
                    │  ┌──────────┐   │ - github        │  │
                    │  │ Memory   │   │ - integrations  │  │
                    │  │ (PG)     │   └─────────────────┘  │
                    │  └──────────┘                        │
                    └──────────────────────────────────────┘
```

Key difference from CloseLoopAI: **no separate memory service**. Memory
(facts, people, projects) lives inside the backend as SQLAlchemy models,
and the agent accesses it through tools instead of HTTP calls.

## Stack

- **Backend**: FastAPI, SQLAlchemy async, PostgreSQL, Redis, Celery
- **LLM**: Cerebras (OpenAI-compatible) via `gpt-oss-120b`
- **Auth**: Clerk (RS256 JWT) with fallback custom JWT (HS256)
- **Frontend**: Next.js 16, React 19, Tailwind CSS v4, Clerk
- **Payments**: Razorpay
- **Meetings**: Recall.ai (bot joins, transcribes, extracts)
- **Integrations**: Slack, GitHub, Jira, Linear, Notion, Google/Microsoft Calendar

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL
- Redis

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # fill in your keys
python run_dev.py            # starts uvicorn on :8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in Clerk keys + API URL
npm run dev                  # starts Next.js on :3000
```

## Agent tools

The agent loop calls registered tools to act on the world:

| Tool | What it does |
|------|-------------|
| `memory_add` | Store a fact in memory |
| `memory_search` | Semantic search over facts |
| `memory_list` | List facts by topic/kind |
| `memory_invalidate` | Mark a fact as superseded |
| `people_create` / `people_update` / `people_list` | Manage person profiles |
| `tasks_create` / `tasks_list` / `tasks_update` / `tasks_set_state` | Task management |
| `slack_send_message` | Send a Slack message |
| `slack_check_in` | Check in with a team member on Slack |
| `slack_lookup` | Look up Slack channels/users |
| `github_list_repos` / `github_list_activity` | GitHub activity |

## Proactive scheduler

The backend runs a background scheduler (`pm_scheduler`) that periodically
asks the agent to check in with team members and follow up on stale work —
without a user prompt. This makes Autogent autonomous.

## Project structure

```
Autogent/
├── backend/
│   └── app/
│       ├── agent/          # LLM client, tool registry, agent loop
│       ├── api/v1/         # FastAPI routes
│       ├── db/             # SQLAlchemy async session
│       ├── models/         # core, memory, work, meetings, operations, payments
│       ├── schemas/        # Pydantic extraction schemas
│       ├── services/       # recall, extraction, payments, scheduler, ...
│       └── tools/          # agent tools (memory, people, tasks, slack, github)
└── frontend/
    ├── app/
    │   ├── (app)/          # authenticated app shell + all feature pages
    │   ├── login/          # auth pages
    │   └── signup/
    ├── components/         # auth provider, workspace provider, app shell
    └── lib/                # api client, types, utils
```

## Configuration

See `backend/.env.example` and `frontend/.env.example` for all environment
variables.
