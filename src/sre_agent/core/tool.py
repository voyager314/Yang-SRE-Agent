from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ToolResultStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    NO_DATA = "no_data"


class StructuredToolResult(BaseModel):
    status: ToolResultStatus
    data: Any | None = None
    error: str | None = None
    params: dict[str, Any] | None = None
    elapsed_seconds: float | None = None


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]

    def __init__(self, name: str, description: str, parameters: dict[str, Any] | None = None):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}

    def invoke(self, params: dict[str, Any], max_output_lines: int = 2000) -> StructuredToolResult:
        start = time.time()
        params = self._coerce_params(params)
        try:
            result = self._invoke(params)
        except Exception as e:
            result = StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=str(e),
                params=params,
            )
        result.elapsed_seconds = time.time() - start
        result.params = params
        return self._truncate_if_needed(result, max_output_lines)

    @abstractmethod
    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult: ...

    def _coerce_params(self, params: dict[str, Any]) -> dict[str, Any]:
        properties = self.parameters.get("properties", {})
        coerced = {}
        for key, value in params.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type == "integer" and isinstance(value, str):
                    coerced[key] = int(value)
                elif expected_type == "boolean" and isinstance(value, str):
                    coerced[key] = value.lower() in ("true", "1", "yes")
                else:
                    coerced[key] = value
            else:
                coerced[key] = value
        return coerced

    def _truncate_if_needed(
        self, result: StructuredToolResult, max_lines: int
    ) -> StructuredToolResult:
        if result.status != ToolResultStatus.SUCCESS or result.data is None:
            return result
        text = str(result.data)
        lines = text.split("\n")
        if len(lines) > max_lines:
            truncated = "\n".join(lines[:max_lines])
            truncated += f"\n\n[输出已截断，原始长度 {len(lines)} 行，已保留前 {max_lines} 行]"
            result.data = truncated
        return result

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class PrerequisiteStatus(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    UNCHECKED = "unchecked"


class Prerequisite(ABC):
    @abstractmethod
    def check(self) -> tuple[PrerequisiteStatus, str]: ...


class EnvPrerequisite(Prerequisite):
    def __init__(self, env_vars: list[str]):
        self.env_vars = env_vars

    def check(self) -> tuple[PrerequisiteStatus, str]:
        import os

        missing = [v for v in self.env_vars if not os.environ.get(v)]
        if missing:
            return PrerequisiteStatus.FAILED, f"Missing env vars: {', '.join(missing)}"
        return PrerequisiteStatus.SATISFIED, ""


class CommandPrerequisite(Prerequisite):
    def __init__(self, command: str, timeout: float = 10.0):
        self.command = command
        self.timeout = timeout

    def check(self) -> tuple[PrerequisiteStatus, str]:
        try:
            result = subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode == 0:
                return PrerequisiteStatus.SATISFIED, ""
            return (
                PrerequisiteStatus.FAILED,
                f"Command failed: {self.command} ({result.stderr.strip()})",
            )
        except subprocess.TimeoutExpired:
            return PrerequisiteStatus.FAILED, f"Command timed out: {self.command}"
        except Exception as e:
            return PrerequisiteStatus.FAILED, f"Command error: {self.command} ({e})"


class Toolset:
    def __init__(
        self,
        name: str,
        tools: list[Tool],
        prerequisites: list[Prerequisite] | None = None,
        llm_instructions: str | None = None,
    ):
        self.name = name
        self.tools = tools
        self.prerequisites = prerequisites or []
        self.llm_instructions = llm_instructions
        self._status: PrerequisiteStatus = PrerequisiteStatus.UNCHECKED
        self._status_message: str = ""

    @property
    def is_available(self) -> bool:
        return self._status == PrerequisiteStatus.SATISFIED

    def check_prerequisites(self) -> bool:
        for prereq in self.prerequisites:
            status, message = prereq.check()
            if status == PrerequisiteStatus.FAILED:
                self._status = PrerequisiteStatus.FAILED
                self._status_message = message
                return False
        self._status = PrerequisiteStatus.SATISFIED
        self._status_message = ""
        return True


class YAMLTool(Tool):
    def __init__(
        self,
        name: str,
        description: str,
        command: str | None = None,
        script: str | None = None,
        timeout: float = 30.0,
        render_func: Any = None,
    ):
        self.command_template = command or ""
        self.script_template = script or ""
        self.timeout = timeout
        self._render = render_func
        parameters = self._infer_parameters()
        super().__init__(name=name, description=description, parameters=parameters)

    def _infer_parameters(self) -> dict[str, Any]:
        from sre_agent.utils.jinja import extract_variables

        template = self.command_template or self.script_template
        variables = extract_variables(template)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for var_name, has_default in variables:
            properties[var_name] = {"type": "string", "description": var_name}
            if not has_default:
                required.append(var_name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        template = self.command_template or self.script_template
        rendered = self._render(template, params) if self._render else template

        try:
            result = subprocess.run(
                rendered,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output:
                    return StructuredToolResult(status=ToolResultStatus.NO_DATA, data=None)
                return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=output)
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Exit code {result.returncode}: {result.stderr.strip()}",
                data=result.stdout.strip() or None,
            )
        except subprocess.TimeoutExpired:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Command timed out after {self.timeout}s",
            )
