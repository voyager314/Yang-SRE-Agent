## Purpose

LLM 抽象层，通过 litellm 统一封装多个模型提供商，提供 completion、token 计数和模型注册能力。

## ADDED Requirements

### Requirement: Multi-provider LLM completion
系统 SHALL 通过统一接口调用多个 LLM 提供商（OpenAI、Anthropic、Azure、Bedrock、Ollama），底层使用 litellm 路由。

#### Scenario: 调用 OpenAI 模型
- **WHEN** 用户配置模型为 `gpt-4.1` 并提供有效 API key
- **THEN** 系统通过 litellm 向 OpenAI 发送 completion 请求并返回响应

#### Scenario: 调用 Anthropic 模型
- **WHEN** 用户配置模型为 `anthropic/claude-sonnet-4-5-20250929`
- **THEN** 系统通过 litellm 向 Anthropic 发送 completion 请求并返回响应

#### Scenario: 模型不可用
- **WHEN** 配置的模型 API key 无效或服务不可达
- **THEN** 系统 SHALL 抛出明确的错误信息，包含模型名称和失败原因

### Requirement: Token counting
系统 SHALL 提供 token 计数能力，用于上下文窗口管理。

#### Scenario: 计算消息 token 数
- **WHEN** 传入一组 messages 和 tools 定义
- **THEN** 系统返回该组合的 token 数量估算值

### Requirement: Model registry
系统 SHALL 支持从配置文件加载多个模型定义，每个模型包含 model name、api_key、base_url 等字段。

#### Scenario: 加载模型列表
- **WHEN** `~/.sre-agent/models.yaml` 存在且包含多个模型定义
- **THEN** 系统加载所有模型到注册表，可通过别名引用

#### Scenario: 模型选择优先级
- **WHEN** CLI `--model` 参数、环境变量 `MODEL`、config.yaml `model` 字段同时存在
- **THEN** 优先级为 CLI > 环境变量 > config.yaml > models.yaml 第一个
