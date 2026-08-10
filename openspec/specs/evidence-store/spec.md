## Purpose

工具完整输出的本地持久化与按需回取，作为三级滚动上下文的 Tier 3 实现。

## ADDED Requirements

### Requirement: Evidence persistence

当工具输出被压缩时 SHALL 将完整原始输出持久化到本地文件系统。

#### Scenario: 落盘路径规则
- **WHEN** call_id 为 "call_abc123" 的工具输出被压缩
- **THEN** 完整输出保存到 `temp/tool-results/call_abc123` 文件

#### Scenario: 落盘内容完整性
- **WHEN** 工具输出落盘
- **THEN** 文件内容与工具返回的原始完整输出完全一致，不做任何处理

### Requirement: recall_evidence tool

系统 SHALL 提供 `recall_evidence` 内置工具，模型可通过 tool_call 按 call_id 回取已压缩的完整原始输出。

#### Scenario: 成功回取
- **WHEN** 模型调用 recall_evidence，传入有效的 call_id
- **THEN** 返回对应文件的完整内容作为工具结果

#### Scenario: 回取不存在的证据
- **WHEN** 模型调用 recall_evidence，传入不存在的 call_id
- **THEN** 返回错误消息说明该 call_id 无对应证据文件

#### Scenario: 回取结果的上下文影响
- **WHEN** recall_evidence 返回大量内容
- **THEN** 该结果同样受即时压缩规则约束（如超过阈值会再次被压缩）

### Requirement: Evidence reference in compressed output

压缩后的工具摘要中 SHALL 包含证据引用信息，使模型知道可以回取。

#### Scenario: 摘要包含引用
- **WHEN** 工具输出被压缩并落盘
- **THEN** 压缩后的摘要末尾包含 `[完整输出: {call_id}]` 标记

### Requirement: Evidence cleanup

证据库 SHALL 限定在当前进程生命周期内，进程退出时不主动清理但不保证跨会话可用。

#### Scenario: 同一会话内回取
- **WHEN** 在同一次 sre-agent 运行中回取证据
- **THEN** 始终可以成功读取

#### Scenario: 跨会话不保证
- **WHEN** 新的 sre-agent 进程尝试回取上次运行的证据
- **THEN** 行为未定义，文件可能存在也可能已被清理
