## Purpose

智能体循环引擎，驱动 LLM 与工具之间的多轮交互，支持并发工具执行和流式事件输出。

## ADDED Requirements

### Requirement: Iterative agentic loop
系统 SHALL 实现迭代式智能体循环：每轮调用 LLM，若 LLM 返回 tool_calls 则执行工具并将结果追加到消息历史，直到 LLM 给出最终回答或达到 max_steps 上限。

#### Scenario: LLM 直接回答
- **WHEN** LLM 第一轮响应不包含 tool_calls
- **THEN** 引擎立即返回 LLM 的文本回答，循环结束

#### Scenario: 多轮工具调用
- **WHEN** LLM 连续 3 轮返回 tool_calls
- **THEN** 引擎依次执行工具、追加结果、重新调用 LLM，直到第 4 轮 LLM 给出最终回答

#### Scenario: 达到 max_steps 上限
- **WHEN** 迭代次数达到配置的 max_steps
- **THEN** 引擎停止循环，返回当前已有的对话内容和一条提示"已达最大步数"

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
当工具输出超过配置的最大长度时，系统 SHALL 截断输出并在末尾附加提示告知 LLM 内容已被截断。

#### Scenario: 工具输出超长
- **WHEN** 某工具返回 10000 行文本，配置的最大输出长度为 2000 行
- **THEN** 系统截断到 2000 行并附加 "[输出已截断，原始长度 10000 行]"
