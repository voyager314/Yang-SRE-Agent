## 1. Dependencies and Configuration

- [x] 1.1 Add `chromadb` and `sentence-transformers` to `pyproject.toml` dependencies
- [x] 1.2 Add memory configuration fields to `Config` in `src/sre_agent/config.py`: `memory_enabled` (bool, default True), `memory_dir` (str, default `~/.sre-agent/memory`), `embedding_model` (str, default `Alibaba-NLP/gte-Qwen2-1.5B-instruct`), `memory_top_k` (int, default 3), `memory_score_threshold` (float, default 0.6)

## 2. Embedder Module

- [x] 2.1 Create `src/sre_agent/core/embedder.py` with `Embedder` ABC defining `embed(texts: list[str]) -> list[list[float]]`
- [x] 2.2 Implement `SentenceTransformerEmbedder` in the same file: lazy-load model on first `embed()` call, use `trust_remote_code=True`, return 1536-dim vectors for the default model

## 3. Investigation Summary Data Model

- [x] 3.1 Create `src/sre_agent/core/memory_store.py` with `InvestigationSummary` Pydantic model containing fields: id, question, conclusion, root_cause, resolution, tools_used, key_evidence, tags, timestamp, evidence_refs, converged
- [x] 3.2 Implement `InvestigationSummary.to_embedding_text()` that concatenates question, conclusion, and key_evidence for embedding input
- [x] 3.3 Implement `InvestigationSummary.to_chroma_metadata()` that returns tools_used, tags, timestamp, converged as a flat metadata dict for ChromaDB

## 4. Extraction Prompt

- [x] 4.1 Create `src/sre_agent/prompts/extract_summary.j2` with SRE-domain-specialized extraction prompt template accepting question, answer, scratchpad_yaml, and tool_calls_summary variables, instructing the LLM to return JSON with conclusion, root_cause, resolution, key_evidence, and tags fields

## 5. MemoryStore Core

- [x] 5.1 Implement `MemoryStore.__init__()` in `memory_store.py`: accept embedder, llm, memory_dir, top_k, score_threshold; initialize ChromaDB `PersistentClient` at `{memory_dir}/chroma/` and get_or_create collection `sre_investigations` with `embedding_function=None`; create JSON archive dir at `{memory_dir}/investigations/`
- [x] 5.2 Implement `MemoryStore.save_investigation()`: accept question, answer, scratchpad, tool_calls, evidence_refs, converged; render extraction prompt via `load_prompt`; call `llm.completion()` to extract structured summary; parse JSON response into `InvestigationSummary`; generate unique id (`inv_{timestamp}_{hash}`); embed via `embedder.embed()`; upsert into ChromaDB with embedding, document text, and metadata; write JSON file to archive dir; wrap entire flow in try/except logging warnings on failure
- [x] 5.3 Implement `MemoryStore.recall()`: accept query string; embed query via `embedder.embed()`; query ChromaDB collection with `n_results=top_k` and `include=["documents", "metadatas", "distances"]`; filter results by score_threshold; reconstruct and return `list[InvestigationSummary]`

## 6. Engine Integration

- [x] 6.1 Add `memory_store: MemoryStore | None = None` parameter to `Engine.__init__()`
- [x] 6.2 Add pre-investigation recall in `Engine.call_stream()`: before the main loop, if memory_store is not None, extract user question from messages, call `memory_store.recall()`, and inject results into a shallow-copied system message (similar to `_inject_scratchpad` pattern); wrap in try/except with warning log
- [x] 6.3 Add post-investigation save in `Engine.call_stream()`: after the final `ANSWER_END` yield, if memory_store is not None, call `memory_store.save_investigation()` with the accumulated question, answer, scratchpad state, tool call IDs, and converged flag; wrap in try/except with warning log
- [x] 6.4 Implement `_inject_memories()` helper function that formats recalled `InvestigationSummary` list into a structured text block appended to system prompt (question, conclusion, root_cause, key_evidence, similarity score per entry)

## 7. CLI Wiring

- [x] 7.1 Update `_build_engine()` in `src/sre_agent/cli.py`: when `config.memory_enabled` is True, create `SentenceTransformerEmbedder(config.embedding_model)` and `MemoryStore(embedder, llm, ...)` with config values; wrap in try/except to gracefully disable memory if initialization fails; pass memory_store to `Engine()`
- [x] 7.2 Verify `ask` and `chat` commands both use the updated `_build_engine()` and thus automatically get memory recall/save behavior

## 8. Tests

- [x] 8.1 Add unit tests for `SentenceTransformerEmbedder`: test embed returns correct shape, test lazy loading behavior (mock SentenceTransformer to avoid downloading model in CI)
- [x] 8.2 Add unit tests for `InvestigationSummary`: test to_embedding_text composition, test to_chroma_metadata output, test unique id generation
- [x] 8.3 Add unit tests for `MemoryStore.save_investigation()`: mock LLM and embedder, verify ChromaDB upsert and JSON file creation, verify failure handling
- [x] 8.4 Add unit tests for `MemoryStore.recall()`: mock embedder and ChromaDB, verify score filtering, verify empty collection handling
- [x] 8.5 Add integration tests for Engine with MemoryStore: mock LLM and embedder, verify recall is called before loop and save is called after, verify memory_store=None preserves original behavior
- [x] 8.6 Add unit tests for Config memory fields: verify defaults, verify environment variable override, verify YAML loading

## 9. Validation

- [ ] 9.1 Run `uv run pytest` and verify all tests pass
- [ ] 9.2 Run `uv run ruff check .` and `uv run ruff format --check .` and fix any issues
- [ ] 9.3 Run `uv run mypy src` and resolve type errors
