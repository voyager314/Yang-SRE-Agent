## Purpose

本地文本嵌入向量生成，基于 sentence-transformers 提供零外部依赖的 embedding 能力。

## ADDED Requirements

### Requirement: Embedding abstraction

系统 SHALL 提供 Embedder 抽象接口，将 embedding 实现与业务逻辑解耦。

#### Scenario: 接口契约
- **WHEN** 调用 Embedder.embed() 传入文本列表
- **THEN** 返回对应的浮点向量列表，每个向量的维度与所用模型一致

#### Scenario: 单文本 embedding
- **WHEN** 传入包含 1 个字符串的列表
- **THEN** 返回包含 1 个向量的列表

#### Scenario: 批量 embedding
- **WHEN** 传入包含多个字符串的列表
- **THEN** 返回等长的向量列表，顺序与输入一致

### Requirement: SentenceTransformer implementation

系统 SHALL 提供基于 sentence-transformers 的默认 Embedder 实现，使用 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` 模型。

#### Scenario: 模型自动下载
- **WHEN** 首次创建 SentenceTransformerEmbedder 且本地无模型缓存
- **THEN** 自动从 HuggingFace Hub 下载 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` 模型

#### Scenario: 后续启动使用缓存
- **WHEN** 模型已下载到本地缓存
- **THEN** 直接从缓存加载，不再下载

#### Scenario: 向量维度
- **WHEN** 使用 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` 模型生成 embedding
- **THEN** 每个向量为 1536 维

#### Scenario: 模型加载失败
- **WHEN** 模型文件损坏或下载中断
- **THEN** 抛出明确的异常，由调用方决定降级策略

### Requirement: Embedding model configurability

Embedder 使用的模型 SHALL 可通过配置覆盖。

#### Scenario: 使用默认模型
- **WHEN** 未配置 embedding_model
- **THEN** 使用 `Alibaba-NLP/gte-Qwen2-1.5B-instruct`

#### Scenario: 配置自定义模型
- **WHEN** 配置 `embedding_model: "BAAI/bge-large-zh-v1.5"`
- **THEN** Embedder 加载并使用指定模型
