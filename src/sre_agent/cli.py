"""基于 Typer 的命令行入口及终端流式输出逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from sre_agent.config import DEFAULT_CONFIG_FILE, Config
from sre_agent.core.context_manager import ContextManager
from sre_agent.core.engine import Engine
from sre_agent.core.evidence_store import EvidenceStore
from sre_agent.core.llm import DefaultLLM
from sre_agent.core.scratchpad import Scratchpad
from sre_agent.core.tool_executor import ToolExecutor
from sre_agent.core.toolset_manager import ToolsetManager
from sre_agent.utils.jinja import load_prompt
from sre_agent.utils.streaming import StreamEventType

app = typer.Typer(name="sre-agent", help="AI-powered SRE agent for infrastructure diagnostics")
console = Console()


def _build_engine(
    config: Config, model_override: str | None = None
) -> tuple[Engine, str, ToolsetManager]:
    """根据配置组装模型、可用工具和执行引擎。"""

    model_entry = config.resolve_model(model_override)
    llm = DefaultLLM(
        model=model_entry.model,
        api_key=model_entry.api_key.get_secret_value() if model_entry.api_key else None,
        api_base=model_entry.api_base,
        api_version=model_entry.api_version,
    )

    toolset_config = {}
    for name, ts_cfg in config.toolsets.items():
        toolset_config[name] = ts_cfg

    mgr = ToolsetManager(toolset_config=toolset_config)
    mgr.load_builtin_toolsets()
    mgr.check_prerequisites()

    executor = ToolExecutor()
    for toolset in mgr.get_available_toolsets():
        executor.register_all(toolset.tools)

    # tool_name → Toolset mapping for compress() dispatch
    tool_to_toolset = {
        tool.name: toolset for toolset in mgr.get_available_toolsets() for tool in toolset.tools
    }

    evidence_store = EvidenceStore()
    scratchpad = Scratchpad()
    context_manager = ContextManager(
        llm=llm,
        evidence_store=evidence_store,
        scratchpad=scratchpad,
        toolsets=tool_to_toolset,
        compress_threshold=config.compress_threshold,
        converge_threshold=config.converge_threshold,
    )

    available_toolsets = mgr.get_available_toolsets()
    system_prompt = load_prompt("system", {"toolsets": available_toolsets})

    return (
        Engine(
            llm=llm,
            tool_executor=executor,
            max_steps=config.max_steps,
            max_output_lines=config.max_tool_output_lines,
            context_manager=context_manager,
        ),
        system_prompt,
        mgr,
    )


def _render_stream(engine: Engine, messages: list[dict]) -> str:
    """消费引擎事件，在终端显示进度并返回最终文本答案。"""

    answer = ""
    for event in engine.call_stream(messages):
        if event.event == StreamEventType.TOOL_START:
            name = event.data.get("name", "")
            console.print(f"  [dim]▶ calling {name}...[/dim]")
        elif event.event == StreamEventType.TOOL_RESULT:
            content = event.data.get("content", "")
            status = "[OK]" if not content.startswith("ERROR") else "[FAIL]"
            preview = content[:80].replace("\n", " ")
            console.print(f"  [dim]{status} {preview}[/dim]")
        elif event.event == StreamEventType.AI_MESSAGE:
            pass
        elif event.event == StreamEventType.ANSWER_END:
            answer = event.data.get("content", "")
            if event.data.get("converged"):
                console.print(
                    "\n  [yellow]⚠ 上下文预算耗尽，已根据现有调查结果强制收敛。"
                    "如需继续，请开启新会话或减少工具调用。[/yellow]"
                )
    return answer


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Question or issue to investigate")],
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model to use")] = None,
    config_file: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file path")
    ] = None,
):
    """对基础设施问题执行一次性调查。"""
    config = Config(_config_file=str(config_file) if config_file else str(DEFAULT_CONFIG_FILE))  # type: ignore
    engine, system_prompt, _mgr = _build_engine(config, model)

    # 将原始问题嵌入调查模板，使一次性模式也遵循统一的分析指引。
    user_prompt = load_prompt("investigate", {"question": question})
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    console.print()
    console.print(Panel(question, title="[bold]SRE Agent[/bold]", border_style="blue"))
    console.print()

    answer = _render_stream(engine, messages)

    console.print()
    console.print(Markdown(answer))


@app.command()
def chat(
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model to use")] = None,
    config_file: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file path")
    ] = None,
):
    """启动保留上下文的交互式多轮会话。"""

    # 交互依赖只在该子命令运行时导入，避免其他命令承担启动开销。
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    config = Config(_config_file=str(config_file) if config_file else str(DEFAULT_CONFIG_FILE))  # type: ignore
    engine, system_prompt, _mgr = _build_engine(config, model)

    # 同一列表会在每轮调用中扩展，从而向模型提供完整会话和工具调用历史。
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    session: PromptSession = PromptSession(history=InMemoryHistory())

    console.print(
        Panel(
            "Interactive SRE Agent session. Type your questions, 'exit' or Ctrl+D to quit.",
            title="[bold]SRE Agent Chat[/bold]",
            border_style="blue",
        )
    )

    while True:
        try:
            user_input = session.prompt("\n❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        messages.append({"role": "user", "content": user_input})
        console.print()

        answer = _render_stream(engine, messages)

        # 保存最终回答，下一轮用户可以引用此前的诊断结论。
        messages.append({"role": "assistant", "content": answer})
        console.print()
        console.print(Markdown(answer))


@app.command("toolset")
def toolset_list(
    config_file: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file path")
    ] = None,
):
    """列出工具集、工具数量以及前置条件检查状态。"""
    config = Config(_config_file=str(config_file) if config_file else str(DEFAULT_CONFIG_FILE))  # type: ignore

    toolset_config = {}
    for name, ts_cfg in config.toolsets.items():
        toolset_config[name] = ts_cfg

    mgr = ToolsetManager(toolset_config=toolset_config)
    mgr.load_builtin_toolsets()
    mgr.check_prerequisites()

    console.print()
    console.print("[bold]Toolsets:[/bold]")
    console.print()

    for ts in mgr.toolsets:
        status_icon = "[OK]" if ts.is_available else "[FAIL]"
        status_color = "green" if ts.is_available else "red"
        tool_count = len(ts.tools)
        tool_names = ", ".join(t.name for t in ts.tools)
        console.print(
            f"  [{status_color}]{status_icon}[/{status_color}] "
            f"[bold]{ts.name}[/bold] ({tool_count} tools: {tool_names})"
        )
        if not ts.is_available and ts._status_message:
            console.print(f"    [dim]{ts._status_message}[/dim]")

    console.print()
