# Autogent

An agentic execution platform. One backend owns the agent loop, tools, and
memory — no separate memory service. The agent calls tools (Slack, memory,
profile, GitHub, tasks, ...) to do real work, and the Next.js frontend is the
interface to it.

## Services

| Service | Port | Directory | What it does |
|---------|------|-----------|--------------|
| Frontend | 3000 | `frontend/` | Next.js dashboard + agent chat |
| Backend | 8000 | `backend/` | FastAPI: API, agent loop, tools, memory |

## Stack

- Backend: FastAPI, SQLAlchemy (PostgreSQL), Redis, Celery, Cerebras LLM
- Frontend: Next.js, Clerk auth, Tailwind

See `backend/.env.example` and `frontend/.env.example` for configuration.
