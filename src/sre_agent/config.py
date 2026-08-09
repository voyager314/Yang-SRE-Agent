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
    model_config = SettingsConfigDict(extra="allow")

    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ModelEntry(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")

    model: str = ""
    api_key: SecretStr | None = None
    api_base: str | None = None
    api_version: str | None = None


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SRE_AGENT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    model: str | None = None
    max_steps: int = 30
    max_tool_output_lines: int = 2000

    toolsets: dict[str, ToolsetConfig] = Field(default_factory=dict)
    models: dict[str, ModelEntry] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _load_yaml_config(cls, values: dict[str, Any]) -> dict[str, Any]:
        config_path = values.pop("_config_file", None) or DEFAULT_CONFIG_FILE
        if isinstance(config_path, str):
            config_path = Path(config_path)
        if config_path.exists():
            with open(config_path) as f:
                file_data = yaml.safe_load(f) or {}
            for key, val in file_data.items():
                if key not in values or values[key] is None:
                    values[key] = val
        return values

    def load_models_registry(self) -> dict[str, ModelEntry]:
        registry: dict[str, ModelEntry] = {}
        if DEFAULT_MODELS_FILE.exists():
            with open(DEFAULT_MODELS_FILE) as f:
                raw = yaml.safe_load(f) or {}
            for name, entry_data in raw.items():
                if isinstance(entry_data, dict):
                    if "model" not in entry_data:
                        entry_data["model"] = name
                    registry[name] = ModelEntry(**entry_data)
        for name, entry in self.models.items():
            if not entry.model:
                entry.model = name
            registry[name] = entry
        return registry

    def resolve_model(self, cli_model: str | None = None) -> ModelEntry:
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
