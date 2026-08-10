"""应用配置、模型注册表及多来源配置合并规则。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_DIR = Path.home() / ".sre-agent"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_MODELS_FILE = DEFAULT_CONFIG_DIR / "models.yaml"


class ToolsetConfig(BaseSettings):
    """单个工具集的启用状态及供应商专属配置。"""

    # 允许工具集携带核心程序未知的扩展配置，例如 URL、超时或供应商选项。
    model_config = SettingsConfigDict(extra="allow")

    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ModelEntry(BaseSettings):
    """一个可命名复用的模型连接配置。"""

    model_config = SettingsConfigDict(extra="allow")

    model: str = ""
    api_key: SecretStr | None = None
    api_base: str | None = None
    api_version: str | None = None


class Config(BaseSettings):
    """SRE Agent 的顶层运行配置。

    配置可来自 ``SRE_AGENT_`` 环境变量、YAML 文件和构造参数。显式传入值的
    优先级高于 YAML；嵌套环境变量使用双下划线分隔。
    """

    model_config = SettingsConfigDict(
        env_prefix="SRE_AGENT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    model: str | None = None
    max_steps: int = 50
    max_tool_output_lines: int = 2000
    compress_threshold: float = 0.70
    converge_threshold: float = 0.90

    # Memory 配置
    memory_enabled: bool = True
    memory_dir: str = str(DEFAULT_CONFIG_DIR / "memory")
    embedding_model: str = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
    memory_top_k: int = 3
    memory_score_threshold: float = 0.6

    toolsets: dict[str, ToolsetConfig] = Field(default_factory=dict)
    models: dict[str, ModelEntry] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _load_yaml_config(cls, values: dict[str, Any]) -> dict[str, Any]:
        """在 Pydantic 校验前读取 YAML，并仅填补尚未显式提供的字段。"""

        # ``_config_file`` 是一次性加载参数，不属于最终的 Config 模型字段。
        config_path = values.pop("_config_file", None) or DEFAULT_CONFIG_FILE
        if isinstance(config_path, str):
            config_path = Path(config_path)
        if config_path.exists():
            with open(config_path) as f:
                file_data = yaml.safe_load(f) or {}
            # 构造参数或环境变量已提供的值不得被 YAML 覆盖。
            for key, val in file_data.items():
                if key not in values or values[key] is None:
                    values[key] = val
        return values

    def load_models_registry(self) -> dict[str, ModelEntry]:
        """合并用户级模型注册表和当前配置中的内联模型。

        内联 ``models`` 后写入，因此同名项会覆盖 ``models.yaml`` 中的定义。
        """

        registry: dict[str, ModelEntry] = {}
        if DEFAULT_MODELS_FILE.exists():
            with open(DEFAULT_MODELS_FILE) as f:
                raw = yaml.safe_load(f) or {}
            for name, entry_data in raw.items():
                if isinstance(entry_data, dict):
                    if "model" not in entry_data:
                        entry_data["model"] = name
                    registry[name] = ModelEntry(**entry_data)
        # 配置项省略 model 时，将注册表键本身作为 LiteLLM 模型标识。
        for name, entry in self.models.items():
            if not entry.model:
                entry.model = name
            registry[name] = entry
        return registry

    def resolve_model(self, cli_model: str | None = None) -> ModelEntry:
        """按照 CLI 覆盖值、顶层配置和注册表默认项的顺序选择模型。

        未在注册表中出现的名称仍可直接传给 LiteLLM，支持临时使用新模型。
        """

        registry = self.load_models_registry()

        model_name = cli_model or self.model
        if not model_name:
            if registry:
                first_key = next(iter(registry))
                return registry[first_key]
            raise ValueError(
                "未配置模型，请通过 --model 参数、SRE_AGENT_MODEL 环境变量"
                "或 config.yaml model 字段指定模型"
            )

        if model_name in registry:
            return registry[model_name]

        return ModelEntry(model=model_name)
