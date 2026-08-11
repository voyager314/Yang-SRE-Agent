# Spec: Slash Commands

## Capability

Provide REPL-internal commands prefixed with `/` that control session state without leaving the REPL.

## Requirements

### R1: Command dispatch

Input starting with `/` is split into command name and arguments. Unknown commands print an error message and continue the loop.

### R2: `/new` (aliases: `/clear`)

Clear all investigation state and start fresh:
- Reset `messages` to `[system_prompt]`
- Call `evidence_store.clear()`
- Call `scratchpad.clear()`
- Print confirmation message
- Do NOT rebuild Engine, ToolsetManager, or MemoryStore
- Do NOT change the current model selection

### R3: `/exit` (aliases: `/quit`)

Print goodbye message and break the REPL loop. Process exits with code 0.

### R4: `/toolset`

Display all toolsets with:
- Status icon (available / unavailable)
- Toolset name
- Tool count and tool names
- Failure reason if unavailable

Reuse the display logic from the old `toolset_list` command. Output inline, then continue the loop.

### R5: `/help`

Print a table of available slash commands with short descriptions.

### R6: `/model` — see `model-switch/spec.md`
