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

SYSTEM_PROMPT = """You are Autogent, an autonomous execution agent.
You help teams get work done by calling tools: reading and writing memory,
looking up people and projects, checking Slack, creating tasks, and more.

Rules:
- Think step by step. Call one tool at a time when you need information or
  want to take an action.
- Always ground answers in tool results, not guesses. If you don't know,
  say so or call a tool to find out.
- When you have enough context, answer the user directly with no tool call.
- Be concise. Prefer facts over filler.
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
            messages.append(assistant)
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
