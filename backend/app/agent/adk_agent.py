"""Google Agent Development Kit (ADK) integration for Autogent.

This module wraps Autogent's existing tool registry as ADK ``FunctionTool``
instances and runs the chat agent through ADK's ``LlmAgent`` + ``Runner`` —
Google's official agent framework. The agent uses Gemini 3.5 Flash as its
model and executes the same ReAct-style tool-calling loop as the custom
``Agent`` in ``loop.py``, but through ADK's battle-tested runtime.

A ``contextvars.ContextVar`` bridges ADK's tool invocation to Autogent's
own ``ToolContext`` (which carries the DB session, workspace id, and user
id). This keeps the existing tools unchanged — they still receive the same
context they always have.

If ADK is not available or ``USE_ADK_AGENT`` is disabled, the agent router
falls back to the custom ReAct loop in ``loop.py``.
"""
from __future__ import annotations

import contextvars
import inspect
import json
import logging
import os
import uuid
from typing import Any

from google import genai
from google.genai import types as gtypes
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool

from ..config import settings
from .loop import AgentRun, AgentStep, SYSTEM_PROMPT
from .registry import Tool, ToolContext, all_tools, get_tool

log = logging.getLogger(__name__)

# ContextVar that carries Autogent's ToolContext into ADK tool calls.
_ctx_var: contextvars.ContextVar[ToolContext] = contextvars.ContextVar(
    "autogent_tool_ctx"
)

# Lazily-built ADK agent + runner (built once, reused across requests).
_adk_agent: LlmAgent | None = None
_adk_runner: Runner | None = None
_session_service: InMemorySessionService | None = None


# ── JSON Schema → Python type mapping for tool signatures ──────────────

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_type_to_py(json_type: str) -> type:
    return _JSON_TYPE_MAP.get(json_type, str)


def _make_adk_tool_func(tool: Tool):
    """Create an async function with a proper signature that ADK's
    ``FunctionTool`` can introspect. The function reads Autogent's
    ``ToolContext`` from the ContextVar and delegates to the real tool.
    """
    properties: dict[str, Any] = tool.parameters.get("properties", {})
    required: set[str] = set(tool.parameters.get("required", []))

    async def _adk_func(**kwargs):
        ctx = _ctx_var.get()
        return await tool.run(ctx, kwargs)

    _adk_func.__name__ = tool.name
    _adk_func.__doc__ = tool.description

    # Build a proper signature so ADK can generate the function declaration
    # with the right parameter names, types, and required flags.
    params: list[inspect.Parameter] = []
    for prop_name, prop_schema in properties.items():
        py_type = _json_type_to_py(prop_schema.get("type", "string"))
        default = (
            inspect.Parameter.empty if prop_name in required else None
        )
        params.append(
            inspect.Parameter(
                prop_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=py_type,
            )
        )

    _adk_func.__signature__ = inspect.Signature(params)
    _adk_func.__annotations__ = {p.name: p.annotation for p in params}
    return _adk_func


def _build_adk_agent() -> LlmAgent:
    """Build the ADK LlmAgent with all registered Autogent tools."""
    # Import the tools package so all tools register before we read the
    # registry. This is idempotent — Python caches module imports.
    import app.tools  # noqa: F401

    tools = all_tools()
    adk_tools = [FunctionTool(func=_make_adk_tool_func(t)) for t in tools]

    config = gtypes.GenerateContentConfig(
        temperature=settings.agent_model_temperature,
        # Disable thinking output to ensure the model returns direct text
        # responses instead of only thinking traces.
        thinking_config=gtypes.ThinkingConfig(include_thoughts=False),
    )

    agent = LlmAgent(
        model=settings.gemini_model,
        name="autogent_pm",
        description=(
            "Autogent — an autonomous AI project manager for engineering "
            "teams. It manages tasks, memory, people, meetings, and "
            "integrations proactively."
        ),
        instruction=SYSTEM_PROMPT,
        tools=adk_tools,
        generate_content_config=config,
    )
    log.info(
        "ADK agent built: model=%s, tools=%d",
        settings.gemini_model,
        len(adk_tools),
    )
    return agent


def _ensure_adk_env():
    """Set environment variables so ADK's internal genai.Client picks up
    the right credentials. Uses explicit assignment (not setdefault) so
    switching between Gemini API and Vertex AI works reliably."""
    if settings.use_vertex_ai:
        # Force Vertex AI mode and clear any API keys that would cause
        # the genai client to fall back to the Gemini Developer API.
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
    else:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
        os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
        os.environ.pop("GOOGLE_CLOUD_LOCATION", None)
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
            os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key


def _get_adk_runner() -> Runner:
    global _adk_agent, _adk_runner, _session_service
    if _adk_runner is None:
        _ensure_adk_env()
        _adk_agent = _build_adk_agent()
        _session_service = InMemorySessionService()
        _adk_runner = Runner(
            agent=_adk_agent,
            app_name="autogent",
            session_service=_session_service,
        )
    return _adk_runner


# ── Main entry point ───────────────────────────────────────────────────

async def run_adk_agent(
    messages: list[dict],
    ctx: ToolContext,
    *,
    max_steps: int | None = None,
) -> AgentRun:
    """Run the ADK agent and return an ``AgentRun`` compatible with the
    existing agent router.

    The conversation history (minus the system prompt, which becomes the
    ADK agent's instruction) is pre-loaded into an in-memory session as
    prior events. The final user message is sent as ``new_message``.
    """
    runner = _get_adk_runner()
    user_id = str(ctx.user_id or "default")

    # Set the ToolContext for this run's tool calls.
    token = _ctx_var.set(ctx)

    try:
        # Create a fresh session for this conversation turn.
        session = await _session_service.create_session(
            app_name="autogent",
            user_id=user_id,
        )

        # Pre-populate conversation history (everything except the system
        # prompt and the last user message, which goes as new_message).
        history = [
            m for m in messages if m.get("role") != "system"
        ]
        if history and history[-1].get("role") == "user":
            new_msg = history[-1]
            prior = history[:-1]
        else:
            new_msg = {"role": "user", "content": ""}
            prior = history

        for msg in prior:
            role = "user" if msg.get("role") == "user" else "model"
            text = msg.get("content") or ""
            content = gtypes.Content(
                role=role, parts=[gtypes.Part(text=text)]
            )
            from google.adk.events import Event

            event = Event(
                invocation_id=f"hist-{session.id}",
                author=role,
                content=content,
            )
            await _session_service.append_event(session, event)

        # Send the new user message.
        new_content = gtypes.Content(
            role="user",
            parts=[gtypes.Part(text=new_msg.get("content", ""))],
        )

        # Collect events and build the trace.
        run = AgentRun(answer="")
        steps: list[AgentStep] = []
        pending_tool_calls: list[dict] = []
        actions: list[dict] = []

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=new_content,
        ):
            # Skip the echoed user message.
            if event.author == "user" and not event.content:
                continue

            if not event.content or not event.content.parts:
                continue

            step_tool_calls: list[dict] = []
            step_tool_results: list[dict] = []

            for part in event.content.parts:
                # Skip thinking parts
                if getattr(part, "thought", False):
                    continue

                # Capture text response. Accumulate text across events
                # and prefer the final (turn_complete) text, but fall back
                # to any non-empty text if turn_complete never fires with
                # text content.
                if part.text:
                    if event.turn_complete:
                        run.answer = part.text
                    elif not run.answer:
                        run.answer = part.text

                if part.function_call:
                    fc = part.function_call
                    call_id = f"call_{len(actions)}"
                    args = fc.args if fc.args else {}
                    step_tool_calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(args),
                        },
                    })
                    # Track for pairing with response
                    pending_tool_calls.append({
                        "id": call_id,
                        "name": fc.name,
                        "args": args,
                    })

                if part.function_response:
                    fr = part.function_response
                    response = fr.response if fr.response else {}
                    # Pair with the pending tool call
                    if pending_tool_calls:
                        pending = pending_tool_calls.pop(0)
                        result_content = (
                            json.dumps(response, default=str)
                            if isinstance(response, dict)
                            else str(response)
                        )
                        step_tool_results.append({
                            "tool_call_id": pending["id"],
                            "content": result_content,
                        })
                        actions.append({
                            "tool": pending["name"],
                            "arguments": pending["args"],
                            "result": result_content,
                            "error": None,
                        })

            if step_tool_calls or step_tool_results:
                step_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": step_tool_calls,
                }
                step = AgentStep(message=step_msg, tool_results=step_tool_results)
                steps.append(step)

        # Clean up the session (in-memory, ephemeral).
        try:
            await _session_service.delete_session(
                app_name="autogent",
                user_id=user_id,
                session_id=session.id,
            )
        except Exception:
            pass

        run.steps = steps
        # If no actions were collected via events, fall back to the
        # steps-based extraction (same logic as AgentRun.actions()).
        if not actions:
            actions = run.actions()

        # Store actions on the run for the router to use.
        run._adk_actions = actions  # type: ignore[attr-defined]

        return run
    finally:
        _ctx_var.reset(token)


def is_adk_available() -> bool:
    """Check whether ADK should be used for the chat agent."""
    return settings.use_adk_agent and settings.ai_provider.lower() == "gemini"
