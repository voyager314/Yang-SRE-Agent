"""Distributed tracing toolset supporting Tempo and Jaeger backends."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from sre_agent.core.tool import (
    EnvPrerequisite,
    StructuredToolResult,
    Tool,
    ToolResultStatus,
    Toolset,
)
from sre_agent.utils.time import parse_relative_time


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    start_us: int
    duration_us: int
    status_code: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TraceSummary:
    trace_id: str
    root_service: str
    root_operation: str
    duration_ms: float
    span_count: int
    error_count: int
    start_time: float = 0.0


@runtime_checkable
class TracingBackend(Protocol):
    def search_traces(self, params: dict[str, Any]) -> list[TraceSummary]: ...
    def get_trace(self, trace_id: str) -> list[Span]: ...
    def list_services(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Tempo Backend
# ---------------------------------------------------------------------------

class TempoBackend:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def search_traces(self, params: dict[str, Any]) -> list[TraceSummary]:
        raw_query = params.get("raw_query")
        if raw_query:
            api_params: dict[str, Any] = {"q": raw_query}
        else:
            parts: list[str] = []
            if params.get("service"):
                parts.append(f'resource.service.name="{params["service"]}"')
            if params.get("operation"):
                parts.append(f'name="{params["operation"]}"')
            if params.get("min_duration"):
                parts.append(f'duration>{params["min_duration"]}')
            if params.get("max_duration"):
                parts.append(f'duration<{params["max_duration"]}')
            if params.get("tags"):
                for k, v in params["tags"].items():
                    parts.append(f'.{k}="{v}"')
            q = "{" + " && ".join(parts) + "}" if parts else "{}"
            api_params = {"q": q}

        if params.get("start"):
            now = time.time()
            api_params["start"] = int(parse_relative_time(params["start"], now))
            api_params["end"] = int(now)
        if params.get("limit"):
            api_params["limit"] = params["limit"]

        resp = httpx.get(
            f"{self.base_url}/api/search", params=api_params, timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._to_summary(t) for t in data.get("traces", [])]

    def _to_summary(self, t: dict[str, Any]) -> TraceSummary:
        return TraceSummary(
            trace_id=t.get("traceID", ""),
            root_service=t.get("rootServiceName", ""),
            root_operation=t.get("rootTraceName", ""),
            duration_ms=t.get("durationMs", 0),
            span_count=t.get("spanSets", [{}])[0].get("matched", 0)
                if t.get("spanSets") else t.get("spanCount", 0),
            error_count=t.get("errorCount", 0),
            start_time=t.get("startTimeUnixNano", 0) / 1e9,
        )

    def get_trace(self, trace_id: str) -> list[Span]:
        resp = httpx.get(
            f"{self.base_url}/api/traces/{trace_id}", timeout=30.0,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_otlp_spans(data)

    def list_services(self) -> list[str]:
        resp = httpx.get(
            f"{self.base_url}/api/v2/search/tag/service.name/values", timeout=15.0
        )
        resp.raise_for_status()
        data = resp.json()
        return [v.get("id", v.get("value", "")) for v in data.get("tagValues", [])]

# ---------------------------------------------------------------------------
# Jaeger Backend
# ---------------------------------------------------------------------------

class JaegerBackend:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def search_traces(self, params: dict[str, Any]) -> list[TraceSummary]:
        service = params.get("service")
        if not service:
            raise ValueError("service parameter is required for Jaeger backend")
        api_params: dict[str, Any] = {"service": service}
        if params.get("operation"):
            api_params["operation"] = params["operation"]
        if params.get("min_duration"):
            api_params["minDuration"] = params["min_duration"]
        if params.get("max_duration"):
            api_params["maxDuration"] = params["max_duration"]
        if params.get("tags"):
            import json
            api_params["tags"] = json.dumps(params["tags"])
        if params.get("start"):
            now = time.time()
            start_ts = parse_relative_time(params["start"], now)
            api_params["start"] = int(start_ts * 1_000_000)
            api_params["end"] = int(now * 1_000_000)
        if params.get("limit"):
            api_params["limit"] = params["limit"]

        resp = httpx.get(
            f"{self.base_url}/api/traces", params=api_params, timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._to_summary(t) for t in data.get("data", [])]

    def _to_summary(self, t: dict[str, Any]) -> TraceSummary:
        spans = t.get("spans", [])
        processes = t.get("processes", {})
        root = spans[0] if spans else {}
        root_proc = processes.get(root.get("processID", ""), {})
        error_count = sum(
            1 for s in spans
            if any(tag.get("key") == "error" and tag.get("value") for tag in s.get("tags", []))
            or any(tag.get("key") == "otel.status_code" and tag.get("value") == "ERROR" for tag in s.get("tags", []))
        )
        duration_us = root.get("duration", 0)
        return TraceSummary(
            trace_id=t.get("traceID", ""),
            root_service=root_proc.get("serviceName", ""),
            root_operation=root.get("operationName", ""),
            duration_ms=duration_us / 1000.0,
            span_count=len(spans),
            error_count=error_count,
            start_time=root.get("startTime", 0) / 1e6,
        )

    def get_trace(self, trace_id: str) -> list[Span]:
        resp = httpx.get(
            f"{self.base_url}/api/traces/{trace_id}", timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()
        traces = data.get("data", [])
        if not traces:
            return []
        return _parse_jaeger_spans(traces[0])

    def list_services(self) -> list[str]:
        resp = httpx.get(f"{self.base_url}/api/services", timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])


# ---------------------------------------------------------------------------
# Span Parsers
# ---------------------------------------------------------------------------

def _parse_otlp_spans(data: dict[str, Any]) -> list[Span]:
    spans: list[Span] = []
    for rs in data.get("batches", data.get("resourceSpans", [])):
        resource = rs.get("resource", {})
        service_name = ""
        for attr in resource.get("attributes", []):
            if attr.get("key") == "service.name":
                service_name = attr.get("value", {}).get("stringValue", "")
                break
        for ss in rs.get("scopeSpans", rs.get("instrumentationLibrarySpans", [])):
            for s in ss.get("spans", []):
                attrs = {}
                for a in s.get("attributes", []):
                    val = a.get("value", {})
                    v = val.get("stringValue") or val.get("intValue") or val.get("boolValue", "")
                    attrs[a["key"]] = v
                spans.append(Span(
                    trace_id=s.get("traceId", ""),
                    span_id=s.get("spanId", ""),
                    parent_span_id=s.get("parentSpanId") or None,
                    service=service_name,
                    operation=s.get("name", ""),
                    start_us=int(s.get("startTimeUnixNano", 0)) // 1000,
                    duration_us=(int(s.get("endTimeUnixNano", 0)) - int(s.get("startTimeUnixNano", 0))) // 1000,
                    status_code=s.get("status", {}).get("code", 0),
                    attributes=attrs,
                    events=s.get("events", []),
                ))
    return spans

def _parse_jaeger_spans(trace_data: dict[str, Any]) -> list[Span]:
    spans: list[Span] = []
    processes = trace_data.get("processes", {})
    for s in trace_data.get("spans", []):
        proc = processes.get(s.get("processID", ""), {})
        attrs = {}
        for tag in s.get("tags", []):
            attrs[tag["key"]] = tag.get("value", "")
        status_code = 0
        if attrs.get("otel.status_code") == "ERROR" or attrs.get("error") is True:
            status_code = 2
        refs = s.get("references", [])
        parent_id = None
        for ref in refs:
            if ref.get("refType") == "CHILD_OF":
                parent_id = ref.get("spanID")
                break
        spans.append(Span(
            trace_id=s.get("traceID", ""),
            span_id=s.get("spanID", ""),
            parent_span_id=parent_id,
            service=proc.get("serviceName", ""),
            operation=s.get("operationName", ""),
            start_us=s.get("startTime", 0),
            duration_us=s.get("duration", 0),
            status_code=status_code,
            attributes=attrs,
            events=[{"name": log.get("operationName", "log"), "attributes": log.get("fields", [])} for log in s.get("logs", [])],
        ))
    return spans


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_ATTR_BLACKLIST_PREFIXES = ("otel.library.", "telemetry.sdk.")
_ATTR_BLACKLIST_KEYS = frozenset({
    "thread.id", "thread.name", "otel.status_code", "otel.status_description",
    "span.kind", "internal.span.format",
})


def _filter_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v for k, v in attrs.items()
        if k not in _ATTR_BLACKLIST_KEYS
        and not any(k.startswith(p) for p in _ATTR_BLACKLIST_PREFIXES)
    }


def _format_span_attrs(attrs: dict[str, Any], max_show: int = 4) -> str:
    filtered = _filter_attrs(attrs)
    if not filtered:
        return ""
    items = list(filtered.items())[:max_show]
    parts = [f"{k}={v}" for k, v in items]
    extra = len(filtered) - max_show
    if extra > 0:
        parts.append(f"+{extra} more")
    return " [" + ", ".join(parts) + "]"


def _build_span_tree(spans: list[Span]) -> dict[str | None, list[Span]]:
    children: dict[str | None, list[Span]] = {}
    for s in sorted(spans, key=lambda x: x.start_us):
        children.setdefault(s.parent_span_id, []).append(s)
    return children


def _render_span_tree(spans: list[Span]) -> str:
    if not spans:
        return "(empty trace)"
    children = _build_span_tree(spans)
    span_map = {s.span_id: s for s in spans}
    roots = children.get(None, [])
    if not roots:
        all_ids = {s.span_id for s in spans}
        parent_ids = {s.parent_span_id for s in spans if s.parent_span_id}
        missing_parents = parent_ids - all_ids
        for pid in missing_parents:
            if pid in children:
                roots.extend(children[pid])
                break
        if not roots:
            roots = [spans[0]]

    lines: list[str] = []

    def walk(span: Span, prefix: str, is_last: bool, parent_duration_us: int | None):
        connector = "└─ " if is_last else "├─ "
        dur_ms = span.duration_us / 1000.0
        line = f"{prefix}{connector}{span.service}::{span.operation} ({dur_ms:.1f}ms)"

        annotations: list[str] = []
        if span.status_code == 2:
            annotations.append("❌ ERROR")
        if (parent_duration_us is not None
                and span.duration_us > parent_duration_us * 0.5
                and span.duration_us > 100_000):
            annotations.append("⚠️ SLOW")
        if annotations:
            line += " " + " ".join(annotations)

        attr_str = _format_span_attrs(span.attributes)
        if attr_str:
            line += attr_str
        lines.append(line)

        child_prefix = prefix + ("   " if is_last else "│  ")
        kids = children.get(span.span_id, [])
        for i, child in enumerate(kids):
            walk(child, child_prefix, i == len(kids) - 1, span.duration_us)

    for i, root in enumerate(roots):
        walk(root, "", i == len(roots) - 1, None)

    return "\n".join(lines)

def _format_search_results(summaries: list[TraceSummary]) -> str:
    if not summaries:
        return ""
    header = f"{'TRACE ID':<34} {'SERVICE':<20} {'OPERATION':<25} {'DURATION':>10} {'SPANS':>6} {'ERRORS':>6}"
    lines = [header, "-" * len(header)]
    for s in summaries:
        lines.append(
            f"{s.trace_id:<34} {s.root_service:<20} {s.root_operation:<25} "
            f"{s.duration_ms:>8.1f}ms {s.span_count:>6} {s.error_count:>6}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool Classes
# ---------------------------------------------------------------------------

class TraceSearchTool(Tool):
    def __init__(self, backend: TracingBackend, provider: str):
        self._backend = backend
        self._provider = provider
        super().__init__(
            name="trace_search",
            description="Search traces by service, operation, duration, and tags",
            parameters={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service name to filter by"},
                    "operation": {"type": "string", "description": "Operation name to filter by"},
                    "min_duration": {"type": "string", "description": "Minimum duration (e.g. 500ms, 1s)"},
                    "max_duration": {"type": "string", "description": "Maximum duration"},
                    "tags": {"type": "object", "description": "Key-value tag filters"},
                    "start": {"type": "string", "description": "Time range start (e.g. -1h, -30m)"},
                    "limit": {"type": "integer", "description": "Max results (default 20)"},
                    "raw_query": {"type": "string", "description": "Raw TraceQL query (Tempo only)"},
                },
                "required": [],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        if params.get("raw_query") and self._provider == "jaeger":
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error="raw_query is only supported with Tempo backend",
            )
        if self._provider == "jaeger" and not params.get("service"):
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error="service parameter is required for Jaeger backend",
            )
        try:
            summaries = self._backend.search_traces(params)
            if not summaries:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS,
                data=_format_search_results(summaries),
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error="Cannot connect to tracing backend",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


class TraceGetTool(Tool):
    def __init__(self, backend: TracingBackend):
        self._backend = backend
        super().__init__(
            name="trace_get",
            description="Get full span tree for a trace by ID",
            parameters={
                "type": "object",
                "properties": {
                    "trace_id": {"type": "string", "description": "Trace ID to retrieve"},
                },
                "required": ["trace_id"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        trace_id = params["trace_id"]
        try:
            spans = self._backend.get_trace(trace_id)
            if not spans:
                return StructuredToolResult(
                    status=ToolResultStatus.ERROR,
                    error=f"Trace {trace_id} not found",
                )
            tree = _render_span_tree(spans)
            summary = (
                f"Trace: {trace_id}\n"
                f"Spans: {len(spans)} | "
                f"Errors: {sum(1 for s in spans if s.status_code == 2)}\n\n"
            )
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS, data=summary + tree
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return StructuredToolResult(
                    status=ToolResultStatus.ERROR,
                    error=f"Trace {trace_id} not found",
                )
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"HTTP {e.response.status_code}",
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error="Cannot connect to tracing backend",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


class TraceServicesTool(Tool):
    def __init__(self, backend: TracingBackend):
        self._backend = backend
        super().__init__(
            name="trace_services",
            description="List available services in the tracing system",
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        try:
            services = self._backend.list_services()
            if not services:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS,
                data="\n".join(sorted(services)),
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error="Cannot connect to tracing backend",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))

# ---------------------------------------------------------------------------
# Factory & Provider Detection
# ---------------------------------------------------------------------------

def _detect_provider(url: str) -> str:
    lower = url.lower()
    if "tempo" in lower:
        return "tempo"
    if "jaeger" in lower or ":16686" in lower:
        return "jaeger"
    try:
        resp = httpx.get(f"{url.rstrip('/')}/api/search/tags", timeout=5.0)
        if resp.status_code == 200:
            return "tempo"
    except Exception:
        pass
    return "jaeger"


def create_tracing_toolset(config: dict[str, Any]) -> Toolset | None:
    import os

    url = (
        config.get("url")
        or os.environ.get("TEMPO_URL")
        or os.environ.get("JAEGER_URL")
        or os.environ.get("TRACING_URL")
    )
    if not url:
        return Toolset(
            name="tracing",
            tools=[],
            prerequisites=[EnvPrerequisite(["TEMPO_URL", "JAEGER_URL", "TRACING_URL"])],
            llm_instructions="Tracing is not configured.",
        )

    provider = config.get("provider") or _detect_provider(url)
    backend: TracingBackend
    if provider == "tempo":
        backend = TempoBackend(url)
    else:
        backend = JaegerBackend(url)

    class TracingToolset(Toolset):
        def compress(self, tool_name: str, raw_output: str) -> str:
            if tool_name != "trace_get":
                return raw_output
            lines = raw_output.split("\n")
            if len(lines) <= 60:
                return raw_output
            kept: list[str] = []
            for line in lines:
                if ("❌" in line or "⚠️" in line
                        or line.startswith("Trace:") or line.startswith("Spans:")):
                    kept.append(line)
                elif "└─" in line and not kept:
                    kept.append(line)
            header = f"[Compressed trace: {len(lines)} lines → {len(kept)} significant]"
            return header + "\n" + "\n".join(kept)

    tools = [
        TraceSearchTool(backend, provider),
        TraceGetTool(backend),
        TraceServicesTool(backend),
    ]

    return TracingToolset(
        name="tracing",
        tools=tools,
        prerequisites=[],
        llm_instructions=(
            f"You have access to distributed tracing ({provider} backend).\n"
            "Use trace_search to find traces by service/operation/duration.\n"
            "Use trace_get to inspect the full span tree of a specific trace.\n"
            "Use trace_services to discover available services."
        ),
    )
