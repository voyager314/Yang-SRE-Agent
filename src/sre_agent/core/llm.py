"""大模型抽象接口及基于 LiteLLM 的默认实现。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import litellm
from pydantic import BaseModel


class ModelResponse(BaseModel):
    """将不同模型供应商的响应归一化为引擎可消费的结构。"""

    content: str | None = None
    tool_calls: list[dict[str, Any]] = []
    raw: Any = None


class LLM(ABC):
    """模型适配器协议。

    新增供应商实现时只需实现该接口，核心引擎无需了解具体 SDK 或响应类型。
    """

    @abstractmethod
    def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ModelResponse:
        """根据对话生成一次响应，可选地允许模型调用工具。"""

        ...

    @abstractmethod
    def count_tokens(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> int:
        """估算对话占用的 token 数。"""

        ...

    @abstractmethod
    def get_context_window_size(self) -> int:
        """返回模型支持的最大输入上下文长度。"""

        ...


class DefaultLLM(LLM):
    """通过 LiteLLM 统一调用 OpenAI、Anthropic 等兼容模型。"""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
    ):
        """记录模型标识和可选的供应商连接参数。"""

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
        """调用 LiteLLM，并把 SDK 对象转换成稳定的内部数据结构。"""

        # 仅传递明确配置的可选参数，让 LiteLLM 保留供应商自身的默认行为。
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

        # 引擎和测试只依赖普通字典，不直接泄漏 LiteLLM 的响应对象类型。
        message = response.choices[0].message  # pyright: ignore[reportAttributeAccessIssue]
        tool_calls_raw = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls_raw.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )

        return ModelResponse(
            content=message.content,
            tool_calls=tool_calls_raw,
            raw=response,
        )

    def count_tokens(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> int:
        """优先使用模型分词器计数，失败时退化为字符数近似值。"""

        try:
            return litellm.token_counter(model=self.model, messages=messages)
        except Exception:
            # 四个字符约一个 token 只是保守兜底，不用于精确计费。
            total = 0
            for msg in messages:
                content = msg.get("content", "")
                if content:
                    total += len(content) // 4
            return total

    def get_context_window_size(self) -> int:
        """查询模型元数据；未知模型或查询失败时采用 128K 默认值。"""

        try:
            info = litellm.get_model_info(self.model)
            return info.get("max_input_tokens", 128000) if info else 128000  # pyright: ignore[reportReturnType]
        except Exception:
            return 128000
