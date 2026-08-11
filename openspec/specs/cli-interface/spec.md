## Purpose

CLI 交互层，提供统一的 REPL 界面，默认进入交互模式，支持斜杠命令控制会话，使用 Rich 渲染输出。

## ADDED Requirements

### Requirement: Default REPL entry
系统 SHALL 在无参数启动时直接进入交互式 REPL 循环，显示欢迎面板后等待用户输入。

#### Scenario: 无参数启动
- **WHEN** 用户执行 `sre-agent`
- **THEN** 系统进入 REPL 循环，显示提示符等待用户输入

### Requirement: Initial question entry
系统 SHALL 在启动时接受可选的位置参数作为初始问题，执行调查后继续等待输入。

#### Scenario: 带初始问题启动
- **WHEN** 用户执行 `sre-agent "为什么 checkout-service 502"`
- **THEN** 系统立即开始调查该问题，完成后继续等待下一个输入

### Requirement: Non-interactive print mode
系统 SHALL 提供 `-p`/`--print` 标志进入非交互模式，执行一次调查后退出。

#### Scenario: 管道模式
- **WHEN** 用户执行 `sre-agent -p "检查磁盘使用率"`
- **THEN** 系统执行调查、输出结论、退出进程

#### Scenario: 缺少问题时报错
- **WHEN** 用户执行 `sre-agent -p`（无问题参数）
- **THEN** 系统报错并以非零退出码退出

### Requirement: Multi-turn conversation
系统 SHALL 在 REPL 中保持完整的对话上下文，包括消息历史和工具调用记录。

#### Scenario: 多轮对话
- **WHEN** 用户在 REPL 中连续提问两个问题
- **THEN** 第二个问题的对话上下文包含第一个问题及其回答的历史

### Requirement: Model override at startup
系统 SHALL 接受 `--model`/`-m` 参数指定启动时使用的模型。

#### Scenario: 指定模型
- **WHEN** 用户执行 `sre-agent -m claude-sonnet "分析 OOM 原因"`
- **THEN** 系统使用指定模型执行查询

### Requirement: Rich terminal output
系统 SHALL 使用 Rich 库渲染终端输出，工具调用过程实时显示，最终结论格式化呈现。

#### Scenario: 工具调用进度显示
- **WHEN** 引擎执行工具调用
- **THEN** 终端实时显示工具名称、参数摘要、执行状态

#### Scenario: 最终结论渲染
- **WHEN** 引擎返回最终回答
- **THEN** 终端以 Markdown 格式渲染诊断结论
