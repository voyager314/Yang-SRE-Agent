## ADDED Requirements

### Requirement: Pre-investigation memory recall

引擎 SHALL 在调查循环开始前执行语义检索，将相关历史调查注入上下文。

#### Scenario: 有 MemoryStore 时检索
- **WHEN** 引擎持有 MemoryStore 引用且调查开始
- **THEN** 引擎从用户消息中提取问题文本，调用 MemoryStore.recall() 获取相关历史调查

#### Scenario: 无 MemoryStore 时跳过
- **WHEN** 引擎未持有 MemoryStore 引用（memory 禁用）
- **THEN** 引擎跳过检索步骤，直接进入调查循环，行为与此功能引入前一致

#### Scenario: 检索结果注入
- **WHEN** MemoryStore.recall() 返回非空结果
- **THEN** 引擎将历史调查摘要注入 system prompt 尾部，格式化为结构化文本

#### Scenario: 检索失败不阻塞
- **WHEN** MemoryStore.recall() 抛出异常
- **THEN** 引擎记录警告日志但正常继续调查循环

### Requirement: Post-investigation memory save

引擎 SHALL 在调查循环结束后触发摘要提取和存储。

#### Scenario: 正常结束后保存
- **WHEN** 调查循环正常结束且引擎持有 MemoryStore 引用
- **THEN** 引擎调用 MemoryStore.save_investigation()，传入用户问题、最终回答、Scratchpad 状态、工具调用记录和收敛标记

#### Scenario: 保存失败不阻塞
- **WHEN** MemoryStore.save_investigation() 抛出异常
- **THEN** 引擎记录警告日志但正常返回调查结果给用户

#### Scenario: chat 模式每轮保存
- **WHEN** 在 chat 多轮模式中完成一轮调查
- **THEN** 该轮调查结果同样触发摘要提取和存储
