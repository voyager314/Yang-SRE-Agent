## Purpose

CLI 交互层，提供 Typer 命令行界面，支持单次问答和多轮交互 REPL 模式，使用 Rich 渲染输出。

## ADDED Requirements

### Requirement: Single-shot ask command
系统 SHALL 提供 `sre-agent ask "<question>"` 命令，执行一次智能体循环并输出诊断结论。

#### Scenario: 单次问答
- **WHEN** 用户执行 `sre-agent ask "为什么 checkout-service 502"`
- **THEN** 系统加载配置、初始化引擎、执行 agentic loop、在终端实时显示工具调用过程、最终输出诊断结论

#### Scenario: 指定模型
- **WHEN** 用户执行 `sre-agent ask --model claude-sonnet "分析 OOM 原因"`
- **THEN** 系统使用指定模型执行查询

### Requirement: Interactive REPL mode
系统 SHALL 提供 `sre-agent chat` 命令进入多轮交互模式，保持对话上下文。

#### Scenario: 进入 REPL
- **WHEN** 用户执行 `sre-agent chat`
- **THEN** 系统进入交互模式，显示提示符等待用户输入

#### Scenario: 多轮对话
- **WHEN** 用户在 REPL 中连续提问两个问题
- **THEN** 第二个问题的对话上下文包含第一个问题及其回答的历史

#### Scenario: 退出 REPL
- **WHEN** 用户输入 `exit` 或按 Ctrl+C
- **THEN** 系统优雅退出交互模式

### Requirement: Rich terminal output
系统 SHALL 使用 Rich 库渲染终端输出，工具调用过程实时显示，最终结论格式化呈现。

#### Scenario: 工具调用进度显示
- **WHEN** 引擎执行工具调用
- **THEN** 终端实时显示工具名称、参数摘要、执行状态（运行中/完成/失败）

#### Scenario: 最终结论渲染
- **WHEN** 引擎返回最终回答
- **THEN** 终端以 Markdown 格式渲染诊断结论

### Requirement: Toolset list command
系统 SHALL 提供 `sre-agent toolset` 命令列出所有工具集及其状态。

#### Scenario: 列出工具集
- **WHEN** 用户执行 `sre-agent toolset list`
- **THEN** 系统显示所有已注册工具集的名称、状态（可用/不可用）、工具数量
