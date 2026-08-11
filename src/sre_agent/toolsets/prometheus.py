"""Prometheus 即时查询与时间范围查询工具。"""

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
from sre_agent.utils.time import parse_relative_time


class PrometheusQueryTool(Tool):
    """调用 Prometheus HTTP API 执行即时 PromQL 查询。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        super().__init__(
            name="prometheus_query",
            description="Execute an instant PromQL query against Prometheus",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL expression"},
                },
                "required": ["query"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        """执行查询，并统一处理协议错误、HTTP 错误和连接错误。"""

        query = params["query"]
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                return StructuredToolResult(
                    status=ToolResultStatus.ERROR,
                    error=data.get("error", "Query failed"),
                )
            results = data.get("data", {}).get("result", [])
            if not results:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS, data=_format_results(results)
            )
        except httpx.HTTPStatusError as e:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"HTTP {e.response.status_code}: {e.response.text[:500]}",
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Cannot connect to Prometheus at {self.base_url}",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


class PrometheusRangeQueryTool(Tool):
    """查询一段时间内的指标序列，支持简写的相对开始时间。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        super().__init__(
            name="prometheus_query_range",
            description="Execute a range PromQL query with start/end/step parameters",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL expression"},
                    "start": {"type": "string", "description": "Start time (e.g. -1h, RFC3339)"},
                    "end": {"type": "string", "description": "End time (default: now)"},
                    "step": {
                        "type": "string",
                        "description": "Query resolution step (e.g. 60s, 5m)",
                    },
                },
                "required": ["query", "start", "step"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        """解析时间边界后调用 Prometheus ``query_range`` 接口。"""

        # time 仅供范围查询使用，延迟导入避免污染模块级命名空间。
        import time

        query = params["query"]
        start = params["start"]
        step = params["step"]
        end = params.get("end", "now")

        # 起止时间共享同一个 now，避免解析期间的时间差造成边界漂移。
        now = time.time()
        start_ts = parse_relative_time(start, now)
        end_ts = parse_relative_time(end, now) if end != "now" else now

        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": query, "start": start_ts, "end": end_ts, "step": step},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                return StructuredToolResult(
                    status=ToolResultStatus.ERROR,
                    error=data.get("error", "Query failed"),
                )
            results = data.get("data", {}).get("result", [])
            if not results:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS, data=_format_results(results)
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Cannot connect to Prometheus at {self.base_url}",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


def _format_results(results: list[dict[str, Any]]) -> str:
    """格式化 Prometheus vector/matrix，并限制每条序列为最近十个点。"""

    lines: list[str] = []
    for r in results:
        metric = r.get("metric", {})
        label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
        if "value" in r:
            ts, val = r["value"]
            lines.append(f"{{{label_str}}} => {val}")
        elif "values" in r:
            lines.append(f"{{{label_str}}}:")
            # 防止高分辨率范围查询产生过长提示词，同时报告总点数供判断。
            for ts, val in r["values"][-10:]:
                lines.append(f"  [{ts}] {val}")
            if len(r["values"]) > 10:
                lines.append(f"  ... ({len(r['values'])} total points)")
    return "\n".join(lines)


def create_prometheus_toolset(config: dict[str, Any]) -> Toolset | None:
    """从工具集配置或环境变量创建 Prometheus 工具集。"""

    import os

    url = config.get("url") or config.get("prometheus_url") or os.environ.get("PROMETHEUS_URL")
    if not url:
        return Toolset(
            name="prometheus",
            tools=[],
            prerequisites=[EnvPrerequisite(["PROMETHEUS_URL"])],
            llm_instructions="Prometheus is not configured.",
        )

    class PrometheusToolset(Toolset):
        def compress(self, tool_name: str, raw_output: str) -> str:
            """保留所有指标序列，折叠每条序列超出的时间点。

            Prometheus 输出由 _format_results() 格式化，每行是一个时间点或序列头；
            序列数量通常有限，压缩重点是长时间范围查询产生的密集时间点。
            """

            lines = raw_output.split("\n")
            total = len(lines)
            if total <= 80:
                return raw_output

            # 按序列头（不以空格开头）分组，每组最多保留 5 个时间点
            compressed: list[str] = [f"[共 {total} 行，时间点已压缩]"]
            current_series: list[str] = []
            for line in lines:
                if line and not line.startswith(" "):
                    if current_series:
                        compressed.extend(current_series[:5])
                        if len(current_series) > 5:
                            compressed.append(f"  ... ({len(current_series) - 5} 个时间点已折叠)")
                    current_series = [line]
                else:
                    current_series.append(line)
            if current_series:
                compressed.extend(current_series[:5])
                if len(current_series) > 5:
                    compressed.append(f"  ... ({len(current_series) - 5} 个时间点已折叠)")
            return "\n".join(compressed)

    tools = [
        PrometheusQueryTool(url),
        PrometheusRangeQueryTool(url),
    ]

    return PrometheusToolset(
        name="prometheus",
        tools=tools,
        prerequisites=[],
        llm_instructions=(
            "You have access to Prometheus metrics via PromQL.\n"
            "Use prometheus_query for instant queries and "
            "prometheus_query_range for time-series data.\n"
            "Common patterns: rate(), increase(), histogram_quantile(), avg by()."
        ),
    )
