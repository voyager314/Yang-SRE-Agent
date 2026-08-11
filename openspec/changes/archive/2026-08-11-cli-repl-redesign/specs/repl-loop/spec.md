# Spec: REPL Loop

## Capability

Replace the three Typer subcommands (`ask`, `chat`, `toolset`) with a single main command that defaults to an interactive REPL.

## Requirements

### R1: Default interactive mode

`sre-agent` with no arguments enters the REPL loop. Display a welcome panel, then repeatedly prompt for input.

### R2: Initial question

`sre-agent "question"` enters the REPL with the question as the first user input. After the investigation completes, continue waiting for the next input instead of exiting.

### R3: Non-interactive mode

`sre-agent -p "question"` runs a single investigation, prints the answer, and exits. This replaces the old `ask` subcommand for pipe/CI usage.

### R4: Session state

The REPL loop owns:
- `messages: list[dict]` — conversation history, initialized with system prompt
- `engine: Engine` — shared across turns
- `config: Config` — loaded once at startup, available for model registry lookups

### R5: Input handling

- Empty input: skip, re-prompt
- Input starting with `/`: dispatch to slash command handler
- Any other input: append as user message, run investigation via `_render_stream`, append assistant answer, display with Markdown
- `Ctrl+D` / `Ctrl+C`: exit gracefully (same as `/exit`)
