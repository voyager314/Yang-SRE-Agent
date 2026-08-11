"""基于 Typer 的命令行入口及终端流式输出逻辑。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from sre_agent import ensure_config
from sre_agent.config import DEFAULT_CONFIG_FILE, Config
from sre_agent.core.context_manager import ContextManager
from sre_agent.core.engine import Engine
from sre_agent.core.evidence_store import EvidenceStore
from sre_agent.core.llm import DefaultLLM
from sre_agent.core.memory_store import MemoryStore
from sre_agent.core.scratchpad import Scratchpad
from sre_agent.core.tool_executor import ToolExecutor
from sre_agent.core.toolset_manager import ToolsetManager
from sre_agent.utils.jinja import load_prompt
from sre_agent.utils.streaming import StreamEventType

logger = logging.getLogger(__name__)

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

    # 建立 tool_name → Toolset 映射，供压缩逻辑按工具集分发。
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

    # 初始化跨会话调查记忆系统（可选）。
    memory_store: MemoryStore | None = None
    if config.memory_enabled:
        try:
            from sre_agent.core.embedder import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder(config.embedding_model)
            memory_store = MemoryStore(
                embedder=embedder,
                llm=llm,
                memory_dir=config.memory_dir,
                top_k=config.memory_top_k,
                score_threshold=config.memory_score_threshold,
            )
        except Exception:
            logger.warning("调查记忆系统初始化失败，已降级为禁用模式", exc_info=True)

    available_toolsets = mgr.get_available_toolsets()
    system_prompt = load_prompt("system", {"toolsets": available_toolsets})

    return (
        Engine(
            llm=llm,
            tool_executor=executor,
            max_steps=config.max_steps,
            max_output_lines=config.max_tool_output_lines,
            context_manager=context_manager,
            memory_store=memory_store,
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
                    "如需继续，请使用 /new 开启新会话或减少工具调用。[/yellow]"
                )
    return answer


# ------------------------------------------------------------------
# Slash command handlers
# ------------------------------------------------------------------

_SLASH_COMMANDS: dict[str, str] = {
    "/new": "Clear context and start a new investigation",
    "/clear": "Alias for /new",
    "/model": "Show or switch the active model",
    "/toolset": "List available toolsets and their status",
    "/help": "Show this help message",
    "/exit": "Exit the program",
    "/quit": "Alias for /exit",
}


class _SessionState:
    """REPL 会话中需要跨 slash command 共享的可变状态。"""

    def __init__(
        self,
        engine: Engine,
        config: Config,
        system_prompt: str,
        mgr: ToolsetManager,
        messages: list[dict],
    ):
        self.engine = engine
        self.config = config
        self.system_prompt = system_prompt
        self.mgr = mgr
        self.messages = messages
        self.model_key: str | None = None


def _dispatch_slash(user_input: str, state: _SessionState) -> bool | None:
    """分发斜杠命令，返回 False 表示应退出 REPL，None 表示继续。"""

    parts = user_input.split(None, 1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        console.print("[dim]Goodbye.[/dim]")
        return False

    if cmd in ("/new", "/clear"):
        _cmd_new(state)
        return None

    if cmd == "/model":
        _cmd_model(args, state)
        return None

    if cmd == "/toolset":
        _cmd_toolset(state)
        return None

    if cmd == "/help":
        _cmd_help()
        return None

    console.print(f"  [red]Unknown command: {cmd}[/red]  (type /help for available commands)")
    return None


def _cmd_new(state: _SessionState) -> None:
    """清空调查状态，开始新一轮对话。"""

    state.messages.clear()
    state.messages.append({"role": "system", "content": state.system_prompt})

    cm = state.engine.context_manager
    if cm is not None:
        cm.evidence_store.clear()
        cm.scratchpad.clear()

    console.print("  [green]Context cleared. Ready for a new investigation.[/green]")


def _cmd_model(args: str, state: _SessionState) -> None:
    """查看或切换当前模型。"""

    llm = state.engine.llm

    if not args:
        registry = state.config.load_models_registry()
        current_model = llm.model
        console.print()
        console.print(f"  [bold]Current model:[/bold] {current_model}")
        if llm.api_base:
            console.print(f"  [dim]API base: {llm.api_base}[/dim]")
        if registry:
            console.print()
            console.print("  [bold]Available models:[/bold]")
            for name, entry in registry.items():
                marker = "●" if entry.model == current_model else " "
                base_info = f" ({entry.api_base})" if entry.api_base else ""
                console.print(f"    {marker} [bold]{name}[/bold] - {entry.model}{base_info}")
        console.print()
        return

    try:
        entry = state.config.resolve_model(args)
    except ValueError as e:
        console.print(f"  [red]{e}[/red]")
        return

    llm.model = entry.model
    llm.api_key = entry.api_key.get_secret_value() if entry.api_key else None
    llm.api_base = entry.api_base
    llm.api_version = entry.api_version
    state.model_key = args

    registry = state.config.load_models_registry()
    if args in registry:
        console.print(f"  [green]Switched to: {args} ({entry.model})[/green]")
    else:
        console.print(
            f"  [green]Switched to: {entry.model}[/green]"
            f"\n  [dim]Not in registry, using as raw LiteLLM identifier[/dim]"
        )


def _cmd_toolset(state: _SessionState) -> None:
    """显示工具集状态。"""

    console.print()
    console.print("  [bold]Toolsets:[/bold]")
    console.print()

    for ts in state.mgr.toolsets:
        status_icon = "[OK]" if ts.is_available else "[FAIL]"
        status_color = "green" if ts.is_available else "red"
        tool_count = len(ts.tools)
        tool_names = ", ".join(t.name for t in ts.tools)
        console.print(
            f"    [{status_color}]{status_icon}[/{status_color}] "
            f"[bold]{ts.name}[/bold] ({tool_count} tools: {tool_names})"
        )
        if not ts.is_available and ts._status_message:
            console.print(f"      [dim]{ts._status_message}[/dim]")

    console.print()


def _cmd_help() -> None:
    """打印可用命令列表。"""

    console.print()
    console.print("  [bold]Available commands:[/bold]")
    console.print()
    for cmd, desc in _SLASH_COMMANDS.items():
        if cmd in ("/clear", "/quit"):
            continue
        console.print(f"    [bold]{cmd:<12}[/bold] {desc}")
    console.print()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    question: Annotated[str | None, typer.Argument(help="Question or issue to investigate")] = None,
    print_mode: Annotated[
        bool, typer.Option("--print", "-p", help="Non-interactive mode: print answer and exit")
    ] = False,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model to use")] = None,
    config_file: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file path")
    ] = None,
) -> None:
    """AI-powered SRE agent for infrastructure diagnostics."""

    ensure_config(console)

    config = Config(_config_file=str(config_file) if config_file else str(DEFAULT_CONFIG_FILE))  # type: ignore
    engine, system_prompt, mgr = _build_engine(config, model)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if print_mode:
        if not question:
            console.print("[red]Error: question is required in print mode (-p)[/red]")
            raise typer.Exit(code=1)

        user_prompt = load_prompt("investigate", {"question": question})
        messages.append({"role": "user", "content": user_prompt})

        answer = _render_stream(engine, messages)
        console.print()
        console.print(Markdown(answer))
        return

    # 交互依赖只在 REPL 运行时导入，避免非交互命令承担启动开销。
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    session: PromptSession = PromptSession(history=InMemoryHistory())
    state = _SessionState(engine, config, system_prompt, mgr, messages)

    console.print(
        Panel(
            "Interactive SRE Agent session. Type your questions, /help for commands.",
            title="[bold]SRE Agent[/bold]",
            border_style="blue",
        )
    )

    if question:
        console.print()
        console.print(Panel(question, title="[bold]Question[/bold]", border_style="blue"))
        console.print()

        user_prompt = load_prompt("investigate", {"question": question})
        messages.append({"role": "user", "content": user_prompt})
        answer = _render_stream(engine, messages)
        messages.append({"role": "assistant", "content": answer})
        console.print()
        console.print(Markdown(answer))

    while True:
        try:
            user_input = session.prompt("\n❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = _dispatch_slash(user_input, state)
            if result is False:
                break
            continue

        messages.append({"role": "user", "content": user_input})
        console.print()

        answer = _render_stream(engine, messages)
        messages.append({"role": "assistant", "content": answer})
        console.print()
        console.print(Markdown(answer))
