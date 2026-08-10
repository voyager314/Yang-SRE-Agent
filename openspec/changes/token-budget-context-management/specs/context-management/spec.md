## Purpose

Token 预算控制与三级滚动上下文管理，使引擎在任意模型窗口大小下动态调整上下文占用，并在资源耗尽前触发压缩或优雅收敛。

## ADDED Requirements

### Requirement: Token budget waterline check

引擎每步循环开始时 SHALL 计算当前上下文占用率（used_tokens / context_window_size），并根据水位线决定行为。

#### Scenario: 正常水位
- **WHEN** 上下文占用率 < 70%
- **THEN** 引擎正常继续，不触发任何压缩或收敛动作

#### Scenario: 压缩水位
- **WHEN** 上下文占用率 >= 70% 且 < 90%
- **THEN** 引擎触发批量压缩，将较早的工具结果从 Tier 1 降级为 Tier 2（结构化摘要）

#### Scenario: 收敛水位
- **WHEN** 上下文占用率 >= 90%
- **THEN** 引擎触发优雅收敛流程，禁用工具调用，要求模型基于已有 scratchpad 给出最终结论

### Requirement: Immediate compression on ingestion

工具结果进入上下文时 SHALL 立即评估其 token 量，超过阈值时就地压缩。

#### Scenario: 小输出原样保留
- **WHEN** 单次工具输出 <= 2K tokens
- **THEN** 原样追加到消息历史，不触发压缩

#### Scenario: 大输出立即压缩
- **WHEN** 单次工具输出 > 4-8K tokens
- **THEN** 调用对应 Toolset 的 compress() 方法生成结构化摘要，将完整输出落盘到证据库，消息历史中只保留摘要 + 证据引用路径

### Requirement: Batch compression of older results

当水位线达到 70% 时 SHALL 对较早的工具结果执行批量压缩。

#### Scenario: 保留最近工作集
- **WHEN** 批量压缩触发
- **THEN** 最近 3-5 个与当前决策直接相关的工具调用保持原样（Tier 1）

#### Scenario: 较早结果降级
- **WHEN** 批量压缩触发
- **THEN** 超出工作集范围的工具结果被替换为结构化摘要（Tier 2），原始输出落盘到证据库（Tier 3）

### Requirement: Graceful convergence

当上下文占用率 >= 90% 或 max_steps 兜底触发时 SHALL 执行优雅收敛。

#### Scenario: 基于 scratchpad 收敛
- **WHEN** 优雅收敛触发且 scratchpad 中有已记录的 findings
- **THEN** 注入收敛指令，包含 scratchpad 内容，要求模型给出结论、置信度和后续建议，tool_choice 设为 none

#### Scenario: 收敛结果标记
- **WHEN** 优雅收敛完成
- **THEN** ANSWER_END 事件中 converged=true，告知调用方这是被动收敛而非自然结束

### Requirement: Unified strategy for ask and chat

ask 和 chat 子命令 SHALL 使用同一套上下文管理策略，不因对话模式不同而采用不同的压缩或收敛规则。

#### Scenario: chat 多轮触发压缩
- **WHEN** chat 模式下多轮对话累积 token 超过 70% 水位
- **THEN** 执行与 ask 模式完全相同的压缩逻辑
