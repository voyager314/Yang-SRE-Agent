# CLI REPL Redesign

## Problem

Current CLI uses a subcommand model (`ask`, `chat`, `toolset`) that doesn't match real usage:

- `ask` is one-shot, but SRE investigations are almost never single-turn
- `chat` must be explicitly entered; should be the default
- `toolset` prints info and exits; should stay in the CLI
- `chat` mode's `exit`/`quit` kills the entire process; no way to start a fresh investigation without restarting

## Solution

Replace the subcommand model with a single REPL that launches by default, controlled by slash commands.

### Entry points

| Invocation | Behavior |
|---|---|
| `sre-agent` | Enter REPL, wait for input |
| `sre-agent "question"` | Enter REPL with initial question, begin investigation, then wait for next input |
| `sre-agent -p "question"` | Non-interactive mode: investigate, print answer, exit (pipe/CI use) |

### Slash commands (inside REPL)

| Command | Aliases | Behavior | Context impact |
|---|---|---|---|
| `/new` | `/clear` | Clear messages, evidence store, scratchpad; start fresh investigation | Clears all |
| `/exit` | `/quit` | Exit the process | N/A |
| `/model [name]` | | No args: show current model + available models from registry. With arg: switch to named model | Preserves messages; compress deferred to next query |
| `/toolset` | | Display toolset names, tool counts, prerequisite status | Preserves all |
| `/help` | | Show available commands | Preserves all |

### Model switching details

`/model <name>` resolves via `Config.resolve_model()` → `ModelEntry`, then updates all connection params on the existing `DefaultLLM` instance in-place:

- `llm.model`
- `llm.api_key`
- `llm.api_base`
- `llm.api_version`

Since `Engine.llm` and `ContextManager.llm` are the same object reference, one mutation propagates everywhere. Context window adaptation is handled by the existing `check_budget` guard at the top of the engine loop — if the new model's window makes current messages exceed `compress_threshold`, `compress_batch` fires automatically on the next query. No special handling at switch time.

## Removed

- `ask` subcommand (replaced by `-p` flag for non-interactive mode)
- `chat` subcommand (REPL is now the default)
- `toolset` subcommand (replaced by `/toolset` slash command)

## Non-goals

- Interactive model picker UI (simple name-based switching is sufficient)
- Session persistence / resume across process restarts
- Config hot-reload beyond model switching
