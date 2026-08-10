## Why

当前引擎使用固定 `max_steps=30` 作为唯一的循环终止条件，与模型实际上下文窗口大小、工具输出量完全脱钩。小窗口模型可能第 3 步就溢出，大窗口模型在 30 步时远未用尽容量却被强行截断。工具输出虽有行数上限，但累积 token 无回压机制，长对话（尤其 chat 模式）不可控地膨胀直到溢出。需要基于 token 预算的动态上下文管理，使引擎在任何模型、任何工具组合下都能安全运行并在资源耗尽前优雅收敛。

## What Changes

- 引入 Token Budget Controller，每步检查上下文占用率，70% 触发压缩、90% 触发优雅收敛
- 引入三级滚动上下文：工作集（原始输出）→ 调查记录（结构化摘要）→ 证据库（磁盘落盘）
- 引入 Scratchpad 机制，模型通过 `update_scratchpad` tool_call 自主维护调查状态（findings / hypotheses / ruled_out / next_steps）
- 引入 `recall_evidence` 内置工具，允许模型按需回取已压缩的完整原始输出
- 每个 Toolset 新增 `compress()` 方法，按工具类型进行语义压缩而非固定截断
- 工具结果进入上下文时立即判断是否需要压缩（单次 > 4-8K tokens 立即压缩并落盘）
- 优雅收敛时基于 scratchpad 生成最终结论，而非简单返回"未完成"
- `max_steps` 保留为防死循环兜底，默认值提高到 50-100
- ask 和 chat 共用同一套上下文管理策略

## Capabilities

### New Capabilities
- `context-management`: Token 预算控制、三级滚动上下文、压缩调度和优雅收敛的完整上下文管理子系统
- `scratchpad`: 模型自维护的结构化调查状态追踪，通过 tool_call 更新
- `evidence-store`: 工具完整输出的本地落盘与按需回取

### Modified Capabilities
- `agentic-engine`: 循环终止条件从固定步数改为 token 预算驱动；新增压缩和收敛流程；集成内置工具路由
- `tool-system`: Toolset 基类新增 `compress()` 方法契约

## Impact

- `core/engine.py`: 主循环逻辑重构，集成水位检查、压缩触发、内置工具分发、优雅收敛
- `core/context_manager.py`: 新增，TokenBudgetController + 压缩调度
- `core/scratchpad.py`: 新增，Scratchpad 数据结构与序列化
- `core/evidence_store.py`: 新增，落盘/回取逻辑
- `core/tool.py`: Toolset 基类扩展 compress() 抽象方法
- `core/tool_executor.py`: 内置工具（update_scratchpad, recall_evidence）路由
- `toolsets/bash.py`, `toolsets/logs.py`, `toolsets/prometheus.py`: 各自实现 compress()
- `prompts/system.j2`: 加入 scratchpad 使用说明和内置工具描述
- `config.py`: max_steps 默认值调整，新增压缩相关配置项
- 新增目录 `temp/tool-results/` 用于证据库存储
