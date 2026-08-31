"""Gemini LLM client built on the Google GenAI SDK (google-genai).

This is the primary LLM backend for Autogent. It uses Gemini 3.5 Flash —
Google's most intelligent Flash model, optimized for agentic execution,
tool calling, and long-horizon tasks.

The client exposes the same ``chat()`` / ``complete()`` interface as the
OpenAI-compatible ``LLMClient`` so the existing ReAct agent loop and all
PM intelligence services (extraction, onboarding, state inference, etc.)
work unchanged.

Two access modes are supported:
  * **Gemini Developer API** — set ``GEMINI_API_KEY`` (default, simplest).
  * **Vertex AI / Agent Platform** — set ``USE_VERTEX_AI=true`` with
    ``GOOGLE_CLOUD_PROJECT`` and ``GOOGLE_CLOUD_LOCATION`` for production
    deployments on Google Cloud.
"""
from __future__ import annotations

import asyncio
import json
import logging

from google import genai
from google.genai import types as gtypes

from ..config import settings

log = logging.getLogger(__name__)


class GeminiLLMClient:
    """LLM client that talks to Gemini 3.5 Flash via the google-genai SDK."""

    def __init__(self) -> None:
        if settings.use_vertex_ai:
            if not settings.google_cloud_project:
                raise LLMError(
                    "USE_VERTEX_AI is enabled but GOOGLE_CLOUD_PROJECT is not set"
                )
            self._client = genai.Client(
                enterprise=True,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
            )
            log.info(
                "Gemini client (Vertex AI): project=%s, location=%s, model=%s",
                settings.google_cloud_project,
                settings.google_cloud_location,
                settings.gemini_model,
            )
        else:
            if not settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set")
            self._client = genai.Client(api_key=settings.gemini_api_key)
            log.info("Gemini client (Developer API): model=%s", settings.gemini_model)

        self.model = settings.gemini_model

    # ── public API (same interface as LLMClient) ──────────────────────

    async def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Run one chat turn. Returns the raw choice message dict
        (role, content, tool_calls) — same shape the agent loop expects.
        """
        system_instruction, contents = self._convert_messages(messages)
        config = gtypes.GenerateContentConfig(
            temperature=(
                temperature
                if temperature is not None
                else settings.agent_model_temperature
            ),
        )
        if system_instruction:
            config.system_instruction = system_instruction
        if max_tokens:
            config.max_output_tokens = max_tokens
        if tools:
            config.tools = self._convert_tools(tools)

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(response)
            except Exception as exc:
                last_error = exc
                log.warning("Gemini call failed (attempt %d): %s", attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise LLMError(f"Gemini call failed after retries: {last_error}") from last_error

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Single-prompt completion (no tools, no history). Used by PM
        intelligence services that need structured JSON output.
        """
        result = await self.chat(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (result.get("content") or "").strip()

    # ── message conversion: OpenAI format → Gemini format ─────────────

    def _convert_messages(
        self, messages: list[dict]
    ) -> tuple[str | None, list[gtypes.Content]]:
        """Split system messages into system_instruction and convert the
        rest into Gemini ``Content`` objects.

        Gemini uses ``role="model"`` instead of ``role="assistant"`` and
        represents tool results as ``function_response`` parts inside a
        ``role="user"`` content.
        """
        system_parts: list[str] = []
        contents: list[gtypes.Content] = []
        # Map tool_call_id → function name so we can build function_response
        # parts for tool-result messages.
        call_id_to_name: dict[str, str] = {}

        for msg in messages:
            role = msg.get("role", "user")

            if role == "system":
                text = msg.get("content") or ""
                if text:
                    system_parts.append(text)
                continue

            if role == "tool":
                # Tool result → function_response part in a user content.
                call_id = msg.get("tool_call_id", "")
                fn_name = call_id_to_name.get(call_id, call_id)
                raw_content = msg.get("content", "")
                try:
                    response_dict = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                    if not isinstance(response_dict, dict):
                        response_dict = {"result": raw_content}
                except (json.JSONDecodeError, TypeError):
                    response_dict = {"result": raw_content}

                contents.append(
                    gtypes.Content(
                        role="user",
                        parts=[
                            gtypes.Part(
                                function_response=gtypes.FunctionResponse(
                                    name=fn_name,
                                    response=response_dict,
                                )
                            )
                        ],
                    )
                )
                continue

            if role == "assistant":
                parts: list[gtypes.Part] = []
                text = msg.get("content")
                if text:
                    parts.append(gtypes.Part(text=text))

                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    call_id = tc.get("id", fn_name)
                    call_id_to_name[call_id] = fn_name
                    raw_args = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {"_raw": raw_args}
                    parts.append(
                        gtypes.Part(
                            function_call=gtypes.FunctionCall(
                                name=fn_name,
                                args=args,
                            )
                        )
                    )

                if not parts:
                    parts.append(gtypes.Part(text=""))
                contents.append(gtypes.Content(role="model", parts=parts))
                continue

            # Default: user message
            text = msg.get("content") or ""
            contents.append(
                gtypes.Content(role="user", parts=[gtypes.Part(text=text)])
            )

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    # ── tool schema conversion: OpenAI format → Gemini Tool ───────────

    def _convert_tools(self, tools: list[dict]) -> list[gtypes.Tool]:
        """Convert OpenAI-style tool schemas to Gemini ``Tool`` objects
        with ``function_declarations``.
        """
        declarations: list[gtypes.FunctionDeclaration] = []
        for t in tools:
            fn = t.get("function", t)
            name = fn.get("name", "")
            description = fn.get("description", "")
            parameters = fn.get("parameters", {})
            # ``parameters_json_schema`` accepts a raw JSON Schema dict,
            # which is exactly what the existing tool registry produces.
            declarations.append(
                gtypes.FunctionDeclaration(
                    name=name,
                    description=description,
                    parameters_json_schema=parameters,
                )
            )
        return [gtypes.Tool(function_declarations=declarations)]

    # ── response parsing: Gemini response → OpenAI format ─────────────

    def _parse_response(self, response) -> dict:
        """Convert a Gemini ``GenerateContentResponse`` into the dict the
        agent loop expects: ``{role, content, tool_calls, _finish_reason}``.
        """
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        finish_reason = None

        candidate = None
        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = str(candidate.finish_reason) if candidate.finish_reason else None
            if candidate.content and candidate.content.parts:
                for i, part in enumerate(candidate.content.parts):
                    # Skip thinking parts
                    if getattr(part, "thought", False):
                        continue
                    if part.text:
                        text_parts.append(part.text)
                    if part.function_call:
                        fc = part.function_call
                        tool_calls.append(
                            {
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": fc.name,
                                    "arguments": json.dumps(
                                        fc.args if fc.args else {}
                                    ),
                                },
                            }
                        )

        content = "\n".join(text_parts) if text_parts else None
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else [],
            "_finish_reason": finish_reason,
        }


class LLMError(RuntimeError):
    pass
