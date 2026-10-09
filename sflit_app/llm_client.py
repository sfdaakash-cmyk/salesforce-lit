"""OpenAI-compatible client for routing and answering conversations."""

from __future__ import annotations

import logging
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam


class LlmClientError(RuntimeError):
    """Raised when the configured LLM cannot format an answer."""


class OpenAIClient:
    """Concrete LLM adapter used by SalesforceLitService.

    This client is the real implementation of the LLM contract: it routes Salesforce
    questions, answers general chat, and handles MCP-backed Salesforce tool calls.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        #self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY")
        #self.base_url = base_url or os.getenv(
            #"LLM_BASE_URL", "https://openrouter.ai/api/v1"
        #)
        #self.model = model or os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        #self.timeout = timeout or float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
        #self.max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", "512"))
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY")
        self.base_url = base_url or os.getenv(
            "LLM_BASE_URL", "http://localhost:11434/v1"
        )
        self.model = model or os.getenv("LLM_MODEL", "qwen3:8b")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    @staticmethod
    def _flatten_text(value: Any) -> str:
        """Normalize text from OpenAI-compatible responses and streamed deltas."""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(OpenAIClient._flatten_text(item) for item in value)
        if isinstance(value, dict):
            for key in (
                "text",
                "content",
                "reasoning",
                "reasoning_content",
                "thinking",
                "thought",
            ):
                candidate = value.get(key)
                if candidate is not None:
                    return OpenAIClient._flatten_text(candidate)
            return "".join(
                OpenAIClient._flatten_text(item) for item in value.values()
            )
        return ""

    @classmethod
    def _message_text(cls, message: Any) -> str:
        """Fetch the primary answer text while tolerating reasoning-visible models."""
        for key in (
            "content",
            "reasoning_content",
            "reasoning",
            "thinking",
            "thought",
        ):
            text = cls._flatten_text(getattr(message, key, None)).strip()
            if text:
                return text
        if isinstance(message, dict):
            for key in (
                "content",
                "reasoning_content",
                "reasoning",
                "thinking",
                "thought",
            ):
                text = cls._flatten_text(message.get(key)).strip()
                if text:
                    return text
        return ""

    def answer_salesforce(
        self,
        question: str,
        release: str,
        collections: list[str] | None = None,
        available_collections: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        reading_context: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Clarify Salesforce requests, then answer using only MCP-backed tools."""

        project_root = Path(__file__).resolve().parent.parent
        search_guide = (project_root / "search_guide.md").read_text(encoding="utf-8")
        formatting_instructions = (
            project_root / "response_formatting_instructions.md"
        ).read_text(encoding="utf-8")
        collection_catalog = available_collections or []
        system_prompt = (
            "You are a Salesforce documentation assistant. Answer general conversation naturally, "
            "but this request has been identified as Salesforce-related. First decide whether the "
            "request is specific enough to research. If it is vague, ask one concise clarification "
            "question and do not call tools. Before calling any tools, follow the supplied search "
            "guide to formulate a focused MCP query. Choose the best matching collection names "
            "from the supplied catalog unless the user selected a collection scope. If you are not sure"
            "which collection to use, provide a list of recommended collections and ask to select one or more. If the user selected a collection scope, "
            "Every collection value in a tool call must exactly match a catalog entry; do not invent "
            "source roots, aliases, or shortened names. If a tool returns valid_collections, "
            "retry with exact entries from that list. Search, fetch "
            "the most relevant documents, and read their full content before answering. You may "
            "repeat search and fetch calls as needed. Use only tool results; if the literature does "
            "not support an answer, say so. If the model exposes visible reasoning or working notes, "
            "show them transparently before the final answer. Before writing the final response, "
            "follow the supplied response-formatting instructions. "
            f"Target release: {release}. "
            f"User-selected collections: {', '.join(collections) if collections else 'none'}. "
            f"Available collection catalog: {', '.join(collection_catalog) if collection_catalog else 'unavailable'}.\n\n"
            f"Search guide:\n{search_guide}\n\n"
            f"Response formatting instructions:\n{formatting_instructions}"
        )
        if reading_context:
            system_prompt += " Use the selected Salesforce document below as primary context."
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *([{"role": "user", "content": f"Selected document:\n{reading_context}"}] if reading_context else []),
            *self._conversation_messages(history, question),
        ]
        return self._complete_with_tools(messages, tools, tool_executor, on_token)

    def _complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        try:
            empty_response_retried = False
            for _ in range(8):
                request: dict[str, Any] = {
                    "model": self.model,
                    "temperature": 0,
                    #"max_tokens": self.max_tokens,
                    "messages": messages
                }
                if tools and tool_executor:
                    request["tools"] = tools

                logger.info("answer_salesforce: calling LLM with %s messages", len(messages))
                logger.debug("answer_salesforce: messages=%s", messages)
                logger.debug("answer_salesforce: request=%s", request)
                response = self.client.chat.completions.create(**request)
                choices = getattr(response, "choices", None) or []
                if not choices:
                    raise LlmClientError("LLM returned no completion choices")
                choice = choices[0]
                message = choice.message
                tool_calls = getattr(message, "tool_calls", None) or []
                if not tool_calls or not tool_executor:
                    answer = self._message_text(message)
                    if answer:
                        if on_token:
                            return self._stream_completion(messages, on_token)
                        return answer
                    finish_reason = getattr(choice, "finish_reason", "unknown")
                    if empty_response_retried:
                        raise LlmClientError(
                            "LLM returned an empty response "
                            f"(finish_reason={finish_reason})"
                        )
                    logger.warning(
                        "answer_salesforce: empty completion | finish_reason=%s; retrying once",
                        finish_reason,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was empty. Continue by either using an "
                                "available documentation tool or returning a concise, grounded "
                                "answer. Do not return an empty response."
                            ),
                        }
                    )
                    empty_response_retried = True
                    continue
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.function.name,
                                    "arguments": call.function.arguments,
                                },
                            }
                            for call in tool_calls
                        ],
                    }
                )
                for call in tool_calls:
                    arguments = json.loads(call.function.arguments or "{}")
                    result = tool_executor(call.function.name, arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(result),
                        }
                    )
            return self._finalize_tool_response(messages, on_token)
        except LlmClientError:
            raise
        except Exception as exc:
            logger.exception("Salesforce tool-enabled LLM call failed")
            raise LlmClientError(f"LLM Salesforce service is unavailable: {exc}") from exc

    def _finalize_tool_response(
        self,
        messages: list[dict[str, Any]],
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Ask for a final answer without tools after the bounded retrieval loop."""

        messages.append(
            {
                "role": "user",
                "content": (
                    "Use the Salesforce tool results already provided. Stop calling tools and "
                    "return the best concise grounded answer now. If the results are insufficient, "
                    "say that clearly."
                ),
            }
        )
        if on_token:
            return self._stream_completion(messages, on_token)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            #max_tokens=self.max_tokens,
            messages=cast(list[ChatCompletionMessageParam], messages),
        )
        answer = self._message_text(response.choices[0].message)
        if not answer:
            raise LlmClientError("LLM returned an empty response after tool retrieval")
        return answer

    def _stream_completion(
        self,
        messages: list[dict[str, Any]],
        on_token: Callable[[str], None],
    ) -> str:
        """Stream a final completion and forward each text delta to the caller."""

        stream = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=cast(list[ChatCompletionMessageParam], messages),
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            reasoning = self._flatten_text(
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
                or getattr(delta, "thinking", None)
            ).strip()
            if reasoning:
                on_token(reasoning)
            content = self._flatten_text(getattr(delta, "content", None))
            if content:
                parts.append(content)
                on_token(content)
        answer = "".join(parts).strip()
        if not answer:
            raise LlmClientError("LLM returned an empty streamed response")
        return answer

    def is_salesforce_question(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> bool:
        """Classify a turn before SalesforceLitService decides whether to call MCP.

        Purpose: route Salesforce questions to the docs workflow while keeping unrelated chat in
        the normal assistant flow.
        """

        logger.info("is_salesforce_question: start | history=%s | question=%r", bool(history), question)
        system_prompt = (
            """
            You are a helpful assistant that classifies user questions as either Salesforce-related or general.
            A Salesforce-related question is about Salesforce, its products, APIs, metadata, Apex, Lightning, CRM, releases, or Salesforce documentation.
            A general question is about anything else.
            Do not make up information or provide answers outside of the supplied context.
            """
        )
        user_prompt = (
            """
            Classify the latest message to help me decide if it is Salesforce-related.
            """
        )
        try:
            response = self.client.chat.completions.create(
                model= self.model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    },
                    *cast(
                        list[ChatCompletionMessageParam],
                        self._conversation_messages(history, question),
                    ),
                ],
            )
            classification = (response.choices[0].message.content or "").strip()
            is_salesforce = "SALESFORCE" in classification.upper()
            logger.info("is_salesforce_question: result=%s | raw=%r", is_salesforce, classification)
            return is_salesforce
        except Exception as exc:
            logger.exception("is_salesforce_question: LLM routing failed")
            raise LlmClientError(f"LLM routing service is unavailable: {exc}") from exc

    def answer_general(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Answer a non-Salesforce turn as a normal multi-turn assistant.

        Purpose: keep general conversation support separate from the release-note lookup flow and
        avoid forcing irrelevant topics through the Salesforce docs path.
        """

        logger.info("answer_general: start | history=%s | question=%r", bool(history), question)
        system_prompt = (
            "You are a helpful conversational assistant. Answer naturally and clearly. "
            "If the model exposes visible reasoning or working notes, show them transparently before the final answer. "
            "Follow the supplied response-formatting instructions before writing your answer.\n\n"
            "Response formatting instructions:\n"
            f"{(Path(__file__).resolve().parent.parent / 'response_formatting_instructions.md').read_text(encoding='utf-8')}"
        )
        try:
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                },
                *cast(
                    list[ChatCompletionMessageParam],
                    self._conversation_messages(history, question),
                ),
            ]
            if on_token:
                answer = self._stream_completion(messages, on_token)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0,
                    #max_tokens=self.max_tokens,
                    messages=messages,
                )
                answer = self._message_text(response.choices[0].message)
        except Exception as exc:
            logger.exception("answer_general: LLM chat failed")
            raise LlmClientError(f"LLM chat service is unavailable: {exc}") from exc
        if not answer:
            raise LlmClientError("LLM returned an empty response")
        logger.info("answer_general: response received | length=%s", len(answer))
        return answer

    @staticmethod
    def _conversation_messages(
        history: list[dict[str, str]] | None, question: str
    ) -> list[dict[str, str]]:
        # Keep only the most recent user/assistant turns so follow-up questions can be resolved
        # accurately without sending the full session history into every model call.
        messages = [
            {"role": item["role"], "content": item["content"]}
            for item in (history or [])[-10:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        messages.append({"role": "user", "content": question})
        return messages
