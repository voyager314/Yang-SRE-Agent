from __future__ import annotations

import concurrent.futures
from typing import Any

from sre_agent.core.tool import StructuredToolResult, Tool, ToolResultStatus


class ToolExecutor:
    def __init__(self, max_workers: int = 16):
        self._tools: dict[str, Tool] = {}
        self._max_workers = max_workers

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def execute(
        self, name: str, params: dict[str, Any], max_output_lines: int = 2000
    ) -> StructuredToolResult:
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
        results: list[dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
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

        call_order = {call["id"]: i for i, call in enumerate(calls)}
        results.sort(key=lambda r: call_order.get(r["tool_call_id"], 0))
        return results


def _parse_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        import json
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_result_for_llm(result: StructuredToolResult) -> str:
    if result.status == ToolResultStatus.SUCCESS:
        return str(result.data) if result.data else "(empty output)"
    elif result.status == ToolResultStatus.NO_DATA:
        return "(no data found)"
    else:
        msg = f"ERROR: {result.error or 'unknown error'}"
        if result.data:
            msg += f"\nPartial output:\n{result.data}"
        return msg
