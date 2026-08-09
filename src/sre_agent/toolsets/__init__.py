from __future__ import annotations

from pathlib import Path
from typing import Any

from sre_agent.core.tool import Toolset


def get_builtin_toolsets(toolset_config: dict[str, Any]) -> list[Toolset]:
    from sre_agent.core.toolset_manager import ToolsetManager
    from sre_agent.toolsets.bash import create_bash_toolset
    from sre_agent.toolsets.logs import create_logs_toolset
    from sre_agent.toolsets.prometheus import create_prometheus_toolset
    from sre_agent.utils.jinja import render_template

    toolsets: list[Toolset] = []

    k8s_yaml = Path(__file__).parent / "kubernetes.yaml"
    if k8s_yaml.exists():
        mgr = ToolsetManager()
        mgr.load_yaml_toolsets([k8s_yaml])
        for ts in mgr.toolsets:
            for tool in ts.tools:
                if hasattr(tool, "_render") and tool._render is None:
                    tool._render = render_template
            toolsets.append(ts)

    prom_config = _get_toolset_config(toolset_config, "prometheus")
    if not _is_disabled(toolset_config, "prometheus"):
        ts = create_prometheus_toolset(prom_config or {})
        if ts:
            toolsets.append(ts)

    logs_config = _get_toolset_config(toolset_config, "logs")
    if not _is_disabled(toolset_config, "logs"):
        ts = create_logs_toolset(logs_config or {})
        if ts:
            toolsets.append(ts)

    if not _is_disabled(toolset_config, "bash"):
        bash_config = _get_toolset_config(toolset_config, "bash")
        toolsets.append(create_bash_toolset(bash_config or {}))

    return toolsets


def _is_disabled(toolset_config: dict[str, Any], name: str) -> bool:
    entry = toolset_config.get(name)
    if entry is None:
        return False
    if isinstance(entry, dict):
        return not entry.get("enabled", True)
    if hasattr(entry, "enabled"):
        return not entry.enabled
    return False


def _get_toolset_config(toolset_config: dict[str, Any], name: str) -> dict[str, Any] | None:
    entry = toolset_config.get(name)
    if entry is None:
        return None
    if isinstance(entry, dict):
        if not entry.get("enabled", True):
            return None
        return entry.get("config", entry)
    if hasattr(entry, "config"):
        return entry.config
    return {}
