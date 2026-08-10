## ADDED Requirements

### Requirement: Memory configuration fields

配置系统 SHALL 支持 memory 相关的配置字段。

#### Scenario: memory 开关
- **WHEN** config.yaml 设置 `memory_enabled: false`
- **THEN** 系统不初始化 Embedder 和 MemoryStore

#### Scenario: memory 默认启用
- **WHEN** config.yaml 未设置 memory_enabled 字段
- **THEN** memory 功能默认启用

#### Scenario: 存储目录配置
- **WHEN** config.yaml 设置 `memory_dir: "/custom/path/memory"`
- **THEN** ChromaDB 数据和 JSON 归档写入指定目录

#### Scenario: 存储目录默认值
- **WHEN** config.yaml 未设置 memory_dir
- **THEN** 使用 `~/.sre-agent/memory/` 作为默认目录

#### Scenario: embedding 模型配置
- **WHEN** config.yaml 设置 `embedding_model: "BAAI/bge-large-zh-v1.5"`
- **THEN** Embedder 加载指定模型

#### Scenario: embedding 模型默认值
- **WHEN** config.yaml 未设置 embedding_model
- **THEN** 使用 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` 作为默认模型

#### Scenario: 检索数量配置
- **WHEN** config.yaml 设置 `memory_top_k: 5`
- **THEN** 语义检索返回最多 5 条结果

#### Scenario: 检索数量默认值
- **WHEN** config.yaml 未设置 memory_top_k
- **THEN** 默认检索 top-3

#### Scenario: 分数阈值配置
- **WHEN** config.yaml 设置 `memory_score_threshold: 0.8`
- **THEN** 仅返回相似度分数 >= 0.8 的结果

#### Scenario: 分数阈值默认值
- **WHEN** config.yaml 未设置 memory_score_threshold
- **THEN** 默认阈值为 0.6

#### Scenario: 环境变量覆盖
- **WHEN** 环境变量 `SRE_AGENT_MEMORY_ENABLED=false` 存在
- **THEN** 覆盖 config.yaml 中的 memory_enabled 设置
