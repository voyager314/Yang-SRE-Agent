## Why

构建一个精简的 SRE 智能体 CLI 工具，能够通过 LLM 驱动的 agentic loop 自主调用 kubectl、PromQL、日志查询等运维工具链来诊断基础设施问题。以 HolmesGPT 为设计参考但完全独立实现，目标是更轻量、更易扩展，后续可接入钉钉/飞书等国内协作平台。

## What Changes

- 新建完整的 `sre_agent` 包结构，包含 core engine、tool system、CLI 入口
- 实现基于 litellm 的多模型 LLM 抽象层，支持 OpenAI/Anthropic/Azure/Bedrock 等
- 实现 agentic loop 引擎：按轮迭代、并发工具执行、流式事件输出
- 实现 Tool/Toolset 类型系统：模板方法模式、YAML 工具定义 + Jinja2 参数推断
- 实现 ToolsetManager：分层先决条件检查、懒加载初始化
- 实现 4 个初始工具集：Kubernetes、Prometheus、Logs (Loki/ES)、Bash
- 实现 Typer CLI：单次问答 (`ask`) + 多轮交互 (REPL) 模式
- 实现上下文窗口管理：超大输出截断 + 告知 LLM 已截断
- 实现 Jinja2 提示词模板系统

## Capabilities

### New Capabilities

- `llm-layer`: LLM 抽象层 — litellm 封装、多模型注册、token 计数、模型选择优先级
- `agentic-engine`: 智能体循环引擎 — call/call_stream、并发工具执行、流事件、上下文压缩
- `tool-system`: 工具类型系统 — Tool/Toolset 基类、StructuredToolResult、模板方法、YAML 工具定义、Jinja2 参数推断、Transformer 截断
- `toolset-kubernetes`: Kubernetes 工具集 — kubectl 命令封装、Pod/Service/Event 查询
- `toolset-prometheus`: Prometheus 工具集 — PromQL 查询、指标获取
- `toolset-logs`: 日志工具集 — Loki 和 Elasticsearch 日志查询
- `toolset-bash`: Bash 工具集 — 通用命令执行 escape hatch
- `cli-interface`: CLI 交互层 — Typer 命令定义、单次 ask、多轮 REPL、Rich 输出渲染
- `config-system`: 配置系统 — YAML 配置加载、环境变量覆盖、模型列表管理、工具集配置

### Modified Capabilities

(无，全新项目)

## Impact

- 替换现有的 hello-world `sre_agent/__init__.py`，重建整个包结构
- 新增依赖：litellm, typer, rich, pydantic-settings, jinja2, httpx, pyyaml
- 新增配置目录约定：`~/.sre-agent/config.yaml` 和 `~/.sre-agent/models.yaml`
- CLI 入口点 `sre-agent` 保持不变（pyproject.toml 已定义）
