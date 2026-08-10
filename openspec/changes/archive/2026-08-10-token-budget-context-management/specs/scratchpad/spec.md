## Purpose

模型自维护的结构化调查状态追踪。模型通过 tool_call 主动更新调查进度，引擎将其注入上下文供后续推理和优雅收敛使用。

## ADDED Requirements

### Requirement: Scratchpad data structure

Scratchpad SHALL 包含四个字段：findings（已确认发现）、hypotheses（当前假设）、ruled_out（已排除方向）、next_steps（建议下一步）。

#### Scenario: 初始状态
- **WHEN** 调查开始时
- **THEN** scratchpad 所有字段为空列表

#### Scenario: 序列化为 YAML
- **WHEN** scratchpad 需要注入到 system prompt 中
- **THEN** 以 YAML 格式序列化，包含所有四个字段及其当前值

### Requirement: update_scratchpad tool

系统 SHALL 提供 `update_scratchpad` 内置工具，模型通过 tool_call 更新调查状态。

#### Scenario: 模型记录新发现
- **WHEN** 模型调用 update_scratchpad，findings 中新增一条 "node-3 CPU 95%"
- **THEN** 引擎更新内部 scratchpad 对象，返回确认消息，不计入普通工具执行

#### Scenario: 模型排除假设
- **WHEN** 模型调用 update_scratchpad，将某条从 hypotheses 移到 ruled_out
- **THEN** scratchpad 状态相应更新

#### Scenario: 覆盖语义
- **WHEN** 模型调用 update_scratchpad
- **THEN** 传入的字段值完整覆盖 scratchpad 对应字段（非追加），模型负责维护完整状态

### Requirement: Scratchpad injection

每轮 LLM 调用前 SHALL 将当前 scratchpad 内容注入到 system prompt 的指定区域。

#### Scenario: scratchpad 非空时注入
- **WHEN** scratchpad 至少有一个非空字段
- **THEN** 在 system prompt 末尾追加当前调查状态的 YAML 表示

#### Scenario: scratchpad 为空时不注入
- **WHEN** scratchpad 所有字段均为空
- **THEN** 不向 system prompt 追加调查状态区域

### Requirement: Scratchpad as convergence basis

优雅收敛时 SHALL 将 scratchpad 内容作为模型生成最终结论的基础。

#### Scenario: 收敛时提供 scratchpad
- **WHEN** 优雅收敛触发
- **THEN** 收敛指令中包含完整 scratchpad 内容，要求模型据此生成结论、置信度和建议
