## Context

见 proposal.md — Why。当前系统已有三个与 memory 相关的组件：EvidenceStore（工具原文落盘）、Scratchpad（当次调查状态追踪）、ContextManager（token 预算管理和压缩）。本设计在不修改这三个组件的前提下，新增跨会话记忆层。

现有数据流：`用户问题 → Engine 循环 → 工具调用 + Scratchpad → 最终回答`。新增数据流在循环前后各加一步：`recall → 现有循环 → extract + save`。

## Goals / Non-Goals

**Goals:**
- 调查结束后自动提取结构化摘要并持久化
- 新调查开始时自动检索语义相关的历史调查并注入上下文
- Embedding 完全本地推理，零外部 API 依赖
- memory 功能可通过配置禁用，禁用时零性能开销
- 提取或检索失败不阻塞调查流程

**Non-Goals:**
- 不替换 EvidenceStore 或 Scratchpad，不修改现有压缩逻辑
- 不提供 memory 的增删改查 CLI 命令（未来可加）
- 不做跨用户的记忆共享
- 不做 memory 的过期淘汰或容量管理（初版不限制）
- 不对单条工具输出做独立索引（粒度为完整调查）

## Decisions

### Decision 1: Embedder 独立于 LLM 抽象层

**选择**: 新建 `Embedder` 抽象和 `SentenceTransformerEmbedder` 实现，不在 `LLM` 接口上加 `embed()` 方法。

**理由**: LLM（LiteLLM）和 Embedder（sentence-transformers）是完全不同的运行时——前者是远程 API 调用，后者是本地模型推理。合并会污染 LLM 接口，mock 测试也更复杂。

**替代方案**: 在 `LLM` 上加 `embed()` 方法，通过 LiteLLM 调用云端 embedding API。否决原因：引入外部 API 依赖，与 CLI 工具零基础设施的定位矛盾。

### Decision 2: ChromaDB 嵌入式模式 + 自管理 embedding

**选择**: 使用 `chromadb.PersistentClient`，embedding 由 Embedder 预生成后传入，ChromaDB 仅存储和检索。

**理由**: ChromaDB 内置 embedding function 不支持 `trust_remote_code=True` 的模型。自管理 embedding 也让 Embedder 实现可替换，不与存储层耦合。

**替代方案**: 使用 ChromaDB 内置 `SentenceTransformerEmbeddingFunction`。否决原因：不支持 gte-Qwen2 等需要 `trust_remote_code` 的模型。

### Decision 3: 调查结束后被动提取，而非 Agent 主动存储

**选择**: Engine 在调查循环结束后自动触发 LLM 提取，Agent 不感知 memory 系统的存在。

**理由**: Agent 主动存储（MemGPT 风格）需要在工具列表中注册 memory 工具并修改 system prompt 引导 agent 使用，侵入性大。被动提取对现有循环的改动最小——只在 `call_stream()` 末尾加一步。

**替代方案**: 注册 `save_memory` / `search_memory` 工具让 Agent 自主管理。否决原因：初版先验证记忆价值，自主管理可作为后续演进。

### Decision 4: 提取 prompt 走 Jinja 模板

**选择**: 提取 prompt 放在 `prompts/extract_summary.j2`，复用现有 `utils/jinja.py` 的模板渲染。

**理由**: 与现有的 system prompt 和 investigate prompt 保持一致的模板管理方式。修改提取逻辑只需编辑模板，无需改代码。

### Decision 5: 双写存储（ChromaDB + JSON 文件）

**选择**: 每条 InvestigationSummary 同时写入 ChromaDB（用于检索）和 JSON 文件（用于归档）。

**理由**: ChromaDB 是索引层，JSON 是真相源。如果 ChromaDB 数据损坏或 embedding 模型更换，可从 JSON 重建索引。JSON 也便于人工审查和调试。

### Decision 6: Engine 通过可选参数接收 MemoryStore

**选择**: `Engine.__init__()` 新增 `memory_store: MemoryStore | None = None` 参数，为 None 时跳过所有记忆操作。

**理由**: 保持向后兼容——不传 memory_store 时 Engine 行为与修改前完全一致。测试也可以不构造 MemoryStore。

### Decision 7: SentenceTransformerEmbedder 延迟加载模型

**选择**: 模型在首次调用 `embed()` 时加载，而非 `__init__` 时。

**理由**: 当 `memory_enabled=false` 或调查未使用 memory 路径时，避免加载 3.6GB 模型的启动开销。首次 embed 会有几秒加载延迟，但只发生一次。

## Risks / Trade-offs

- **[首次启动延迟]** 首次运行需下载约 3.6GB 模型。→ 缓解：下载后缓存在 HuggingFace 默认目录，后续启动秒级加载。可考虑未来加 `sre-agent setup` 命令预下载。
- **[内存占用]** gte-Qwen2-1.5B-instruct fp16 约占 3GB 显存/内存。→ 缓解：延迟加载，仅在 memory 启用且实际触发时加载。CPU 推理可用但较慢。
- **[提取质量]** LLM 提取的摘要可能遗漏关键细节或产生不准确的标签。→ 缓解：提取 prompt 做 SRE 领域特化，且 JSON 归档保留完整 summary 供人工审查；原文仍在 EvidenceStore。
- **[ChromaDB 数据增长]** 不限制 collection 大小，长期使用可能膨胀。→ 接受：初版不做淘汰，后续根据实际数据量决定策略。
- **[提取的额外 LLM 调用]** 每次调查结束多一次 LLM 请求。→ 接受：摘要提取的输入量远小于调查本身，成本可忽略。
