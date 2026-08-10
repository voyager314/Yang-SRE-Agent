## Purpose

跨会话调查记忆的提取、持久化存储和语义检索，让 agent 在新调查中自动参考相关的历史诊断经验。

## ADDED Requirements

### Requirement: Investigation summary data model

系统 SHALL 以结构化的 InvestigationSummary 为记忆单元，每次完整调查产生一条记忆。

#### Scenario: 摘要字段完整性
- **WHEN** 一次调查结束并触发摘要提取
- **THEN** 生成的 InvestigationSummary 包含以下字段：id、question、conclusion、root_cause、resolution、tools_used、key_evidence、tags、timestamp、evidence_refs、converged

#### Scenario: ID 唯一性
- **WHEN** 两次调查在同一秒内完成
- **THEN** 它们的 id 仍然唯一，不会冲突

### Requirement: Summary extraction

调查结束后系统 SHALL 自动触发一次 LLM 调用，从对话历史和 Scratchpad 状态中提取结构化摘要。

#### Scenario: 正常调查结束后提取
- **WHEN** Engine 的调查循环正常结束（模型给出最终回答）
- **THEN** 系统使用调查所用的同一 LLM 模型，以对话消息、Scratchpad 状态和最终回答为输入，提取 InvestigationSummary

#### Scenario: 强制收敛后提取
- **WHEN** 调查因 token 预算耗尽被强制收敛
- **THEN** 系统同样触发摘要提取，且 converged 字段标记为 true

#### Scenario: 提取失败不阻塞
- **WHEN** LLM 摘要提取调用失败（网络错误、格式解析失败等）
- **THEN** 系统记录警告日志但不抛出异常，调查结果正常返回给用户

### Requirement: Memory persistence

系统 SHALL 将 InvestigationSummary 持久化到两个存储层：ChromaDB 向量库和本地 JSON 文件。

#### Scenario: ChromaDB 持久化
- **WHEN** InvestigationSummary 提取成功
- **THEN** 系统将 embedding 向量、文档文本和 metadata 写入 ChromaDB collection

#### Scenario: JSON 归档
- **WHEN** InvestigationSummary 提取成功
- **THEN** 系统将完整的 InvestigationSummary 以 JSON 格式写入 `~/.sre-agent/memory/investigations/{id}.json`

#### Scenario: 存储目录自动创建
- **WHEN** 首次存储且 `~/.sre-agent/memory/` 目录不存在
- **THEN** 系统自动创建所需的目录结构

### Requirement: Embedding text composition

系统 SHALL 仅从 InvestigationSummary 的语义核心字段生成嵌入向量，而非拼接全部字段。

#### Scenario: 嵌入文本构成
- **WHEN** 需要对 InvestigationSummary 生成 embedding
- **THEN** 嵌入文本由 question、conclusion 和 key_evidence 拼接组成

#### Scenario: metadata 不参与 embedding
- **WHEN** InvestigationSummary 包含 tools_used、tags、timestamp 等字段
- **THEN** 这些字段作为 ChromaDB metadata 存储，用于过滤查询，不参与向量相似度计算

### Requirement: Semantic recall

系统 SHALL 支持按语义相似度检索历史调查摘要。

#### Scenario: 基本语义检索
- **WHEN** 用户提出新问题 "order-svc 频繁重启"
- **THEN** 系统生成查询向量，在 ChromaDB 中检索 top-k 个最相似的历史调查摘要

#### Scenario: 分数阈值过滤
- **WHEN** 检索结果中某条摘要的相似度分数低于配置的阈值
- **THEN** 该条摘要不包含在返回结果中

#### Scenario: 无历史记忆
- **WHEN** ChromaDB collection 为空（首次使用）
- **THEN** 检索返回空列表，不报错

### Requirement: Memory context injection

检索到的历史调查摘要 SHALL 以结构化格式注入 system prompt 尾部，供 LLM 参考。

#### Scenario: 有相关历史时注入
- **WHEN** 语义检索返回 1 条或多条相关历史调查
- **THEN** 系统在 system prompt 尾部追加"以往相关调查"区域，每条摘要包含问题、结论、根因、关键证据和相似度分数

#### Scenario: 无相关历史时不注入
- **WHEN** 语义检索返回空列表
- **THEN** system prompt 不追加任何额外内容

#### Scenario: 注入内容 token 预算
- **WHEN** 检索到多条历史调查
- **THEN** 注入的总 token 量不超过 context window 的合理比例，避免挤压调查工作空间

### Requirement: Memory disabled gracefully

系统 SHALL 在 memory 功能禁用时完全跳过记忆相关操作，不影响现有调查流程。

#### Scenario: 配置禁用 memory
- **WHEN** 配置 `memory_enabled: false`
- **THEN** 系统不初始化 Embedder 和 MemoryStore，不做检索和提取，调查流程与功能引入前完全一致

#### Scenario: embedding 模型不可用
- **WHEN** embedding 模型下载失败或加载失败
- **THEN** 系统记录警告并降级为 memory 禁用模式，调查流程正常继续
