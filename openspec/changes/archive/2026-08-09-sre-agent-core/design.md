## Context

全新 Python 项目，当前只有 uv 脚手架和 hello-world 入口。以 HolmesGPT 为设计参考（非代码依赖），目标是构建一个精简的 SRE 智能体 CLI。详见 proposal.md — Why。

技术约束：
- Python ≥ 3.13，uv 构建
- CLI-only 部署（无 server、无 operator）
- 4 个初始工具集：Kubernetes、Prometheus、Logs、Bash
- 支持多模型提供商（litellm 路由）
- 多轮 REPL + 单次 ask 两种交互模式

## Goals / Non-Goals

**Goals:**
- 可在 5 分钟内配置并运行首次诊断查询
- 引擎与工具集完全解耦，新增工具集无需修改引擎代码
- YAML 工具定义让运维人员无需写 Python 即可扩展
- 代码量控制在 3000 行以内（不含测试）

**Non-Goals:**
- 多租户 / 认证 / 权限系统
- Web API / SSE 流式 / WebSocket
- Kubernetes Operator 部署
- 人工审批中断/恢复协议（v0.2 考虑）
- MCP 工具集支持
- 消息通知输出（钉钉/飞书/Slack，v0.2）

## Decisions

### D1: litellm 作为 LLM 统一层

**选择**: 直接使用 litellm.completion() 作为唯一 LLM 调用路径

**替代方案**:
- A: 直接对接各 SDK（openai, anthropic）— 代码量大，每加一个提供商要写适配层
- B: langchain — 过重，抽象层太多，调试困难
- C: litellm — 轻量封装，100+ 提供商，社区活跃

**理由**: litellm 只做路由和格式转换，不引入额外抽象。HolmesGPT 验证了这条路径的稳定性。

### D2: 工具执行用 subprocess 而非 Python SDK

**选择**: Kubernetes 工具集通过 subprocess 调用 kubectl，Prometheus 通过 httpx 调 HTTP API

**替代方案**:
- A: kubernetes Python client — 重依赖，API 版本跟踪复杂
- B: subprocess kubectl — 轻量，复用用户 kubeconfig，输出与运维人员日常看到的一致

**理由**: SRE 场景中 kubectl 输出就是"真相"，Python client 会引入序列化差异。且 YAML 工具定义天然匹配 subprocess 模式。

### D3: Pydantic BaseSettings 管理配置

**选择**: 使用 pydantic-settings 的 BaseSettings，支持 YAML 文件 + 环境变量 + CLI 覆盖

**替代方案**:
- A: 纯 dataclass + PyYAML — 需手写环境变量映射
- B: dynaconf — 功能重，学习曲线
- C: pydantic-settings — 类型安全，环境变量自动映射，与 Pydantic 生态统一

**理由**: 配置验证、默认值、环境变量覆盖一体化，且 Pydantic 在后续加 API 时直接复用。

### D4: 按轮流式（iteration-level streaming）而非 token 级流式

**选择**: engine.call_stream() 每完成一轮 LLM 调用 yield 事件，不做 token 级流式

**替代方案**:
- A: token 级流式 — 用户体验好（逐字显示），但 tool_calls 必须等完整 JSON 才能解析
- B: 按轮流式 — 每轮完成后立即 yield，工具调用过程实时显示

**理由**: tool-use 场景中 token 流式无意义（必须等完整 tool_call JSON），按轮流式在保留进度感的同时大幅简化实现。与 HolmesGPT 同一选择。

### D5: 多轮 REPL 用 prompt_toolkit

**选择**: 使用 prompt_toolkit 提供 REPL 交互（历史、自动补全、多行输入）

**替代方案**:
- A: 裸 input() — 无历史、无补全
- B: readline — Unix only，Windows 支持差
- C: prompt_toolkit — 跨平台，功能丰富，社区标准

**理由**: Windows 11 是当前开发环境，prompt_toolkit 跨平台支持最好。

### D6: 工具集加载顺序

**选择**:
1. 内置工具集（Python 定义）
2. 内置 YAML 工具集（`sre_agent/toolsets/*.yaml`）
3. 用户自定义 YAML（`~/.sre-agent/toolsets/*.yaml`）
4. config.yaml 中的配置覆盖内置字段

**理由**: 用户自定义优先级最高，但不能跳过内置的先决条件逻辑。配置覆盖只改参数（如 URL），不替换工具定义本身。

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| litellm 版本更新频繁，API 可能变动 | 构建失败 | pin 精确版本，定期升级 |
| subprocess kubectl 性能低于 Python client | 每次调用多 50-100ms | SRE 诊断场景可接受，非高频调用 |
| YAML 工具定义的 Jinja2 注入风险 | 恶意模板执行任意命令 | YAML 来自受信目录（包内+用户 home），非用户输入 |
| 多轮 REPL 上下文无限增长 | token 超限 | 截断策略：达到上下文窗口 80% 时截断早期消息 |
| Python 3.13 限制部分用户 | 安装门槛 | uv 可自动管理 Python 版本 |
## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI Layer                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                    │
│  │ ask cmd  │  │ chat cmd │  │ toolset cmd  │   (typer + rich)    │
│  └────┬─────┘  └────┬─────┘  └──────────────┘                    │
│       │              │                                            │
│       └──────┬───────┘                                            │
│              ▼                                                    │
├──────────────────────────────────────────────────────────────────┤
│                        Config                                     │
│  YAML file + env vars + CLI args → Pydantic BaseSettings          │
│  Factory: create_engine() → LLM + ToolExecutor + Engine           │
├──────────────────────────────────────────────────────────────────┤
│                     Core Engine                                    │
│  ┌─────────────────────────────────────────────────────────┐      │
│  │  Engine.call_stream()                                    │      │
│  │  ┌─────────┐    ┌──────────────┐    ┌───────────────┐   │      │
│  │  │   LLM   │───▶│ ToolExecutor │───▶│ StreamEvents  │   │      │
│  │  │(litellm)│◀───│  (parallel)  │    │  (generator)  │   │      │
│  │  └─────────┘    └──────────────┘    └───────────────┘   │      │
│  └─────────────────────────────────────────────────────────┘      │
├──────────────────────────────────────────────────────────────────┤
│                       Toolsets                                     │
│  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐         │
│  │ Kubernetes │ │ Prometheus │ │   Logs   │ │   Bash   │         │
│  │  (YAML)   │ │  (Python)  │ │ (Python) │ │ (Python) │         │
│  └─────┬──────┘ └─────┬──────┘ └────┬─────┘ └────┬─────┘         │
│        │               │             │            │               │
│        ▼               ▼             ▼            ▼               │
│  ┌──────────┐    ┌──────────┐   ┌────────┐  ┌────────┐           │
│  │ kubectl  │    │ HTTP API │   │Loki/ES │  │ shell  │           │
│  │subprocess│    │  (httpx) │   │ (httpx)│  │  exec  │           │
│  └──────────┘    └──────────┘   └────────┘  └────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

## Key Interfaces

```python
# core/llm.py
class LLM(ABC):
    def completion(self, messages, tools, tool_choice=None) -> ModelResponse: ...
    def count_tokens(self, messages, tools) -> int: ...
    def get_context_window_size(self) -> int: ...

# core/tool.py
class StructuredToolResult(BaseModel):
    status: ToolResultStatus  # SUCCESS / ERROR / NO_DATA
    data: Any | None
    error: str | None
    params: dict | None
    elapsed_seconds: float | None

class Tool(ABC):
    name: str
    description: str
    parameters: dict  # JSON Schema

    def invoke(self, params: dict) -> StructuredToolResult:
        params = self._coerce_params(params)
        result = self._invoke(params)
        return self._truncate_if_needed(result)

    @abstractmethod
    def _invoke(self, params: dict) -> StructuredToolResult: ...

class Toolset(BaseModel):
    name: str
    tools: list[Tool]
    prerequisites: list[Prerequisite]
    llm_instructions: str | None

# core/engine.py
class Engine:
    def call(self, messages) -> EngineResult: ...
    def call_stream(self, messages) -> Generator[StreamEvent, None, None]: ...
```

## File Layout (final)

```
src/sre_agent/
├── __init__.py              # main() entry point
├── cli.py                   # Typer app: ask, chat, toolset
├── config.py                # Config(BaseSettings)
├── core/
│   ├── __init__.py
│   ├── llm.py              # LLM ABC + DefaultLLM (litellm)
│   ├── engine.py           # Engine: agentic loop + streaming
│   ├── tool.py             # Tool, Toolset, StructuredToolResult
│   ├── tool_executor.py    # ToolExecutor: dispatch + parallel run
│   ├── toolset_manager.py  # load/check/register toolsets
│   └── context.py          # truncation logic
├── toolsets/
│   ├── __init__.py
│   ├── kubernetes.yaml      # YAML 工具定义
│   ├── prometheus.py        # Python toolset
│   ├── logs.py              # Loki + ES toolset
│   └── bash.py              # Bash toolset
├── prompts/
│   ├── system.j2
│   └── investigate.j2
└── utils/
    ├── __init__.py
    ├── jinja.py             # render + param extraction
    └── streaming.py         # StreamEvent enum + types
```
