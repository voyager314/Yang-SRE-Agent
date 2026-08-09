## 1. 项目基础设施

- [ ] 1.1 更新 pyproject.toml：添加依赖（litellm, typer, rich, pydantic-settings, jinja2, httpx, pyyaml, prompt-toolkit）
- [ ] 1.2 重建包结构：创建 src/sre_agent/ 下的目录骨架（core/, toolsets/, prompts/, utils/）
- [ ] 1.3 配置 ruff linter 和 mypy 类型检查

## 2. 配置系统（config-system）

- [ ] 2.1 实现 Config(BaseSettings)：YAML 加载 + 环境变量映射 + 字段验证
- [ ] 2.2 实现模型注册表：从 ~/.sre-agent/models.yaml 加载多模型定义
- [ ] 2.3 实现配置优先级链：CLI > env > config.yaml > models.yaml 默认

## 3. LLM 抽象层（llm-layer）

- [ ] 3.1 定义 LLM ABC：completion(), count_tokens(), get_context_window_size()
- [ ] 3.2 实现 DefaultLLM：litellm.completion() 封装，支持 tools 参数传递
- [ ] 3.3 实现模型选择逻辑：根据配置优先级解析最终使用的模型

## 4. 工具类型系统（tool-system）

- [ ] 4.1 定义 StructuredToolResult：status/data/error/params/elapsed_seconds
- [ ] 4.2 实现 Tool ABC：invoke() 模板方法 + _invoke() 抽象 + _coerce_params() + _truncate_if_needed()
- [ ] 4.3 实现 Toolset 容器：tools 列表 + prerequisites 列表 + llm_instructions
- [ ] 4.4 实现 Prerequisite 检查：EnvPrerequisite + CommandPrerequisite
- [ ] 4.5 实现 YAMLTool：Jinja2 模板渲染 + 参数自动推断 + subprocess 执行

## 5. 工具集管理器（tool-system）

- [ ] 5.1 实现 ToolsetManager：加载内置 + 用户自定义 YAML 工具集
- [ ] 5.2 实现分层先决条件检查：env 类型立即检查，command 类型懒加载
- [ ] 5.3 实现 ToolExecutor：运行时工具注册表 + 按名分发

## 6. 智能体循环引擎（agentic-engine）

- [ ] 6.1 实现 Engine.call_stream()：迭代循环 + yield StreamEvent
- [ ] 6.2 实现并发工具执行：ThreadPoolExecutor 并行调用同一轮的多个 tool_calls
- [ ] 6.3 实现 StreamEvent 类型：TOOL_START / TOOL_RESULT / AI_MESSAGE / ANSWER_END
- [ ] 6.4 实现上下文截断：工具输出超限时截断 + 附加截断提示
- [ ] 6.5 实现 Engine.call()：同步包装器，drain call_stream() 返回 EngineResult

## 7. 工具集实现

- [ ] 7.1 实现 Kubernetes 工具集（YAML）：get_resources, describe, logs, get_events
- [ ] 7.2 实现 Prometheus 工具集（Python）：instant_query, range_query + httpx 客户端
- [ ] 7.3 实现 Logs 工具集（Python）：Loki query_range + Elasticsearch _search + provider 切换
- [ ] 7.4 实现 Bash 工具集（Python）：command 执行 + timeout + 非零退出码处理

## 8. 提示词模板

- [ ] 8.1 编写 system.j2：SRE 智能体角色定义 + 可用工具集说明注入
- [ ] 8.2 编写 investigate.j2：问题调查模式的提示词（引导 LLM 按步骤排查）
- [ ] 8.3 实现 Jinja2 渲染工具：utils/jinja.py 模板加载 + 变量推断函数

## 9. CLI 交互层（cli-interface）

- [ ] 9.1 实现 Typer app 骨架：sre-agent 主命令 + ask/chat/toolset 子命令
- [ ] 9.2 实现 ask 命令：加载配置 → 创建引擎 → 消费 stream → Rich 输出
- [ ] 9.3 实现 chat 命令：prompt_toolkit REPL + 对话历史维护 + 优雅退出
- [ ] 9.4 实现 toolset list 命令：显示所有工具集名称、状态、工具数量
- [ ] 9.5 实现 Rich 渲染：工具调用实时进度 + Markdown 结论输出

## 10. 集成验证

- [ ] 10.1 端到端冒烟测试：sre-agent ask 完整流程（mock LLM 响应）
- [ ] 10.2 REPL 多轮对话测试：验证上下文保持
- [ ] 10.3 工具集先决条件失败测试：验证优雅降级
