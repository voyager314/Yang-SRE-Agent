"""工具注册、查找以及并发执行逻辑。"""

from __future__ import annotations

import concurrent.futures
from typing import Any

from sre_agent.core.tool import StructuredToolResult, Tool, ToolResultStatus


class ToolExecutor:
    """维护可供模型调用的工具表，并负责将结果转换为对话消息。"""

    def __init__(self, max_workers: int = 16):
        self._tools: dict[str, Tool] = {}
        self._max_workers = max_workers

    def register(self, tool: Tool) -> None:
        """按名称注册工具；同名注册会显式替换旧实现。"""

        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        """批量注册一个工具集中的所有工具。"""

        for tool in tools:
            self.register(tool)

    def get_tool(self, name: str) -> Tool | None:
        """查找工具；不存在时返回 ``None``。"""

        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        """按注册顺序返回工具名称。"""

        return list(self._tools.keys())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """生成模型 API 所需的 function calling schema 列表。"""

        return [tool.to_openai_tool() for tool in self._tools.values()]

    def execute(
        self, name: str, params: dict[str, Any], max_output_lines: int = 2000
    ) -> StructuredToolResult:
        """同步执行单个工具，并将未知名称转为结构化错误。"""

        tool = self._tools.get(name)
        if not tool:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Unknown tool: {name}",
                params=params,
            )
        return tool.invoke(params, max_output_lines=max_output_lines)

    def execute_parallel(
        self,
        calls: list[dict[str, Any]],
        max_output_lines: int = 2000,
    ) -> list[dict[str, Any]]:
        """并行执行同一模型响应中的多个工具调用。

        返回值始终恢复为模型原始请求顺序。虽然线程完成顺序不确定，但稳定的
        消息顺序更利于调试，也避免不同运行之间产生无意义差异。
        """

        results: list[dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            # 保存 Future 到原始调用的映射，以便补回 tool_call_id。
            future_to_call = {
                executor.submit(
                    self.execute,
                    call["function"]["name"],
                    _parse_arguments(call["function"]["arguments"]),
                    max_output_lines,
                ): call
                for call in calls
            }
            for future in concurrent.futures.as_completed(future_to_call):
                call = future_to_call[future]
                result = future.result()
                results.append({
                    "tool_call_id": call["id"],
                    "role": "tool",
                    "content": _format_result_for_llm(result),
                })

        # as_completed 按完成时间产出结果，此处恢复模型声明的调用顺序。
        call_order = {call["id"]: i for i, call in enumerate(calls)}
        results.sort(key=lambda r: call_order.get(r["tool_call_id"], 0))
        return results


def _parse_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    """接受 SDK 可能返回的 JSON 字符串或已解析字典。

    无效 JSON 返回空参数，让具体工具通过统一执行路径报告缺失参数，而不让
    整个并行批次在解析阶段中断。
    """

    if isinstance(arguments, dict):
        return arguments
    try:
        import json
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_result_for_llm(result: StructuredToolResult) -> str:
    """把内部结果压缩为模型能直接理解的工具消息文本。"""

    if result.status == ToolResultStatus.SUCCESS:
        return str(result.data) if result.data else "(empty output)"
    elif result.status == ToolResultStatus.NO_DATA:
        return "(no data found)"
    else:
        msg = f"ERROR: {result.error or 'unknown error'}"
        if result.data:
            msg += f"\nPartial output:\n{result.data}"
        return msg
