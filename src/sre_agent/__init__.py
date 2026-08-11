"""SRE Agent 包入口。"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from sre_agent.config import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE, DEFAULT_MODELS_FILE


def ensure_config(console: Console) -> None:
    """首次运行时自动创建配置目录和示例文件。"""

    if DEFAULT_CONFIG_DIR.exists():
        return

    DEFAULT_CONFIG_DIR.mkdir(parents=True)
    (DEFAULT_CONFIG_DIR / "memory").mkdir()

    templates: list[tuple[str, Path]] = [
        ("config.example.yaml", DEFAULT_CONFIG_FILE),
        ("models.example.yaml", DEFAULT_MODELS_FILE),
    ]
    for src_name, dst_path in templates:
        content = resources.files("sre_agent.defaults").joinpath(src_name).read_text("utf-8")
        dst_path.write_text(content, encoding="utf-8")

    console.print(
        Panel(
            f"已初始化配置目录: {DEFAULT_CONFIG_DIR}\n"
            f"请编辑 config.yaml 和 models.yaml 配置你的模型和工具集连接。",
            title="首次运行",
            border_style="green",
        )
    )


def main() -> None:
    """启动由 Typer 注册的命令行应用。"""

    from sre_agent.cli import app

    app()
