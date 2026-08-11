## ADDED Requirements

### Requirement: First-run init call at entry point
CLI 入口 SHALL 在构建 Config 之前调用 `ensure_config()`，确保配置目录和文件在配置加载前就位。

#### Scenario: 首次启动自动初始化
- **WHEN** 用户首次执行 `sre-agent`（`~/.sre-agent/` 不存在）
- **THEN** 系统先完成配置初始化，再进入正常的配置加载和 REPL 启动流程
