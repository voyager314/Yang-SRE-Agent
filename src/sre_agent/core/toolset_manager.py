from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sre_agent.core.tool import (
    CommandPrerequisite,
    EnvPrerequisite,
    Prerequisite,
    Tool,
    Toolset,
    YAMLTool,
)
from sre_agent.utils.jinja import render_template


class ToolsetManager:
    def __init__(self, toolset_config: dict[str, Any] | None = None):
        self._toolset_config = toolset_config or {}
        self._toolsets: list[Toolset] = []

    @property
    def toolsets(self) -> list[Toolset]:
        return self._toolsets

    def load_builtin_toolsets(self) -> None:
        from sre_agent.toolsets import get_builtin_toolsets

        for toolset in get_builtin_toolsets(self._toolset_config):
            self._toolsets.append(toolset)

    def load_yaml_toolsets(self, paths: list[Path]) -> None:
        for path in paths:
            if path.is_file() and path.suffix in (".yaml", ".yml"):
                toolset = self._parse_yaml_toolset(path)
                if toolset:
                    self._toolsets.append(toolset)
            elif path.is_dir():
                for file in sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml")):
                    toolset = self._parse_yaml_toolset(file)
                    if toolset:
                        self._toolsets.append(toolset)

    def check_prerequisites(self) -> None:
        for toolset in self._toolsets:
            config = self._toolset_config.get(toolset.name, {})
            if isinstance(config, dict) and not config.get("enabled", True):
                toolset._status = toolset._status.__class__("failed")
                toolset._status_message = "Disabled by config"
                continue
            toolset.check_prerequisites()

    def get_available_toolsets(self) -> list[Toolset]:
        return [ts for ts in self._toolsets if ts.is_available]

    def _parse_yaml_toolset(self, path: Path) -> Toolset | None:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data:
            return None

        name = data.get("name", path.stem)
        tools = self._parse_tools(data.get("tools", []))
        prerequisites = self._parse_prerequisites(data.get("prerequisites", []))
        llm_instructions = data.get("llm_instructions")

        return Toolset(
            name=name,
            tools=tools,
            prerequisites=prerequisites,
            llm_instructions=llm_instructions,
        )

    def _parse_tools(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        tools: list[Tool] = []
        for td in tools_data:
            tool = YAMLTool(
                name=td["name"],
                description=td.get("description", ""),
                command=td.get("command"),
                script=td.get("script"),
                timeout=td.get("timeout", 30.0),
                render_func=render_template,
            )
            tools.append(tool)
        return tools

    def _parse_prerequisites(self, prereqs_data: list[dict[str, Any]]) -> list[Prerequisite]:
        prereqs: list[Prerequisite] = []
        for pd in prereqs_data:
            if "env" in pd:
                env_vars = pd["env"] if isinstance(pd["env"], list) else [pd["env"]]
                prereqs.append(EnvPrerequisite(env_vars))
            elif "command" in pd:
                prereqs.append(CommandPrerequisite(pd["command"], timeout=pd.get("timeout", 10.0)))
        return prereqs
