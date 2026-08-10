## Purpose

工具类型系统，定义 Tool/Toolset 基类、统一结果类型、YAML 工具定义和 Jinja2 参数推断机制。

## ADDED Requirements

### Requirement: StructuredToolResult
所有工具执行 SHALL 返回统一的 StructuredToolResult 类型，包含 status（SUCCESS/ERROR/NO_DATA）、data、error、params、elapsed_seconds 字段。

#### Scenario: 工具执行成功
- **WHEN** 工具正常执行完毕
- **THEN** 返回 status=SUCCESS，data 包含工具输出

#### Scenario: 工具执行出错
- **WHEN** 工具执行抛出异常
- **THEN** 返回 status=ERROR，error 包含错误详情，params 包含调用参数

#### Scenario: 工具无数据
- **WHEN** 工具查询执行成功但结果为空
- **THEN** 返回 status=NO_DATA，LLM 据此可换策略继续调查

### Requirement: Tool template method
Tool 基类 SHALL 实现模板方法模式：invoke() 为固定流程（参数强制转换 → _invoke() → 截断后处理），子类只需实现 _invoke()。

#### Scenario: 自定义工具只实现 _invoke
- **WHEN** 开发者创建新工具只实现 _invoke() 方法
- **THEN** invoke() 自动处理参数类型转换和输出截断

### Requirement: YAML tool definition
系统 SHALL 支持通过 YAML 文件定义工具，使用 Jinja2 模板描述命令，参数从模板变量自动推断。

#### Scenario: 从 YAML 定义工具
- **WHEN** YAML 定义 `command: "kubectl get {{ kind }} -n {{ namespace }}"`
- **THEN** 系统自动推断参数为 kind 和 namespace，无需手动声明 parameters

#### Scenario: Jinja2 默认值
- **WHEN** YAML 定义 `command: "kubectl logs {{ pod }} --tail={{ lines | default(100) }}"`
- **THEN** lines 参数为可选，默认值为 100

### Requirement: Toolset container
Toolset SHALL 作为一组相关工具的容器，持有工具列表、先决条件列表和 LLM 指令说明，并提供 `compress(tool_name, raw_output) -> str` 方法用于将工具原始输出压缩为结构化摘要。

#### Scenario: 工具集提供 LLM 指令
- **WHEN** Toolset 定义了 llm_instructions 字段
- **THEN** 该指令在工具集激活时注入到 LLM system prompt 中

#### Scenario: 基类默认压缩
- **WHEN** Toolset 子类未覆盖 compress() 方法
- **THEN** 基类提供保守的默认实现：保留前 20 行 + 尾部 5 行 + 行数统计

#### Scenario: bash 工具集压缩
- **WHEN** bash 工具输出被压缩
- **THEN** 保留退出码、stderr、stdout 中的错误/警告行，丢弃正常输出的中间部分

#### Scenario: prometheus 工具集压缩
- **WHEN** prometheus 查询结果被压缩
- **THEN** 保留查询表达式、时间范围、异常区间数值和聚合结果，丢弃逐点数据

#### Scenario: logs 工具集压缩
- **WHEN** 日志查询结果被压缩
- **THEN** 按异常簇聚合，保留首现/末现时间、出现计数和代表性条目

#### Scenario: 压缩结果格式
- **WHEN** 任何 Toolset 的 compress() 被调用
- **THEN** 返回的摘要遵循结构化格式，包含 purpose、status、observations、evidence、uncertainty 等字段

### Requirement: Toolset prerequisites
Toolset SHALL 支持先决条件检查，类型包括 env（环境变量）、command（命令执行）。不满足先决条件的工具集不加载。

#### Scenario: 环境变量先决条件
- **WHEN** 工具集配置 `prerequisites: [{env: "PROMETHEUS_URL"}]` 且该变量未设置
- **THEN** 工具集标记为不可用，不注册其工具

#### Scenario: 命令先决条件
- **WHEN** 工具集配置 `prerequisites: [{command: "kubectl version --client"}]` 且命令执行失败
- **THEN** 工具集标记为不可用
