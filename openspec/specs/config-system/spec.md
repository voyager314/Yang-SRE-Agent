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
