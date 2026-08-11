## Context

项目已有 4 个工具集（Kubernetes/YAML、Prometheus/Python、Logs/Python、Bash/Python），统一通过 Tool → Toolset → ToolsetManager 生命周期管理。Python 工具集使用 httpx 同步客户端访问 HTTP API，YAML 工具集通过 Jinja2 模板渲染 shell 命令。所有工具返回 StructuredToolResult，Toolset 提供 compress() 钩子。

See proposal.md — Why。

## Goals / Non-Goals

**Goals:**
- 新增 Tracing、Alertmanager、Network Diagnostics 三个工具集，覆盖 Tier 1 可观测性栈
- Tracing 支持 Tempo/Jaeger 双后端，通过 Protocol 抽象屏蔽 API 差异
- Network 工具集增加参数安全校验，防止 YAML 工具的 shell 注入
- 提取共享 time util 消除代码重复

**Non-Goals:**
- 不做写操作（silence 告警、重启 pod、scale deployment）
- 不支持 Zipkin 后端（可后续扩展）
- 不做 Grafana 工具集（留给 Tier 1 Phase 4）
- 不重构现有工具集的 compress() 实现

## Decisions

### D1: Tracing 后端抽象用 Protocol 而非 ABC

**选择**: `TracingBackend(Protocol)` 定义三个方法签名，TempoBackend/JaegerBackend 各自实现。

**替代方案**: ABC 基类 + 继承。

**理由**: 项目中 duck-typing 风格一致（Toolset 本身不强制继承）。Protocol 允许后端类独立存在，无耦合导入，便于测试中 mock。

### D2: trace_search 参数式优先，内部翻译为 TraceQL

**选择**: 对 Tempo 后端，将 service/operation/duration 参数在 Python 层翻译为 TraceQL 字符串再请求 `/api/search?q=...`。保留 `raw_query` 参数作为逃生口。

**替代方案**: 直接暴露 TraceQL 语法让模型书写。

**理由**: 模型不一定熟悉 TraceQL 语法，参数式接口降低幻觉率。Jaeger 没有 TraceQL，参数式使两个后端的模型调用体验一致。

### D3: Span 属性用黑名单而非白名单

**选择**: 定义 `_ATTR_BLACKLIST_PREFIXES` 和 `_ATTR_BLACKLIST_KEYS`，去除 instrumentation 噪音，保留一切业务属性。

**替代方案**: 白名单只展示 http.*/db.*/rpc.* 等已知有价值属性。

**理由**: 用户自定义 tag（tenant_id、region、feature_flag 等）无法提前枚举，黑名单保证它们自动可见。噪音属性集合相对固定（OpenTelemetry SDK 内部属性），维护成本低。

### D4: Network 工具集用 YAML 声明 + param_validators 钩子

**选择**: 工具定义保持 YAML 声明式，在 YAMLTool 层新增 `param_validators` 字段，支持 `hostname` 类型校验（allowlist 字符集: `[a-zA-Z0-9.\-:]`）。

**替代方案 A**: 纯 Python 实现，用 subprocess.run(["dig", domain]) 避免 shell。
**替代方案 B**: YAML 工具不加校验，依赖 Jinja2 的 shell escaping。

**理由**: A 失去 YAML 声明式的简洁优势。B 不安全——Jinja2 没有内建的 shell escape，且模板注入比参数注入更难防。param_validators 是通用机制，未来其他 YAML 工具也能复用。

### D5: 共享 parse_relative_time 提取到 utils/time.py

**选择**: 从 prometheus.py 提取为 `sre_agent.utils.time.parse_relative_time`，prometheus.py 和 tracing.py 共同引用。

**替代方案**: 各自维护一份。

**理由**: 函数签名和行为完全相同（`-15m/-1h/-1d` + float fallback + now 回退），这是明确的重复而非巧合重复。

### D6: Tracing 内部数据类统一到微秒

**选择**: Span.start_us / Span.duration_us 统一为 int 微秒。Tempo nanosecond `// 1000`，Jaeger 原生微秒直接使用。

**替代方案**: 纳秒（更精确）或毫秒（更易读）。

**理由**: Jaeger 原生就是微秒，避免无意义转换。纳秒对诊断无额外价值，毫秒会丢失 Jaeger 的原始精度。格式化输出时再转为可读的 ms/s 字符串。

## Risks / Trade-offs

- **[Tempo tag cardinality]** trace_services 对 Tempo 走 tag values API，高 cardinality 环境可能慢 → 加 timeout + limit 参数，超时返回部分结果
- **[Network 工具集 Windows 兼容]** dig/traceroute 在 Windows 上不可用 → 前置条件逐工具检查，降级但不阻塞整个工具集
- **[param_validators 侵入 YAMLTool]** 给核心类新增字段 → 变更范围小（解析时多读一个字段，invoke 前多一步校验），不影响现有 YAML 工具
- **[Jaeger API 非官方稳定]** /api/traces 是 internal API → 广泛使用且变动缓慢，v3 API 可作为后续迁移路径
