"""Tool registry. Tools are the agent's hands — each is an async function
decorated with @tool that declares a JSON-schema for its arguments. The
agent loop discovers registered tools, sends their schemas to the LLM, and
dispatches the LLM's tool_calls to the matching function.

A ToolContext carries the per-call state every tool needs: the DB session,
the workspace id, and the acting user. Tools stay stateless and read their
dependencies from the context.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    """Per-invocation state handed to every tool."""
    db: AsyncSession
    workspace_id: UUID
    user_id: UUID | None = None
    # Integrations resolved for the workspace at the start of the run, keyed
    # by provider name. Tools that call external services read their creds
    # from here instead of re-querying the DB each call.
    integrations: dict[str, dict] | None = None


ToolFunc = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


class Tool:
    __slots__ = ("name", "description", "parameters", "func")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: ToolFunc,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func

    def schema(self) -> dict:
        """OpenAI/Cerebras tool schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> str:
        result = await self.func(ctx, arguments)
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)
        return str(result)


_REGISTRY: dict[str, Tool] = {}


def tool(
    name: str, description: str, parameters: dict
) -> Callable[[ToolFunc], ToolFunc]:
    """Register an async function as an agent tool."""

    def decorator(func: ToolFunc) -> ToolFunc:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"tool {name} must be async")
        if name in _REGISTRY:
            raise ValueError(f"tool {name} already registered")
        _REGISTRY[name] = Tool(name, description, parameters, func)
        return func

    return decorator


def get_tool(name: str) -> Tool:
    if name not in _REGISTRY:
        raise KeyError(f"unknown tool: {name}")
    return _REGISTRY[name]


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def schemas_for(names: list[str] | None = None) -> list[dict]:
    """Schemas for a subset of tools (or all if names is None)."""
    if names is None:
        return [t.schema() for t in _REGISTRY.values()]
    return [_REGISTRY[n].schema() for n in names if n in _REGISTRY]


def clear_registry() -> None:
    """Test helper — wipe the registry between test modules."""
    _REGISTRY.clear()
