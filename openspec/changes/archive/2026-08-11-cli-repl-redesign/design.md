# Design: CLI REPL Redesign

## Architecture

```
$ sre-agent ["question"] [-p]
       │
       ├─ 读取 config.yaml + models.yaml
       ├─ resolve_model() → ModelEntry
       ├─ 构造 DefaultLLM, ToolsetManager, Engine
       │
       ├─ if -p flag:
       │     非交互模式 → investigate → print → exit
       │
       └─ else:
             进入 REPL 主循环
             ┌─────────────────────────────────┐
             │  prompt("❯ ")                    │
             │    ├─ /exit → break              │
             │    ├─ /new  → clear_session()    │
             │    ├─ /model → switch_model()    │
             │    ├─ /toolset → show_toolsets() │
             │    ├─ /help → show_help()        │
             │    └─ other → investigate()      │
             │         ├─ _render_stream()      │
             │         └─ append to messages    │
             └──────────── loop ────────────────┘
```

## Key decisions

### D1: REPL is the default, not a subcommand

The Typer app has no subcommands. The main command accepts an optional positional `question` argument and a `-p/--print` flag. Without `-p`, it always enters the interactive REPL loop.

### D2: Slash command dispatch is a simple prefix match

No need for a command registry framework. A dict mapping prefix strings to handler functions is sufficient. Unknown `/xxx` prints an error and continues.

### D3: Model switch is in-place mutation

`DefaultLLM` fields (`model`, `api_key`, `api_base`, `api_version`) are plain mutable attributes. `/model` resolves a `ModelEntry` from the config registry and writes all four fields on the existing instance. Because Python shares object references, `Engine.llm` and `ContextManager.llm` update simultaneously.

### D4: Context window adaptation is deferred

No compress at switch time. The engine's existing `check_budget()` at the top of each iteration reads `llm.get_context_window_size()` dynamically. If the new model's window is smaller and messages exceed the threshold, `compress_batch` fires on the next query automatically.

### D5: `/new` clears investigation state, not just messages

Clear:
- `messages` list (reset to just system prompt)
- `EvidenceStore` (raw tool output archive)
- `Scratchpad` (investigation notes)

Preserve:
- `Engine`, `ToolExecutor`, `ToolsetManager` (no need to rebuild)
- `MemoryStore` (cross-session, not per-investigation)
- Current model selection

### D6: `-p` flag replaces `ask` subcommand

`-p` (print) follows the convention from cc-src. In this mode:
- Read question from positional arg (required)
- Wrap in investigate template
- Run `_render_stream` once
- Print answer
- Exit with code 0

## Module changes

### `cli.py` — complete rewrite

Remove: `ask()`, `chat()`, `toolset_list()` commands.

Add:
- `main()` — single entry point, handles `-p` and REPL
- `_repl_loop()` — interactive loop with slash command dispatch
- `_dispatch_slash()` — route `/xxx` to handler
- `_cmd_new()` — clear session state
- `_cmd_model()` — switch or show model
- `_cmd_toolset()` — show toolset status (reuse existing logic from old `toolset_list`)
- `_cmd_help()` — print available commands

### `core/llm.py` — no changes needed

`DefaultLLM` attributes are already mutable. `get_context_window_size()` already reads `self.model` dynamically.

### `core/engine.py` — no changes needed

`check_budget` already reads window size per-iteration. `compress_batch` already triggers on `COMPRESS` status.

### `core/context_manager.py` — no changes needed

`check_budget` calls `self.llm.get_context_window_size()` which reflects model changes automatically.

### `core/evidence_store.py` — add `clear()` method

For `/new` to reset stored raw tool outputs.

### `core/scratchpad.py` — add `clear()` method (if not present)

For `/new` to reset investigation notes.
