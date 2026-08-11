## Purpose

运行时模型切换，在不丢失对话上下文的前提下更换 LLM 模型及其全部连接参数。

## ADDED Requirements

### Requirement: Show current model
系统 SHALL 在 `/model` 无参数时显示当前模型信息及注册表中所有可用模型。

#### Scenario: 查看当前模型
- **WHEN** 用户输入 `/model`
- **THEN** 系统显示当前模型名称、标识符、API 地址，以及注册表中所有模型的列表

### Requirement: Switch model
系统 SHALL 在 `/model <name>` 时从配置注册表解析完整连接配置并就地更新 LLM 实例。

#### Scenario: 切换到注册表模型
- **WHEN** 用户输入 `/model fast`（其中 fast 在注册表中）
- **THEN** 系统更新 LLM 的 model、api_key、api_base、api_version 字段，显示切换确认

#### Scenario: 切换到未注册模型
- **WHEN** 用户输入 `/model some-unknown-model`（不在注册表中）
- **THEN** 系统将输入直接作为 LiteLLM 模型标识符使用，显示提示信息

### Requirement: Context preservation on switch
系统 SHALL 在模型切换时保留完整的对话历史，不清空消息列表。

#### Scenario: 切换后对话延续
- **WHEN** 用户在有对话历史的 REPL 中切换模型后继续提问
- **THEN** 新模型接收到包含之前所有对话的完整上下文

### Requirement: Deferred context window adaptation
系统 SHALL 在模型切换时不主动压缩上下文，而是延迟到下一轮查询时由引擎的预算检查自动处理。

#### Scenario: 切换到小窗口模型
- **WHEN** 用户从 200K 窗口模型切换到 8K 窗口模型且当前消息超过新模型的压缩阈值
- **THEN** 下一轮查询开始时引擎自动触发批量压缩
