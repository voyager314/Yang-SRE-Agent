## Purpose

智能体循环引擎，驱动 LLM 与工具之间的多轮交互，支持并发工具执行和流式事件输出。

## ADDED Requirements

### Requirement: Iterative agentic loop
引擎循环终止条件 SHALL 由 token 预算水位线驱动，max_steps 降级为防死循环兜底。

#### Scenario: LLM 直接回答
- **WHEN** LLM 第一轮响应不包含 tool_calls
- **THEN** 引擎立即返回 LLM 的文本回答，循环结束

#### Scenario: 多轮工具调用
- **WHEN** LLM 连续 3 轮返回 tool_calls
- **THEN** 引擎依次执行工具、追加结果、重新调用 LLM，直到第 4 轮 LLM 给出最终回答

#### Scenario: token 预算驱动收敛
- **WHEN** 循环中上下文占用率达到 90%
- **THEN** 引擎触发优雅收敛，而非继续迭代直到 max_steps

#### Scenario: max_steps 兜底
- **WHEN** 模型持续请求工具但上下文占用率始终低于 90%，迭代次数达到 max_steps（默认 50）
- **THEN** 引擎触发优雅收敛，行为与 token 预算收敛一致

#### Scenario: 每步水位检查
- **WHEN** 每轮迭代开始
- **THEN** 引擎调用 llm.count_tokens() 和 llm.get_context_window_size() 计算占用率

### Requirement: Parallel tool execution
系统 SHALL 在单轮中并发执行 LLM 返回的多个 tool_calls。

#### Scenario: 并发执行 3 个工具
- **WHEN** LLM 单轮返回 3 个 tool_calls
- **THEN** 系统使用线程池并发执行这 3 个工具调用，总耗时接近最慢的单个工具而非三者之和

### Requirement: Stream events
引擎 SHALL 以生成器模式输出流事件，事件类型包括 TOOL_START、TOOL_RESULT、AI_MESSAGE、ANSWER_END。

#### Scenario: CLI 消费流事件
- **WHEN** CLI 调用 engine.call_stream()
- **THEN** 每个工具执行产生 TOOL_START 和 TOOL_RESULT 事件，最终回答产生 ANSWER_END 事件

### Requirement: Context window truncation
工具输出截断 SHALL 基于 token 估算触发语义压缩，而非固定行数截断。

#### Scenario: 小输出不压缩
- **WHEN** 工具输出 <= 2K tokens
- **THEN** 原样保留，追加到消息历史

#### Scenario: 大输出语义压缩
- **WHEN** 工具输出 > 4-8K tokens
- **THEN** 调用 Toolset.compress() 进行语义压缩，完整输出落盘到证据库

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
