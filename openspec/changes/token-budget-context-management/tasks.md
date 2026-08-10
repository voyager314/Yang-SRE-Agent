## 1. Foundation: Data Structures & Storage

- [x] 1.1 Create `core/scratchpad.py`: Scratchpad dataclass with findings/hypotheses/ruled_out/next_steps fields, `update()` method, and `to_yaml()` serialization
- [x] 1.2 Create `core/evidence_store.py`: EvidenceStore class with `save(call_id, content) -> Path` and `load(call_id) -> str | None`, writing to `temp/tool-results/`
- [x] 1.3 Add unit tests for Scratchpad (update semantics, YAML serialization, empty state)
- [x] 1.4 Add unit tests for EvidenceStore (save/load round-trip, missing call_id returns None)

## 2. Toolset Compression

- [x] 2.1 Add `compress(tool_name: str, raw_output: str) -> str` method to `Toolset` base class with conservative default implementation (first 20 + last 5 lines + stats)
- [x] 2.2 Implement `compress()` in bash toolset: preserve exit code, stderr, error/warning lines from stdout
- [x] 2.3 Implement `compress()` in prometheus toolset: preserve query, time range, anomaly intervals, aggregated values
- [x] 2.4 Implement `compress()` in logs toolset: cluster by anomaly, preserve first/last occurrence, count, representative entries
- [x] 2.5 Add unit tests for each toolset's compress() with representative outputs

## 3. Context Manager

- [x] 3.1 Create `core/context_manager.py`: ContextManager class holding LLM reference, EvidenceStore, Scratchpad, and tool_name→Toolset mapping
- [x] 3.2 Implement `check_budget(messages, tools) -> BudgetStatus` returning NORMAL/COMPRESS/CONVERGE based on 70%/90% waterlines
- [x] 3.3 Implement `compress_immediate(call_id, tool_name, raw_output) -> str` for single-result compression on ingestion (threshold: 4K tokens)
- [x] 3.4 Implement `compress_batch(messages) -> messages` for bulk compression of older tool results when hitting 70% waterline (preserve recent 3-5 calls)
- [x] 3.5 Add unit tests for ContextManager (waterline calculation, immediate compression trigger, batch compression preserves recent results)

## 4. Built-in Tools

- [ ] 4.1 Define `update_scratchpad` tool schema (OpenAI function format) with four list[str] parameters
- [ ] 4.2 Define `recall_evidence` tool schema with call_id string parameter
- [ ] 4.3 Implement built-in tool execution logic: update_scratchpad updates Scratchpad object and returns confirmation; recall_evidence reads from EvidenceStore
- [ ] 4.4 Add unit tests for built-in tool execution (scratchpad update, evidence recall success/missing)

## 5. Engine Integration

- [ ] 5.1 Modify Engine.__init__ to accept and hold ContextManager instance
- [ ] 5.2 Modify Engine.call_stream loop: add budget check at start of each iteration
- [ ] 5.3 Implement graceful convergence path: inject convergence prompt with scratchpad, set tool_choice=none, yield ANSWER_END with converged=true
- [ ] 5.4 Implement built-in tool routing: before passing tool_calls to ToolExecutor, intercept update_scratchpad and recall_evidence
- [ ] 5.5 Implement immediate compression in tool result processing: after ToolExecutor returns, pass each result through ContextManager.compress_immediate
- [ ] 5.6 Inject scratchpad into system prompt each iteration (append to messages[0] or manage as dynamic system message)
- [ ] 5.7 Include built-in tool schemas in the tools list passed to LLM
- [ ] 5.8 Add integration tests for full engine loop: verify compression triggers, convergence triggers, scratchpad injection

## 6. CLI & Config Wiring

- [ ] 6.1 Update Config: change max_steps default to 50, add `compress_threshold` (0.70) and `converge_threshold` (0.90) config fields
- [ ] 6.2 Update `_build_engine` in cli.py: construct ContextManager with tool_name→Toolset mapping, pass to Engine
- [ ] 6.3 Update system prompt template (system.j2): add instructions for scratchpad usage and built-in tools description
- [ ] 6.4 Add ANSWER_END converged flag handling in `_render_stream`: display a note to user that convergence was triggered

## 7. Validation & Polish

- [ ] 7.1 Run full test suite, fix any regressions from engine refactor
- [ ] 7.2 Run ruff check and ruff format
- [ ] 7.3 Run mypy strict type checks, resolve new type errors
- [ ] 7.4 Manual smoke test: run `sre-agent ask` with a diagnostic question, verify compression and scratchpad behavior in verbose/debug output
