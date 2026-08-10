## Why

SRE Agent 的记忆完全限于单次会话。EvidenceStore 按 call_id 存储工具原文但无法语义检索，Scratchpad 追踪当次调查状态但会话结束即丢失。这意味着 agent 每次调查都从零开始——即使上周刚处理过完全相同的 OOM 问题，也无法回忆诊断路径、根因和解决方案。引入跨会话调查记忆系统，让 agent 能在新调查开始时自动检索并参考相关的历史经验。

## What Changes

- 新增 `Embedder` 抽象及 `SentenceTransformerEmbedder` 实现，使用 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` 模型本地生成 1536 维嵌入向量，首次运行自动下载模型
- 新增 `MemoryStore` 模块，基于 ChromaDB PersistentClient 实现调查摘要的持久化存储和语义检索
- 新增 `InvestigationSummary` 数据模型，结构化记录调查问题、结论、根因、解决方案、关键证据、工具使用和领域标签
- 新增 SRE 领域特化的提取 prompt 模板，调查结束后自动触发一次 LLM 调用从对话历史 + Scratchpad + 最终回答中提取结构化摘要
- 修改 Engine，在调查循环前执行语义检索并注入相关历史到 system prompt，在调查循环后触发摘要提取和存储
- 修改 Config，新增 memory 相关配置项（开关、存储目录、embedding 模型、检索参数）
- 新增 `chromadb` 和 `sentence-transformers` 依赖

## Capabilities

### New Capabilities
- `investigation-memory`: 跨会话调查记忆的提取、持久化存储和语义检索
- `embedder`: 本地文本嵌入向量生成

### Modified Capabilities
- `agentic-engine`: 新增调查前记忆检索注入和调查后摘要提取存储的生命周期钩子
- `config-system`: 新增 memory 相关配置字段

## Impact

- **新增文件**: `core/embedder.py`, `core/memory_store.py`, `prompts/extract_summary.j2`
- **修改文件**: `core/engine.py`, `config.py`, `cli.py`, `pyproject.toml`
- **不变文件**: `llm.py`, `evidence_store.py`, `scratchpad.py`, `context_manager.py`, `tool.py`, `tool_executor.py`, `toolset_manager.py`, `builtin_tools.py`
- **新增依赖**: `chromadb`, `sentence-transformers`（影响安装体积和首次启动时间）
- **存储**: 在 `~/.sre-agent/memory/` 下新增 ChromaDB 数据目录和 JSON 归档目录
- **首次运行**: 自动下载 embedding 模型（约 3.6GB），需要网络连接
