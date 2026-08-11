"""诊断工具、执行结果和运行前置条件的基础类型。"""

from __future__ import annotations

import re
import subprocess
import time
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ToolResultStatus(StrEnum):
    """工具执行结果分类，区分执行失败与成功但无数据。"""

    SUCCESS = "success"
    ERROR = "error"
    NO_DATA = "no_data"


class StructuredToolResult(BaseModel):
    """所有工具统一返回的结果信封。

    ``data`` 保存正常或部分输出，``error`` 保存面向模型的错误说明，执行入口
    会统一补充最终参数和耗时，便于追踪一次调查。
    """

    status: ToolResultStatus
    data: Any | None = None
    error: str | None = None
    params: dict[str, Any] | None = None
    elapsed_seconds: float | None = None


class Tool(ABC):
    """可被模型调用的工具基类。

    子类只实现 :meth:`_invoke` 中的业务行为；参数转换、异常隔离、计时和输出
    截断由公开的 :meth:`invoke` 模板方法统一处理。
    """

    name: str
    description: str
    parameters: dict[str, Any]

    def __init__(self, name: str, description: str, parameters: dict[str, Any] | None = None):
        """定义工具名称、模型可读描述和 JSON Schema 参数。"""

        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}

    def invoke(self, params: dict[str, Any], max_output_lines: int = 2000) -> StructuredToolResult:
        """安全执行工具，并保证异常不会逃逸到引擎主循环。"""

        start = time.time()
        # 模型有时会把数字或布尔值编码成字符串，执行前按 schema 做轻量修正。
        params = self._coerce_params(params)
        try:
            result = self._invoke(params)
        except Exception as e:
            result = StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=str(e),
                params=params,
            )
        # 即使子类返回了结果，也以实际入口参数和端到端耗时为准。
        result.elapsed_seconds = time.time() - start
        result.params = params
        return self._truncate_if_needed(result, max_output_lines)

    @abstractmethod
    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        """执行工具的具体业务逻辑，由子类实现。"""

        ...

    def _coerce_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """根据 JSON Schema 转换常见的字符串参数类型。

        未在 schema 中声明的参数原样保留，便于实现允许扩展字段的工具。
        """

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
        """截断过长的成功输出，控制传回模型的上下文占用。"""

        # 错误和无数据结果结构很小，同时可能含关键诊断信息，不做截断。
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
        """转换为 OpenAI function calling 兼容定义。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class PrerequisiteStatus(StrEnum):
    """工具集运行条件的检查状态。"""

    SATISFIED = "satisfied"
    FAILED = "failed"
    UNCHECKED = "unchecked"


class Prerequisite(ABC):
    """工具集可用性检查接口。"""

    @abstractmethod
    def check(self) -> tuple[PrerequisiteStatus, str]:
        """返回检查状态及失败时的可读原因。"""

        ...


class EnvPrerequisite(Prerequisite):
    """要求一个或多个环境变量已设置且非空。"""

    def __init__(self, env_vars: list[str]):
        self.env_vars = env_vars

    def check(self) -> tuple[PrerequisiteStatus, str]:
        """一次性报告全部缺失变量，减少用户反复修正配置。"""

        import os

        missing = [v for v in self.env_vars if not os.environ.get(v)]
        if missing:
            return PrerequisiteStatus.FAILED, f"Missing env vars: {', '.join(missing)}"
        return PrerequisiteStatus.SATISFIED, ""


class CommandPrerequisite(Prerequisite):
    """通过命令退出码判断外部程序或服务是否可用。"""

    def __init__(self, command: str, timeout: float = 10.0):
        self.command = command
        self.timeout = timeout

    def check(self) -> tuple[PrerequisiteStatus, str]:
        """执行探测命令，并把超时及异常转换为失败状态。"""

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
    """按诊断领域组织工具、前置条件和模型使用说明。"""

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
        """仅在前置条件已明确通过后返回可用。"""

        return self._status == PrerequisiteStatus.SATISFIED

    def check_prerequisites(self) -> bool:
        """顺序检查前置条件，遇到首个失败条件立即停止。"""

        for prereq in self.prerequisites:
            status, message = prereq.check()
            if status == PrerequisiteStatus.FAILED:
                self._status = PrerequisiteStatus.FAILED
                self._status_message = message
                return False
        self._status = PrerequisiteStatus.SATISFIED
        self._status_message = ""
        return True

    def compress(self, tool_name: str, raw_output: str) -> str:
        """将超长工具输出压缩为模型仍可决策的最小摘要。

        默认实现保留首尾各 20 行并折叠中间；子类可根据领域知识提供更精准的压缩。
        约定：返回值必须是纯文本，完整原文已由引擎持久化，此处只需保留诊断关键信息。
        """

        lines = raw_output.split("\n")
        total = len(lines)
        if total <= 50:
            return raw_output
        head = lines[:20]
        tail = lines[-20:]
        omitted = total - 40
        return (
            "\n".join(head)
            + f"\n... [{omitted} 行已折叠，完整输出见证据库] ...\n"
            + "\n".join(tail)
        )


class YAMLTool(Tool):
    """从 YAML 声明构建的 shell 工具。

    参数 schema 会从 Jinja 占位符自动推导，因此 YAML 作者无需重复维护模板
    参数与 function schema。
    """

    # validator 名称映射到预编译正则，YAML 只引用受控名称而不能注入任意表达式。
    # hostname 同时允许域名、IPv4/IPv6 文本和端口所需的 ``.``、``-``、``:``。
    _PARAM_VALIDATOR_REGISTRY: dict[str, re.Pattern[str]] = {
        "hostname": re.compile(r"^[a-zA-Z0-9.\-:]+$"),
    }

    def __init__(
        self,
        name: str,
        description: str,
        command: str | None = None,
        script: str | None = None,
        timeout: float = 30.0,
        render_func: Any = None,
        param_validators: dict[str, str] | None = None,
    ):
        self.command_template = command or ""
        self.script_template = script or ""
        self.timeout = timeout
        self._render = render_func
        self._param_validators = param_validators or {}
        parameters = self._infer_parameters()
        super().__init__(name=name, description=description, parameters=parameters)

    def _infer_parameters(self) -> dict[str, Any]:
        """将模板变量转换为字符串参数，并识别带默认值的可选参数。"""

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

    def _validate_params(self, params: dict[str, Any]) -> str | None:
        """校验参数值是否符合声明的 validator。返回错误消息或 None。"""

        # 只检查 YAML 显式声明的参数；未提供的可选参数由模板默认值处理。
        for param_name, validator_name in self._param_validators.items():
            value = params.get(param_name)
            if value is None:
                continue
            # 未注册的 validator 不在这里执行，防止把配置文本当作正则直接编译。
            pattern = self._PARAM_VALIDATOR_REGISTRY.get(validator_name)
            if pattern and not pattern.match(str(value)):
                return (
                    f"Parameter '{param_name}' contains invalid characters. "
                    f"Expected format: {validator_name}"
                )
        return None

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        """渲染命令模板并在受限超时时间内执行。"""

        # 必须在 Jinja 渲染和 shell 执行之前校验，避免危险字符进入命令文本。
        validation_error = self._validate_params(params)
        if validation_error:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=validation_error,
            )

        template = self.command_template or self.script_template
        # 没有渲染函数时保留原模板，便于程序化构造无占位符的工具。
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
