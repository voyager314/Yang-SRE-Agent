# Spec: Model Switch

## Capability

Switch the active LLM model at runtime without losing conversation context.

## Requirements

### R1: Show current model

`/model` with no arguments displays:
- Current model name (registry key or raw model string)
- Full model identifier (`ModelEntry.model`)
- API base URL if non-default
- List of all models available in the registry with a marker on the active one

### R2: Switch model

`/model <name>` resolves `name` via `Config.resolve_model(name)` and updates the `DefaultLLM` instance in-place:
- `llm.model = entry.model`
- `llm.api_key = entry.api_key.get_secret_value() if entry.api_key else None`
- `llm.api_base = entry.api_base`
- `llm.api_version = entry.api_version`

Print confirmation: `Switched to: <name> (<entry.model>)`

### R3: Unknown model name

If the name is not in the registry, `resolve_model` returns `ModelEntry(model=name)` with no api_key/base. This is valid — the user may have credentials configured via environment variables. Print a note: `Model '<name>' not in registry, using as raw LiteLLM identifier`.

### R4: Context window adaptation

No compress at switch time. The engine's `check_budget()` at the top of each loop iteration dynamically reads `llm.get_context_window_size()`. If the new model's window is smaller and existing messages exceed `compress_threshold`, `compress_batch` fires automatically on the next investigation turn.

### R5: Messages preserved

Conversation history (`messages` list) is not modified by `/model`. The next turn uses the new model with the full existing context (subject to R4 compression).

### R6: Track current model name for display

Store the registry key (e.g. `"gpt4"`) separately from `llm.model` (e.g. `"gpt-4o"`) so `/model` can display both the friendly name and the underlying model identifier.
