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


class PrometheusQueryTool(Tool):
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
        import time

        query = params["query"]
        start = params["start"]
        step = params["step"]
        end = params.get("end", "now")

        now = time.time()
        start_ts = _parse_relative_time(start, now)
        end_ts = _parse_relative_time(end, now) if end != "now" else now

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


def _parse_relative_time(value: str, now: float) -> float:
    if value.startswith("-"):
        unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit = value[-1]
        num = int(value[1:-1])
        return now - num * unit_map.get(unit, 1)
    try:
        return float(value)
    except ValueError:
        return now


def _format_results(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in results:
        metric = r.get("metric", {})
        label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
        if "value" in r:
            ts, val = r["value"]
            lines.append(f"{{{label_str}}} => {val}")
        elif "values" in r:
            lines.append(f"{{{label_str}}}:")
            for ts, val in r["values"][-10:]:
                lines.append(f"  [{ts}] {val}")
            if len(r["values"]) > 10:
                lines.append(f"  ... ({len(r['values'])} total points)")
    return "\n".join(lines)


def create_prometheus_toolset(config: dict[str, Any]) -> Toolset | None:
    import os

    url = config.get("url") or config.get("prometheus_url") or os.environ.get("PROMETHEUS_URL")
    if not url:
        return Toolset(
            name="prometheus",
            tools=[],
            prerequisites=[EnvPrerequisite(["PROMETHEUS_URL"])],
            llm_instructions="Prometheus is not configured.",
        )

    tools = [
        PrometheusQueryTool(url),
        PrometheusRangeQueryTool(url),
    ]

    return Toolset(
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
