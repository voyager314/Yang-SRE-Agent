## Purpose

Bash 工具集，提供通用命令执行能力作为 escape hatch，让 LLM 在其他工具集不足时可执行任意 shell 命令。

## ADDED Requirements

### Requirement: Bash command execution
系统 SHALL 提供 bash 命令执行工具，运行用户环境下的 shell 命令并返回输出。

#### Scenario: 执行简单命令
- **WHEN** LLM 调用 bash_exec(command="df -h")
- **THEN** 系统在子进程中执行命令并返回 stdout 内容

#### Scenario: 命令执行超时
- **WHEN** LLM 调用 bash_exec(command="sleep 999") 且配置的超时为 30 秒
- **THEN** 系统在 30 秒后终止进程，返回 status=ERROR，error 包含超时信息

#### Scenario: 命令返回非零退出码
- **WHEN** 命令执行返回退出码非零
- **THEN** 工具返回 status=ERROR，error 包含 stderr 和退出码，data 包含 stdout（如有）

### Requirement: Bash timeout configuration
bash 工具 SHALL 支持配置默认超时时间，防止 LLM 调用长时间阻塞命令。

#### Scenario: 自定义超时
- **WHEN** config.yaml 中设置 `bash: {timeout: 60}`
- **THEN** bash 工具默认超时为 60 秒
