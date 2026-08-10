## Purpose

对 agentic-engine 现有行为的修改：循环终止条件从固定步数改为 token 预算驱动，集成内置工具路由。

## MODIFIED Requirements

### Requirement: Iterative agentic loop

引擎循环终止条件 SHALL 从单纯 max_steps 计数改为 token 预算水位线驱动，max_steps 降级为防死循环兜底。

#### Scenario: token 预算驱动收敛
- **WHEN** 循环中上下文占用率达到 90%
- **THEN** 引擎触发优雅收敛，而非继续迭代直到 max_steps

#### Scenario: max_steps 兜底
- **WHEN** 模型持续请求工具但上下文占用率始终低于 90%，迭代次数达到 max_steps（默认 50-100）
- **THEN** 引擎触发优雅收敛，行为与 token 预算收敛一致

#### Scenario: 每步水位检查
- **WHEN** 每轮迭代开始
- **THEN** 引擎调用 llm.count_tokens() 和 llm.get_context_window_size() 计算占用率

### Requirement: Built-in tool routing

引擎 SHALL 识别内置工具（update_scratchpad, recall_evidence）并在内部处理，不经过 ToolExecutor 的外部工具执行路径。

#### Scenario: update_scratchpad 内部处理
- **WHEN** LLM 返回的 tool_calls 中包含 update_scratchpad
- **THEN** 引擎直接更新内部 scratchpad 对象，返回确认消息，不调用 ToolExecutor

#### Scenario: recall_evidence 内部处理
- **WHEN** LLM 返回的 tool_calls 中包含 recall_evidence
- **THEN** 引擎从 EvidenceStore 读取文件内容并返回，不调用 ToolExecutor

#### Scenario: 混合工具调用
- **WHEN** LLM 单轮返回的 tool_calls 同时包含内置工具和外部工具
- **THEN** 内置工具在引擎内处理，外部工具通过 ToolExecutor 并发执行，两者结果合并追加到消息历史

## MODIFIED Requirements

### Requirement: Context window truncation

工具输出截断 SHALL 从固定行数截断升级为基于 token 估算的语义压缩。

#### Scenario: 小输出不压缩
- **WHEN** 工具输出 <= 2K tokens
- **THEN** 原样保留，行为与之前一致

#### Scenario: 大输出语义压缩
- **WHEN** 工具输出 > 4-8K tokens
- **THEN** 调用 Toolset.compress() 进行语义压缩而非固定行数截断，完整输出落盘到证据库
