from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import litellm
from pydantic import BaseModel


class ModelResponse(BaseModel):
    content: str | None = None
    tool_calls: list[dict[str, Any]] = []
    raw: Any = None


class LLM(ABC):
    @abstractmethod
    def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ModelResponse: ...

    @abstractmethod
    def count_tokens(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> int: ...

    @abstractmethod
    def get_context_window_size(self) -> int: ...


class DefaultLLM(LLM):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.api_version = api_version

    def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_version:
            kwargs["api_version"] = self.api_version
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        response = litellm.completion(**kwargs)

        message = response.choices[0].message
        tool_calls_raw = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls_raw.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })

        return ModelResponse(
            content=message.content,
            tool_calls=tool_calls_raw,
            raw=response,
        )

    def count_tokens(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> int:
        try:
            return litellm.token_counter(model=self.model, messages=messages)
        except Exception:
            total = 0
            for msg in messages:
                content = msg.get("content", "")
                if content:
                    total += len(content) // 4
            return total

    def get_context_window_size(self) -> int:
        try:
            info = litellm.get_model_info(self.model)
            return info.get("max_input_tokens", 128000) if info else 128000
        except Exception:
            return 128000
