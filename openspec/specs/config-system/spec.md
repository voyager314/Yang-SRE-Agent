## Purpose

配置系统，支持从 YAML 文件、环境变量、CLI 参数加载配置，管理模型列表和工具集配置。

## ADDED Requirements

### Requirement: YAML config loading
系统 SHALL 从 `~/.sre-agent/config.yaml` 加载配置，支持模型、工具集、max_steps 等字段。

#### Scenario: 加载默认配置文件
- **WHEN** `~/.sre-agent/config.yaml` 存在
- **THEN** 系统解析文件并填充 Config 对象

#### Scenario: 配置文件不存在
- **WHEN** `~/.sre-agent/config.yaml` 不存在
- **THEN** 系统使用默认配置运行（需至少通过环境变量或 CLI 提供模型配置）

### Requirement: Environment variable override
配置字段 SHALL 支持环境变量覆盖，环境变量优先级高于配置文件。

#### Scenario: 环境变量覆盖模型
- **WHEN** config.yaml 设置 `model: gpt-4.1` 但环境变量 `SRE_AGENT_MODEL=claude-sonnet` 存在
- **THEN** 系统使用 claude-sonnet 作为默认模型

### Requirement: CLI argument override
CLI 参数 SHALL 具有最高配置优先级，覆盖环境变量和配置文件。

#### Scenario: CLI 覆盖模型
- **WHEN** 环境变量和配置文件都设了模型，用户执行 `sre-agent ask --model gpt-4.1 "..."`
- **THEN** 系统使用 CLI 指定的 gpt-4.1

### Requirement: Toolset configuration
配置文件 SHALL 支持工具集级别的配置，包括 enabled 开关和工具集特有的 config 字段。

#### Scenario: 禁用工具集
- **WHEN** config.yaml 设置 `toolsets: {bash: {enabled: false}}`
- **THEN** bash 工具集不加载

#### Scenario: 工具集配置传递
- **WHEN** config.yaml 设置 `toolsets: {prometheus: {config: {url: "http://prom:9090"}}}`
- **THEN** Prometheus 工具集接收到 url 配置并使用它连接

### Requirement: Config validation
系统 SHALL 在启动时验证配置，对缺失必要字段或无效值给出清晰错误。

#### Scenario: 无模型配置
- **WHEN** 未通过任何方式配置模型（无 config.yaml model 字段、无 MODEL 环境变量、无 CLI --model）
- **THEN** 系统启动时报错提示"未配置模型，请设置 model 字段或 MODEL 环境变量"

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
