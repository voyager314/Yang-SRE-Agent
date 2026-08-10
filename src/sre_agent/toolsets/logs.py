"""Loki 与 Elasticsearch 日志查询工具。"""

from __future__ import annotations

from typing import Any

import httpx

from sre_agent.core.tool import (
    EnvPrerequisite,
    StructuredToolResult,
    Tool,
    ToolResultStatus,
    Toolset,
)


class LokiQueryTool(Tool):
    """通过 Loki ``query_range`` API 执行 LogQL 查询。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        super().__init__(
            name="loki_query",
            description="Query logs from Loki using LogQL",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "LogQL query expression"},
                    "limit": {
                        "type": "integer",
                        "description": "Max number of log lines (default 100)",
                    },
                },
                "required": ["query"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        """查询 Loki，并把多日志流合并成模型易读的逐行文本。"""

        query = params["query"]
        limit = params.get("limit", 100)
        try:
            resp = httpx.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={"query": query, "limit": limit},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            lines = _format_loki_results(results)
            return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=lines)
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Cannot connect to Loki at {self.base_url}",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


class ElasticsearchQueryTool(Tool):
    """使用 Lucene query string 查询 Elasticsearch 日志索引。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        super().__init__(
            name="elasticsearch_query",
            description="Search logs in Elasticsearch using a query string",
            parameters={
                "type": "object",
                "properties": {
                    "index": {"type": "string", "description": "Index pattern (e.g. logs-*)"},
                    "query": {"type": "string", "description": "Query string (Lucene syntax)"},
                    "size": {"type": "integer", "description": "Max results (default 50)"},
                },
                "required": ["index", "query"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        """执行搜索并按时间倒序返回最近的日志记录。"""

        index = params["index"]
        query = params["query"]
        size = params.get("size", 50)
        # 查询体保持简单且供应商兼容；调用方可通过 index 限定目标索引。
        body = {
            "query": {"query_string": {"query": query}},
            "size": size,
            "sort": [{"@timestamp": {"order": "desc"}}],
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/{index}/_search",
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            lines = _format_es_results(hits)
            return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=lines)
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Cannot connect to Elasticsearch at {self.base_url}",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


def _format_loki_results(results: list[dict[str, Any]]) -> str:
    """保留每条日志所属的流标签，帮助模型区分服务和实例。"""

    lines: list[str] = []
    for stream in results:
        labels = stream.get("stream", {})
        label_str = ", ".join(f'{k}="{v}"' for k, v in labels.items())
        for ts, line in stream.get("values", []):
            lines.append(f"[{label_str}] {line}")
    return "\n".join(lines)


def _format_es_results(hits: list[dict[str, Any]]) -> str:
    """优先提取常见时间与消息字段，未知结构则完整字符串化。"""

    lines: list[str] = []
    for hit in hits:
        source = hit.get("_source", {})
        ts = source.get("@timestamp", "")
        msg = source.get("message", source.get("log", str(source)))
        lines.append(f"[{ts}] {msg}")
    return "\n".join(lines)


def create_logs_toolset(config: dict[str, Any]) -> Toolset | None:
    """根据显式 provider、URL 特征和环境变量选择日志后端。"""

    import os

    provider = config.get("provider", "loki")
    url = config.get("url") or os.environ.get("LOKI_URL") or os.environ.get("ELASTICSEARCH_URL")
    if not url:
        return Toolset(
            name="logs",
            tools=[],
            prerequisites=[EnvPrerequisite(["LOKI_URL"])],
            llm_instructions="Log system is not configured.",
        )

    class LogsToolset(Toolset):
        def compress(self, tool_name: str, raw_output: str) -> str:
            """优先保留 ERROR/WARN 行，其余保留末尾 30 行。"""

            lines = raw_output.split("\n")
            total = len(lines)
            if total <= 60:
                return raw_output

            error_keywords = ("error", "warn", "fatal", "exception", "panic", "critical")
            signal_lines = [
                line for line in lines if any(kw in line.lower() for kw in error_keywords)
            ]
            tail = lines[-30:]

            parts: list[str] = [f"[共 {total} 行，已压缩]"]
            if signal_lines:
                parts.append("--- ERROR/WARN 行 ---")
                parts.extend(signal_lines[:40])
                if len(signal_lines) > 40:
                    parts.append(f"  ... 另有 {len(signal_lines) - 40} 条异常日志")
            parts.append("--- 最近日志 ---")
            parts.extend(tail)
            return "\n".join(parts)

    tools: list[Tool] = []
    if provider == "loki" or "loki" in url.lower():
        tools.append(LokiQueryTool(url))
        instructions = (
            "You have access to Loki for log queries using LogQL.\n"
            'Common patterns: {app="name"} |= "error", '
            '{namespace="prod"} | json | level="error"'
        )
    elif provider == "elasticsearch" or "elastic" in url.lower():
        tools.append(ElasticsearchQueryTool(url))
        instructions = (
            "You have access to Elasticsearch for log queries.\n"
            "Use Lucene query syntax: field:value, AND/OR operators, wildcards."
        )
    else:
        tools.append(LokiQueryTool(url))
        instructions = "You have access to a log system via LogQL."

    return LogsToolset(
        name="logs",
        tools=tools,
        prerequisites=[],
        llm_instructions=instructions,
    )
