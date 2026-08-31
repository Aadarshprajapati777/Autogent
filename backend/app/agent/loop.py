"""The agent loop. This is Autogent's core: a ReAct-style cycle that sends
the conversation + tool schemas to the LLM, executes any tool_calls the LLM
returns, feeds the results back, and repeats until the LLM produces a final
answer (no tool calls) or the step budget is exhausted.

Each step is recorded so the caller (API, Slack handler, scheduler) can show
the user exactly what the agent did — which tools it called, with what args,
and what came back. That trace is what makes the agent observable.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .llm import LLMError, get_llm
from .registry import ToolContext, all_tools, get_tool, schemas_for

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Autogent, an autonomous AI project manager.
You sit between founders and engineering teams. You help teams get work done
by calling tools: reading and writing memory, looking up people and projects,
checking Slack, creating tasks, onboarding engineers, and more.

You are not a generic chatbot — you are a PM. Act like one.

CORE RULES:
- Think step by step. Call one tool at a time when you need information or
  want to take an action.
- Always ground answers in tool results, not guesses. If you don't know,
  say so or call a tool to find out.
- When you have enough context, answer the user directly with no tool call.
- Be concise. Prefer facts over filler.

PM BEHAVIOR:
- Use tools to gather context BEFORE answering. Search memory for relevant
  facts, look up people and projects, check task status.
- Ground claims in stored facts and task data. Never invent facts.
- Identify your audience: founder (plain language, no jargon), engineer
  (direct, technical), internal (candid about risks).
- Be skeptical of unsupported completion claims. "I finished it" without
  evidence is not the same as "done". Distinguish completed, in-progress,
  blocked, and planned work.
- Track commitments and deadlines. Flag overdue commitments and missed
  deadlines honestly.
- Detect blockers and risks. Surface them to founders when serious.
- Use people and project profiles to make informed decisions about
  assignments, check-ins, and interventions.
- Use check-in and onboarding workflows consistently. Don't spam — respect
  cooldowns.
- Choose the right tool for the job. Don't call memory_search_facts if you
  already have the answer in context.
- Keep responses concise and natural. No corporate speak. No padding.
- When a founder describes a new project or feature, break it into concrete
  tasks and match them to team members by skill. If no team exists yet,
  suggest onboarding first.
- When asked about the team, mention EVERYONE — not just the person with the
  most data. If someone hasn't been onboarded, say so.
- Don't claim someone missed deadlines unless you have evidence. Don't claim
  someone is "not working" unless a fact says so. Distinguish "vague updates"
  (low quality info) from "missed deadlines" (a specific failure).
"""


@dataclass
class AgentStep:
    """One step in the run: the LLM's message + any tool calls executed."""
    message: dict
    tool_results: list[dict] = field(default_factory=list)


@dataclass
class AgentRun:
    """The full result of one agent.run() call."""
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False

    def actions(self) -> list[dict]:
        """Flattened tool-call trace for the chat UI / persistence."""
        actions = []
        for step in self.steps:
            for tc in step.message.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                try:
                    args_parsed = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    args_parsed = {"_raw": args}
                result = next(
                    (r for r in step.tool_results if r.get("tool_call_id") == tc.get("id")),
                    None,
                )
                actions.append(
                    {
                        "tool": fn.get("name"),
                        "arguments": args_parsed,
                        "result": result.get("content") if result else None,
                        "error": result.get("error") if result else None,
                    }
                )
        return actions


class Agent:
    """Stateless agent. A fresh instance per run keeps the loop simple; all
    per-conversation state lives in the messages list passed in by the caller.
    """

    def __init__(self, tool_names: list[str] | None = None) -> None:
        self.tool_names = tool_names

    async def run(
        self,
        messages: list[dict],
        ctx: ToolContext,
        *,
        max_steps: int | None = None,
    ) -> AgentRun:
        llm = get_llm()
        tools = all_tools() if self.tool_names is None else [
            get_tool(n) for n in self.tool_names
        ]
        schemas = [t.schema() for t in tools]
        budget = max_steps or settings.agent_max_steps

        # Seed the system prompt if the caller didn't.
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

        run = AgentRun(answer="")
        for _ in range(budget):
            try:
                assistant = await llm.chat(messages, tools=schemas)
            except LLMError as exc:
                run.error = str(exc)
                run.answer = "I hit a problem reaching the model. Please try again."
                return run

            step = AgentStep(message=assistant)
            # Strip internal fields before appending to messages so the LLM
            # only sees valid message properties (role, content, tool_calls).
            clean = {k: v for k, v in assistant.items() if not k.startswith("_")}
            messages.append(clean)
            tool_calls = assistant.get("tool_calls") or []

            if not tool_calls:
                run.answer = (assistant.get("content") or "").strip()
                run.steps.append(step)
                return run

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError as exc:
                    result = {
                        "tool_call_id": tc.get("id"),
                        "error": f"invalid JSON arguments: {exc}",
                        "content": f"invalid JSON arguments: {exc}",
                    }
                    step.tool_results.append(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": result["content"],
                        }
                    )
                    continue

                try:
                    tool = get_tool(name)
                    content = await tool.run(ctx, args)
                    result = {"tool_call_id": tc.get("id"), "content": content}
                except Exception as exc:  # noqa: BLE001 — tools surface errors to the LLM
                    log.exception("tool %s failed", name)
                    # Rollback the session so it's usable for subsequent tools
                    # and the final commit. The error is surfaced to the LLM.
                    await ctx.db.rollback()
                    content = f"tool error: {exc}"
                    result = {"tool_call_id": tc.get("id"), "error": str(exc), "content": content}

                step.tool_results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": result["content"],
                    }
                )

            run.steps.append(step)

        run.truncated = True
        run.answer = "I reached my step limit without finishing. Here's what I have so far."
        return run


# Convenience singleton — Agent is stateless so one instance is fine.
agent = Agent()
