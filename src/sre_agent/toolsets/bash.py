from __future__ import annotations

import subprocess
from typing import Any

from sre_agent.core.tool import (
    StructuredToolResult,
    Tool,
    ToolResultStatus,
    Toolset,
)


class BashTool(Tool):
    def __init__(self, timeout: float = 60.0):
        self._timeout = timeout
        super().__init__(
            name="bash",
            description=(
                "Execute a bash command. Use for any system command"
                " not covered by other tools."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        command = params["command"]
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                error_msg = result.stderr.strip()
                return StructuredToolResult(
                    status=ToolResultStatus.ERROR,
                    error=f"Exit code {result.returncode}: {error_msg}",
                    data=output or None,
                )
            if not output:
                return StructuredToolResult(status=ToolResultStatus.NO_DATA)
            return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=output)
        except subprocess.TimeoutExpired:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Command timed out after {self._timeout}s",
            )


def create_bash_toolset(config: dict[str, Any]) -> Toolset:
    timeout = config.get("timeout", 60.0)
    return Toolset(
        name="bash",
        tools=[BashTool(timeout=timeout)],
        prerequisites=[],
        llm_instructions=(
            "You have a bash tool for executing arbitrary shell commands.\n"
            "Use this as a fallback when no specialized tool covers what you need.\n"
            "Prefer specialized tools (kubernetes, prometheus, logs) when available."
        ),
    )
