"""组装随应用发布的内置诊断工具集。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sre_agent.core.tool import Toolset


def get_builtin_toolsets(toolset_config: dict[str, Any]) -> list[Toolset]:
    """依据配置创建已启用的内置工具集。

    Kubernetes 使用 YAML 声明，其余工具集需要根据运行配置构造 HTTP 客户端
    或超时参数，因此由 Python 工厂函数创建。
    """

    # 延迟导入避免包初始化期间形成 toolsets -> manager -> toolsets 循环。
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
            # 为自动解析的 YAMLTool 注入项目统一的 Jinja 渲染函数。
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
    """兼容字典和 Pydantic 对象两种配置表示，判断工具集是否禁用。"""

    entry = toolset_config.get(name)
    if entry is None:
        return False
    if isinstance(entry, dict):
        return not entry.get("enabled", True)
    if hasattr(entry, "enabled"):
        return not entry.enabled
    return False


def _get_toolset_config(toolset_config: dict[str, Any], name: str) -> dict[str, Any] | None:
    """提取工具集私有配置；禁用或不存在时返回 ``None``。"""

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
