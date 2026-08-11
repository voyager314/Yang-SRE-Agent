## Purpose

REPL 内斜杠命令系统，提供会话控制、状态清理、工具集查看和帮助等功能，无需退出交互界面。

## ADDED Requirements

### Requirement: Slash command dispatch
系统 SHALL 将以 `/` 开头的输入识别为斜杠命令，按命令名分发到对应处理器。

#### Scenario: 已知命令
- **WHEN** 用户输入 `/help`
- **THEN** 系统执行帮助命令并继续等待下一个输入

#### Scenario: 未知命令
- **WHEN** 用户输入 `/nonexistent`
- **THEN** 系统显示错误提示并继续等待下一个输入

### Requirement: New investigation command
系统 SHALL 提供 `/new`（别名 `/clear`）命令清空当前调查状态并开始新会话。

#### Scenario: 清空会话
- **WHEN** 用户在有对话历史的 REPL 中输入 `/new`
- **THEN** 系统清空消息历史、证据库、调查记录本，保留引擎和模型选择，显示确认信息

### Requirement: Exit command
系统 SHALL 提供 `/exit`（别名 `/quit`）命令退出 REPL。

#### Scenario: 正常退出
- **WHEN** 用户输入 `/exit`
- **THEN** 系统显示告别信息并以 0 退出码退出进程

### Requirement: Toolset status command
系统 SHALL 提供 `/toolset` 命令显示所有工具集的状态。

#### Scenario: 显示工具集
- **WHEN** 用户输入 `/toolset`
- **THEN** 系统显示所有工具集的名称、可用状态、工具数量和工具名称

### Requirement: Help command
系统 SHALL 提供 `/help` 命令列出所有可用的斜杠命令及其简要说明。

#### Scenario: 显示帮助
- **WHEN** 用户输入 `/help`
- **THEN** 系统显示命令列表及描述
