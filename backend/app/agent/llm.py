"""LLM client for the agent.

**Gemini 3.5 Flash** (via the Google GenAI SDK) is the default brain — it is
optimized for agentic execution, tool calling, and long-horizon tasks.
Cerebras and OpenAI are available as fallback providers; all expose the same
``chat()`` / ``complete()`` interface the agent loop relies on.
"""
from __future__ import annotations

import asyncio
import logging

from openai import APIError, AsyncOpenAI

from ..config import settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        provider = settings.ai_provider.lower()
        if provider == "gemini":
            # Delegate to the Gemini client which uses google-genai SDK.
            from .gemini_llm import GeminiLLMClient, LLMError as GeminiLLMError

            self._gemini = GeminiLLMClient()
            self.model = self._gemini.model
            self._provider = "gemini"
        elif provider == "cerebras":
            if not settings.cerebras_api_key:
                raise LLMError("CEREBRAS_API_KEY is not set")
            self._client = AsyncOpenAI(
                base_url="https://api.cerebras.ai/v1",
                api_key=settings.cerebras_api_key,
                timeout=60.0,
            )
            self.model = settings.cerebras_model
            self._provider = "openai_compat"
        elif provider == "openai":
            if not settings.openai_api_key:
                raise LLMError("OPENAI_API_KEY is not set")
            self._client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)
            self.model = "gpt-4o-mini"
            self._provider = "openai_compat"
        else:
            raise LLMError(f"unknown AI_PROVIDER: {provider}")

    async def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Run one chat turn. Returns the raw choice message dict
        (role, content, tool_calls). Retries with backoff on transient errors.
        """
        # Gemini has its own client with the same interface.
        if self._provider == "gemini":
            return await self._gemini.chat(
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": (
                temperature
                if temperature is not None
                else settings.agent_model_temperature
            ),
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                return {
                    "role": "assistant",
                    "content": choice.message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in (choice.message.tool_calls or [])
                    ],
                    # finish_reason is kept separately — Cerebras rejects it
                    # if it ends up in the messages array on the next turn.
                    "_finish_reason": choice.finish_reason,
                }
            except (APIError, asyncio.TimeoutError) as exc:
                last_error = exc
                log.warning("LLM call failed (attempt %d): %s", attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise LLMError(f"LLM call failed after retries: {last_error}") from last_error

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Run a single-prompt completion (no tools, no conversation history).
        Used by the PM intelligence services (extraction, onboarding, check-in,
        state inference) that need structured JSON output from a single prompt.
        Returns the raw content string.
        """
        messages = [{"role": "user", "content": prompt}]
        result = await self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (result.get("content") or "").strip()


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
