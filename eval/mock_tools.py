"""基于 Scenario YAML 定义的 Mock 工具，替换真实数据源。

通过继承 src/sre_agent 的 Tool 基类，Mock 工具与引擎的交互
方式与真实工具完全一致——Engine 不知道也不需要知道工具是 Mock 的。
"""

from __future__ import annotations

import re
from typing import Any

from sre_agent.core.tool import StructuredToolResult, Tool, ToolResultStatus, Toolset


class MockTool(Tool):
    """根据场景 YAML 中的预录响应返回匹配结果。

    匹配策略：
    1. ``match`` 字典中的每个字段与 Agent 传入的参数精确比较。
    2. ``match`` 中带 ``_contains`` 后缀的字段做子串匹配。
    3. 空 ``match`` ({}) 匹配所有调用。
    4. 全部不命中时返回 NO_DATA，模拟"查无此数据"。
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        responses: list[dict[str, Any]],
    ) -> None:
        super().__init__(name=name, description=description, parameters=parameters)
        self.responses = responses
        self.call_log: list[dict[str, Any]] = []

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        self.call_log.append(dict(params))

        for resp in self.responses:
            match_spec = resp.get("match", {})
            if self._matches(params, match_spec):
                return self._build_result(resp.get("result", {}))

        return StructuredToolResult(status=ToolResultStatus.NO_DATA)

    def _matches(self, params: dict[str, Any], match_spec: dict[str, Any]) -> bool:
        """检查参数是否匹配给定规格。"""

        if not match_spec:
            return True

        for key, expected in match_spec.items():
            if key.endswith("_contains"):
                real_key = key.removesuffix("_contains")
                value = self._find_param_value(params, real_key)
                if value is None or str(expected).lower() not in str(value).lower():
                    return False
            else:
                value = params.get(key)
                if value is None or str(value).lower() != str(expected).lower():
                    return False

        return True

    @staticmethod
    def _find_param_value(params: dict[str, Any], key: str) -> Any:
        """在参数中查找值，同时检查原始 key 和去掉前缀的 key。

        例如 key="query" 会同时查找 params["query"]。
        """

        if key in params:
            return params[key]
        # 兜底：在所有字符串值参数中搜索。
        for v in params.values():
            if isinstance(v, str):
                return v
        return None

    @staticmethod
    def _build_result(result_spec: dict[str, Any]) -> StructuredToolResult:
        """从场景 YAML 的 result 定义构建 StructuredToolResult。"""

        status_str = result_spec.get("status", "success")
        status = ToolResultStatus(status_str)
        return StructuredToolResult(
            status=status,
            data=result_spec.get("data"),
            error=result_spec.get("error"),
        )


# ────────────────────────────────────────────────────────────
# 已知工具的参数 schema，用于生成 function calling 定义
# ────────────────────────────────────────────────────────────

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "prometheus_query": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "PromQL expression"}},
        "required": ["query"],
    },
    "prometheus_query_range": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "PromQL expression"},
            "start": {"type": "string", "description": "Start time"},
            "end": {"type": "string", "description": "End time"},
            "step": {"type": "string", "description": "Step"},
        },
        "required": ["query", "start", "step"],
    },
    "loki_query": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "LogQL query"},
            "limit": {"type": "integer", "description": "Max lines"},
        },
        "required": ["query"],
    },
    "elasticsearch_query": {
        "type": "object",
        "properties": {
            "index": {"type": "string", "description": "Index pattern"},
            "query": {"type": "string", "description": "Query string"},
            "size": {"type": "integer", "description": "Max results"},
        },
        "required": ["index", "query"],
    },
    "trace_search": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "operation": {"type": "string", "description": "Operation name"},
            "min_duration": {"type": "string", "description": "Min duration"},
            "start": {"type": "string", "description": "Start time"},
            "limit": {"type": "integer", "description": "Max results"},
        },
        "required": [],
    },
    "trace_get": {
        "type": "object",
        "properties": {
            "trace_id": {"type": "string", "description": "Trace ID"},
        },
        "required": ["trace_id"],
    },
    "trace_services": {
        "type": "object",
        "properties": {},
        "required": [],
    },
    "alertmanager_list": {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "Label filter"},
            "silenced": {"type": "boolean", "description": "Include silenced"},
            "inhibited": {"type": "boolean", "description": "Include inhibited"},
        },
        "required": [],
    },
    "alertmanager_silences": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def build_mock_tools(tool_responses: dict[str, list[dict[str, Any]]]) -> list[Tool]:
    """从场景 YAML 的 tool_responses 段构建 Mock 工具列表。"""

    tools: list[Tool] = []
    for tool_name, responses in tool_responses.items():
        schema = _TOOL_SCHEMAS.get(
            tool_name, {"type": "object", "properties": {}, "required": []}
        )
        tool = MockTool(
            name=tool_name,
            description=f"(mock) {tool_name}",
            parameters=schema,
            responses=responses,
        )
        tools.append(tool)
    return tools


def build_mock_toolset(tool_responses: dict[str, list[dict[str, Any]]]) -> Toolset:
    """构建一个包含所有 Mock 工具的 Toolset。"""

    tools = build_mock_tools(tool_responses)
    return Toolset(
        name="mock",
        tools=tools,
        prerequisites=[],
        llm_instructions="You have access to infrastructure diagnostic tools.",
    )
