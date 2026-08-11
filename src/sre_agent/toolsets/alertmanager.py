"""Alertmanager toolset for querying active alerts and silence rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import httpx

from sre_agent.core.tool import (
    EnvPrerequisite,
    StructuredToolResult,
    Tool,
    ToolResultStatus,
    Toolset,
)


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_CORE_LABELS = ("alertname", "severity", "namespace", "pod", "message", "description")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_alerts(alerts: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alerts:
        labels = alert.get("labels", {})
        sev = labels.get("severity", "unknown")
        grouped[sev].append(alert)

    severity_keys = sorted(
        grouped.keys(), key=lambda s: _SEVERITY_ORDER.get(s, 99)
    )

    lines: list[str] = []
    for sev in severity_keys:
        sev_alerts = grouped[sev]
        lines.append(f"[{sev.upper()}] ({len(sev_alerts)} alert{'s' if len(sev_alerts) != 1 else ''})")
        lines.append("-" * 40)
        for alert in sev_alerts:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            alertname = labels.get("alertname", "unnamed")
            ns = labels.get("namespace", "")
            pod = labels.get("pod", "")
            msg = annotations.get("message") or annotations.get("description") or labels.get("message", "")

            parts = [f"  {alertname}"]
            if ns:
                parts.append(f"ns={ns}")
            if pod:
                parts.append(f"pod={pod}")
            lines.append(" | ".join(parts))
            if msg:
                lines.append(f"    {msg[:120]}")
        lines.append("")

    return "\n".join(lines)


def _format_silences(silences: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for s in silences:
        matchers = s.get("matchers", [])
        matcher_strs = []
        for m in matchers:
            name = m.get("name", "")
            value = m.get("value", "")
            is_regex = m.get("isRegex", False)
            is_equal = m.get("isEqual", True)
            if is_regex:
                op = "=~" if is_equal else "!~"
            else:
                op = "=" if is_equal else "!="
            matcher_strs.append(f"{name}{op}{value}")

        created_by = s.get("createdBy", "unknown")
        ends_at = s.get("endsAt", "")
        comment = s.get("comment", "")
        silence_id = s.get("id", "")[:8]

        lines.append(f"  [{silence_id}] {', '.join(matcher_strs)}")
        lines.append(f"    by={created_by} expires={ends_at}")
        if comment:
            lines.append(f"    \"{comment[:100]}\"")
        lines.append("")

    return "\n".join(lines)


def _compress_alerts(raw_output: str) -> str:
    lines = raw_output.split("\n")
    if len(lines) <= 50:
        return raw_output

    alert_counts: dict[str, int] = defaultdict(int)
    alert_examples: dict[str, str] = {}
    current_alert = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and "] (" in stripped and "alert" in stripped:
            continue
        if stripped.startswith("---"):
            continue
        if line.startswith("  ") and not line.startswith("    ") and "|" in line:
            name = line.strip().split("|")[0].strip()
            alert_counts[name] = alert_counts.get(name, 0) + 1
            current_alert = name
            if name not in alert_examples:
                alert_examples[name] = line.strip()
        elif line.startswith("    ") and current_alert:
            if current_alert not in alert_examples or alert_counts[current_alert] == 1:
                alert_examples[current_alert] = alert_examples.get(current_alert, "") + "\n    " + line.strip()

    if not alert_counts:
        return raw_output

    compressed = [f"[Compressed: {sum(alert_counts.values())} alerts → {len(alert_counts)} unique alertnames]", ""]
    for name, count in sorted(alert_counts.items(), key=lambda x: -x[1]):
        compressed.append(f"  {name} (x{count})")
        example = alert_examples.get(name, "")
        if example:
            compressed.append(f"    e.g. {example.split(chr(10))[0]}")
    return "\n".join(compressed)

# ---------------------------------------------------------------------------
# Tool Classes
# ---------------------------------------------------------------------------

class AlertmanagerListTool(Tool):
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        super().__init__(
            name="alertmanager_list",
            description="List active alerts from Alertmanager, grouped by severity",
            parameters={
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Label matcher filter (e.g. namespace=\"production\")",
                    },
                    "silenced": {
                        "type": "boolean",
                        "description": "Include silenced alerts (default false)",
                    },
                    "inhibited": {
                        "type": "boolean",
                        "description": "Include inhibited alerts (default false)",
                    },
                },
                "required": [],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        api_params: dict[str, Any] = {
            "silenced": str(params.get("silenced", False)).lower(),
            "inhibited": str(params.get("inhibited", False)).lower(),
            "active": "true",
        }
        if params.get("filter"):
            api_params["filter"] = params["filter"]

        try:
            resp = httpx.get(
                f"{self._base_url}/api/v2/alerts",
                params=api_params,
                timeout=15.0,
            )
            resp.raise_for_status()
            alerts = resp.json()
            if not alerts:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS,
                data=_format_alerts(alerts),
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Cannot connect to Alertmanager at {self._base_url}",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


class AlertmanagerSilencesTool(Tool):
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        super().__init__(
            name="alertmanager_silences",
            description="List active silence rules from Alertmanager",
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        try:
            resp = httpx.get(
                f"{self._base_url}/api/v2/silences", timeout=15.0
            )
            resp.raise_for_status()
            all_silences = resp.json()
            active = [s for s in all_silences if s.get("status", {}).get("state") == "active"]
            if not active:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            header = f"Active silences ({len(active)}):\n\n"
            return StructuredToolResult(
                status=ToolResultStatus.SUCCESS,
                data=header + _format_silences(active),
            )
        except httpx.ConnectError:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Cannot connect to Alertmanager at {self._base_url}",
            )
        except Exception as e:
            return StructuredToolResult(status=ToolResultStatus.ERROR, error=str(e))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_alertmanager_toolset(config: dict[str, Any]) -> Toolset:
    import os

    url = config.get("url") or os.environ.get("ALERTMANAGER_URL")
    if not url:
        return Toolset(
            name="alertmanager",
            tools=[],
            prerequisites=[EnvPrerequisite(["ALERTMANAGER_URL"])],
            llm_instructions="Alertmanager is not configured.",
        )

    class AlertmanagerToolset(Toolset):
        def compress(self, tool_name: str, raw_output: str) -> str:
            if tool_name != "alertmanager_list":
                return raw_output
            return _compress_alerts(raw_output)

    tools = [
        AlertmanagerListTool(url),
        AlertmanagerSilencesTool(url),
    ]

    return AlertmanagerToolset(
        name="alertmanager",
        tools=tools,
        prerequisites=[],
        llm_instructions=(
            "You have access to Alertmanager.\n"
            "Use alertmanager_list to see active alerts (supports filter, silenced, inhibited params).\n"
            "Use alertmanager_silences to see active silence rules."
        ),
    )
