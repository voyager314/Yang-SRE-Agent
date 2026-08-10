"""驱动大模型与诊断工具协作的核心执行引擎。"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from pydantic import BaseModel

from sre_agent.core.context_manager import BudgetStatus, ContextManager
from sre_agent.core.llm import LLM
from sre_agent.core.tool import Tool
from sre_agent.core.tool_executor import ToolExecutor, _format_result_for_llm
from sre_agent.utils.streaming import StreamEvent, StreamEventType

_CONVERGE_PROMPT = "上下文预算已接近上限。请立即根据现有调查结果给出最终结论，不要再调用任何工具。"


class EngineResult(BaseModel):
    """一次完整调查的汇总结果。

    ``messages`` 指向调用方传入的消息列表；引擎执行期间会把助手消息和工具
    结果追加到该列表，以便调用方继续进行多轮对话。
    ``converged`` 为 True 表示因上下文预算触发强制收敛，而非模型自然结束。
    """

    answer: str
    tool_calls: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    iterations: int = 0
    converged: bool = False


class Engine:
    """执行"请求模型 -> 调用工具 -> 将结果交还模型"的迭代循环。"""

    def __init__(
        self,
        llm: LLM,
        tool_executor: ToolExecutor,
        max_steps: int = 30,
        max_output_lines: int = 2000,
        context_manager: ContextManager | None = None,
    ):
        self.llm = llm
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.max_output_lines = max_output_lines
        self.context_manager = context_manager

        # 内置工具独立保存，避免与外部工具集混合注册。
        self._builtin_tools: list[Tool] = []
        self._builtin_map: dict[str, Tool] = {}
        if context_manager is not None:
            from sre_agent.core.builtin_tools import make_builtin_tools

            self._builtin_tools = make_builtin_tools(
                context_manager.scratchpad, context_manager.evidence_store
            )
            self._builtin_map = {t.name: t for t in self._builtin_tools}

    def call(self, messages: list[dict[str, Any]]) -> EngineResult:
        """以非流式方式运行调查，并将流事件聚合成一个结果对象。"""

        answer = ""
        all_tool_calls: list[dict[str, Any]] = []
        iterations = 0
        converged = False

        for event in self.call_stream(messages):
            if event.event == StreamEventType.ANSWER_END:
                answer = event.data.get("content", "")
                iterations = event.data.get("iterations", 0)
                converged = event.data.get("converged", False)
            elif event.event == StreamEventType.TOOL_RESULT:
                all_tool_calls.append(event.data)

        return EngineResult(
            answer=answer,
            tool_calls=all_tool_calls,
            messages=messages,
            iterations=iterations,
            converged=converged,
        )

    def call_stream(self, messages: list[dict[str, Any]]) -> Generator[StreamEvent]:
        """逐步产出调查事件，供 CLI 等调用方实时展示执行进度。"""

        cm = self.context_manager

        # 构建完整的工具 Schema 列表：外部工具加内置工具。
        base_tools = self.tool_executor.get_openai_tools()
        builtin_schemas = [t.to_openai_tool() for t in self._builtin_tools]
        all_tools = base_tools + builtin_schemas

        iteration = 0

        while iteration < self.max_steps:
            # 每轮开始前检查上下文预算。
            if cm is not None:
                status = cm.check_budget(messages, all_tools)
                if status == BudgetStatus.CONVERGE:
                    # 预算接近上限时强制收敛，要求模型不调用工具直接作答。
                    yield from self._converge(messages, iteration, cm)
                    return
                elif status == BudgetStatus.COMPRESS:
                    messages[:] = cm.compress_batch(messages)

            # 仅为本次调用将当前记录本注入系统消息，不修改原始消息列表。
            effective = _inject_scratchpad(messages, cm)

            response = self.llm.completion(effective, tools=all_tools or None)

            if response.content:
                yield StreamEvent(
                    event=StreamEventType.AI_MESSAGE,
                    data={"content": response.content},
                )

            if not response.tool_calls:
                yield StreamEvent(
                    event=StreamEventType.ANSWER_END,
                    data={
                        "content": response.content or "",
                        "iterations": iteration + 1,
                        "converged": False,
                    },
                )
                return

            for tc in response.tool_calls:
                yield StreamEvent(
                    event=StreamEventType.TOOL_START,
                    data={
                        "tool_call_id": tc["id"],
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls,
                }
            )

            # 内置工具同步执行，外部工具并行执行。
            builtin_calls = [
                tc for tc in response.tool_calls if tc["function"]["name"] in self._builtin_map
            ]
            external_calls = [
                tc for tc in response.tool_calls if tc["function"]["name"] not in self._builtin_map
            ]

            id_to_name = {tc["id"]: tc["function"]["name"] for tc in response.tool_calls}

            builtin_results = [self._execute_builtin(tc) for tc in builtin_calls]

            external_results = (
                self.tool_executor.execute_parallel(
                    external_calls, max_output_lines=self.max_output_lines
                )
                if external_calls
                else []
            )

            # 外部工具结果返回后立即按需压缩。
            if cm is not None:
                external_results = [
                    _apply_immediate_compress(cm, tr, id_to_name.get(tr["tool_call_id"], ""))
                    for tr in external_results
                ]

            # 写入消息前恢复模型声明的原始调用顺序。
            all_results = builtin_results + external_results
            call_order = {tc["id"]: i for i, tc in enumerate(response.tool_calls)}
            all_results.sort(key=lambda r: call_order.get(r["tool_call_id"], 0))

            for tr in all_results:
                yield StreamEvent(event=StreamEventType.TOOL_RESULT, data=tr)
                messages.append(tr)

            iteration += 1

        yield StreamEvent(
            event=StreamEventType.ANSWER_END,
            data={
                "content": f"已达最大步数 ({self.max_steps})，调查未完成。",
                "iterations": iteration,
                "converged": False,
            },
        )

    def _converge(
        self, messages: list[dict[str, Any]], iteration: int, cm: ContextManager
    ) -> Generator[StreamEvent]:
        """注入收敛提示，要求模型不调用工具直接给出结论。"""

        content = _CONVERGE_PROMPT
        if not cm.scratchpad.is_empty():
            content += f"\n\n当前调查记录：\n{cm.scratchpad.to_yaml()}"

        converge_messages = list(messages) + [{"role": "user", "content": content}]
        response = self.llm.completion(converge_messages, tool_choice="none")
        answer = response.content or ""

        if answer:
            yield StreamEvent(event=StreamEventType.AI_MESSAGE, data={"content": answer})

        yield StreamEvent(
            event=StreamEventType.ANSWER_END,
            data={
                "content": answer,
                "iterations": iteration + 1,
                "converged": True,
            },
        )

    def _execute_builtin(self, tc: dict[str, Any]) -> dict[str, Any]:
        """同步执行内置工具调用，返回 tool 消息字典。"""

        name = tc["function"]["name"]
        tool = self._builtin_map[name]
        args = tc["function"]["arguments"]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {}
        result = tool.invoke(args)
        return {
            "tool_call_id": tc["id"],
            "role": "tool",
            "content": _format_result_for_llm(result),
        }


def _inject_scratchpad(
    messages: list[dict[str, Any]], cm: ContextManager | None
) -> list[dict[str, Any]]:
    """浅拷贝消息列表，并将记录本附加到系统消息。

    原始列表始终不被修改，确保每次 LLM 调用均看到最新记录本，且不会累积旧副本。
    """
    if cm is None or cm.scratchpad.is_empty():
        return messages
    effective = list(messages)
    if effective and effective[0].get("role") == "system":
        sys_msg = dict(effective[0])
        sys_msg["content"] = (
            sys_msg.get("content") or ""
        ) + f"\n\n## 当前调查记录\n{cm.scratchpad.to_yaml()}"
        effective[0] = sys_msg
    return effective


def _apply_immediate_compress(
    cm: ContextManager, tr: dict[str, Any], tool_name: str
) -> dict[str, Any]:
    """按需通过 ContextManager.compress_immediate 压缩工具结果。"""
    original = tr["content"]
    compressed = cm.compress_immediate(tr["tool_call_id"], tool_name, original)
    if compressed is original:
        return tr
    return {**tr, "content": compressed}
