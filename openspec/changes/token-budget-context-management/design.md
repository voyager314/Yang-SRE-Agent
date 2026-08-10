## Context

当前 engine.py 实现了一个简单的 while 循环（见 `Engine.call_stream()`），以 `max_steps` 为唯一终止条件。LLM 抽象层已提供 `count_tokens()` 和 `get_context_window_size()` 但引擎从未调用它们。工具输出通过 `Tool._truncate_if_needed()` 做固定行数截断，但累积 token 无任何回压。

关键约束：
- LiteLLM 的 `token_counter` 对部分模型可能退化为字符近似（见 llm.py:121-129）
- ToolExecutor.execute_parallel 返回 `list[dict]`（role=tool 消息），引擎直接 append 到 messages
- Toolset 是具体类而非 ABC，YAMLTool 通过 subprocess 执行，结果格式为纯文本
- 已有 `StructuredToolResult` 类型但 ToolExecutor 在返回给引擎前已将其格式化为字符串（`_format_result_for_llm`）

See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**
- 引擎循环由 token 水位驱动，在任何模型窗口下自适应
- 工具输出按语义压缩，压缩策略由 Toolset 各自定义
- 模型可自主维护调查状态，资源耗尽时据此优雅收敛
- 完整输出落盘可回取，压缩不等于信息丢失

**Non-Goals:**
- 不引入摘要 LLM 调用（v0.1 不承担额外模型开销）
- 不做分布式证据存储（本地文件即可）
- 不改变 CLI 接口或用户可见行为（除收敛时的提示文案）
- 不修改 LLM 抽象层本身（count_tokens 精度问题另行解决）

## Decisions

### D1: Context Manager 作为独立模块而非嵌入 Engine

**选择**: 新建 `core/context_manager.py`，Engine 持有其实例并在每步委托。

**理由**: Engine 已有 150 行，继续膨胀会让循环逻辑难以测试。ContextManager 可独立单测（给定 messages 列表 → 返回压缩后的列表 + 状态）。

**替代方案**: 直接在 Engine.call_stream 中内联水位检查和压缩。更简单但测试需要 mock 整个 LLM+Executor 栈。

### D2: 压缩在 ToolExecutor 返回后、append 到 messages 前执行

**选择**: 在 Engine 的步骤 5（工具结果处理）中，对每条结果立即调用压缩判断。

**理由**: 
- 越早压缩，后续 count_tokens 越准确
- 避免"先 append 再回头改 messages"的复杂性
- ToolExecutor 不需要知道压缩逻辑（保持单一职责）

**替代方案**: 在 ToolExecutor.execute_parallel 内部压缩。侵入性更强且 ToolExecutor 需要持有 EvidenceStore 引用。

### D3: Toolset.compress() 作为实例方法而非独立压缩器注册表

**选择**: 在 Toolset 类上新增 `compress(tool_name: str, raw_output: str) -> str` 方法。

**理由**:
- 压缩策略与工具类型强绑定（prometheus 输出的压缩规则和 bash 完全不同）
- 遵循 compression_policy.md 中"按工具类型推荐压缩单元"的设计
- 新 Toolset 只需覆盖一个方法即可获得自定义压缩

**需要解决**: ToolExecutor 当前不记录"哪个工具属于哪个 Toolset"。需要在注册时建立 tool_name → toolset 的反向映射，或让 Engine/ContextManager 直接持有 ToolsetManager 引用。

**选择**: ContextManager 持有 tool_name → Toolset 的映射（注册时由 Engine 构建传入）。

### D4: 内置工具通过 Engine 内部路由而非注册到 ToolExecutor

**选择**: Engine 在分发 tool_calls 时先检查是否为内置工具名，是则内部处理，否则走 ToolExecutor。

**理由**:
- update_scratchpad 和 recall_evidence 不是"诊断工具"，不应出现在 Toolset 概念中
- 它们的执行不需要线程池、超时或截断
- 避免污染 ToolExecutor 的通用执行路径

**替代方案**: 创建一个 InternalToolset 注册到 ToolExecutor。概念不匹配且增加不必要的间接层。

### D5: Scratchpad 更新为完整覆盖而非增量 patch

**选择**: 模型每次调用 update_scratchpad 时传入全部四个字段的完整值，引擎直接替换。

**理由**:
- 模型负责维护完整状态，避免引擎实现复杂的合并逻辑
- 模型可以自由删除/重排条目（如将 hypothesis 移到 ruled_out）
- 简化实现：Scratchpad 对象只需要一个 `update(**fields)` 方法

**替代方案**: 增量操作（add_finding, remove_hypothesis 等）。需要更多内置工具，模型调用更复杂，且不同模型对增量语义的理解可能不一致。

### D6: Token 估算使用 LLM.count_tokens() 并容忍不精确

**选择**: 直接调用现有的 `llm.count_tokens(messages, tools)`，接受其退化行为（字符/4）。

**理由**:
- 水位线本身是模糊阈值（70%/90%），±10% 的精度偏差不影响决策正确性
- 避免引入额外的分词器依赖
- 最坏情况（字符/4 高估 token 数）只会提前触发压缩，属于安全方向的偏差

### D7: 证据文件按 tool_call_id 命名，纯文本存储

**选择**: `temp/tool-results/{tool_call_id}` 纯文本文件，无元数据包装。

**理由**:
- tool_call_id 由模型 API 生成，全局唯一
- recall_evidence 只需读文件返回内容，无需索引或数据库
- 进程级生命周期，不需要持久化保证

## Risks / Trade-offs

**[count_tokens 不精确] → 水位线判断可能偏移 10-20%**
- 缓解：阈值选择留有余量（70% 而非 85%），误差方向偏保守
- 后续：可按模型 provider 接入精确分词器

**[compress() 实现质量参差] → 某些 Toolset 压缩后可能丢失关键信息**
- 缓解：完整输出始终落盘，模型可通过 recall_evidence 回取
- 缓解：基类提供保守默认实现，新 Toolset 不实现 compress() 时不会丢数据

**[模型不调用 update_scratchpad] → 优雅收敛时 scratchpad 为空**
- 缓解：system prompt 明确指导模型在发现关键信息时更新 scratchpad
- 缓解：收敛时即使 scratchpad 为空，仍然让模型基于最近消息生成结论（降级但不失败）

**[大量压缩后上下文语义断裂] → 模型可能"忘记"早期发现**
- 缓解：scratchpad 始终保留关键 findings，不受压缩影响
- 缓解：压缩摘要保留 observations 和 uncertainty 字段

**[recall_evidence 回取大文件后再次触发压缩] → 循环压缩风险**
- 缓解：recall_evidence 结果同样受即时压缩规则约束，specs 中已明确此行为
- 这是正确的行为：模型应先记下需要的信息到 scratchpad，再让大输出被压缩

## Open Questions

- max_steps 兜底值具体定为 50 还是 100？倾向 50（30 步已经覆盖绝大多数场景，提高到 50 给了 token 预算充分发挥空间，100 过于宽松可能掩盖循环不收敛的 bug）。可通过实际使用数据调整。
- 即时压缩阈值的精确值：specs 中写 "4-8K tokens"，具体选择需要在测试中确定。初始选择 4K 作为偏保守起点。
