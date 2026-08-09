"""SRE Agent 包入口。"""

from sre_agent.cli import app


def main() -> None:
    """启动由 Typer 注册的命令行应用。"""

    app()
