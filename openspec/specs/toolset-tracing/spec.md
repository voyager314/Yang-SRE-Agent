## Purpose

分布式追踪查询能力，支持 Tempo 和 Jaeger 双后端，提供 trace 搜索、span tree 获取和服务发现功能。

## ADDED Requirements

### Requirement: Trace search by parameters
系统 SHALL 提供 `trace_search` 工具，支持按 service、operation、min_duration、max_duration、tags、start、limit 参数搜索 trace 摘要列表。

#### Scenario: 按服务和延迟搜索
- **WHEN** 调用 trace_search，参数 service="checkout-svc"、min_duration="500ms"
- **THEN** 返回匹配 trace 的摘要列表，包含 trace_id、root_service、root_operation、duration_ms、span_count、error_count

#### Scenario: Jaeger 后端必须指定 service
- **WHEN** provider 为 jaeger 且未提供 service 参数
- **THEN** 返回 ERROR，提示 service 参数对 Jaeger 后端为必填

#### Scenario: 无匹配结果
- **WHEN** 搜索条件无匹配 trace
- **THEN** 返回 status=NO_DATA

### Requirement: TraceQL raw query escape hatch
系统 SHALL 支持 `trace_search` 的 `raw_query` 参数，允许直接传入 TraceQL 表达式。该参数仅在 Tempo 后端生效。

#### Scenario: Tempo 使用 raw_query
- **WHEN** provider 为 tempo 且 raw_query 非空
- **THEN** 直接将 raw_query 作为 TraceQL 传递给 Tempo search API，忽略其他筛选参数（start/limit 仍生效）

#### Scenario: Jaeger 拒绝 raw_query
- **WHEN** provider 为 jaeger 且 raw_query 非空
- **THEN** 返回 ERROR，说明 raw_query 仅 Tempo 支持

### Requirement: Trace span tree retrieval
系统 SHALL 提供 `trace_get` 工具，根据 trace_id 获取完整 span 树并格式化为缩进文本。

#### Scenario: 正常获取 span tree
- **WHEN** 调用 trace_get，参数 trace_id 有效
- **THEN** 返回树形格式化文本，显示每个 span 的 service、operation、duration，使用 ├─/└─ 缩进表示调用层级

#### Scenario: 标注慢 span
- **WHEN** span 的 duration 超过父 span duration 的 50% 且绝对值超过 100ms
- **THEN** 该 span 行末标注 ⚠️ SLOW

#### Scenario: 标注错误 span
- **WHEN** span 的 status_code 为 2 (Error)
- **THEN** 该 span 行末标注 ❌ ERROR

#### Scenario: 属性黑名单过滤
- **WHEN** span 包含 otel.library.*、telemetry.sdk.*、thread.id 等 instrumentation 属性
- **THEN** 这些属性不出现在格式化输出中，业务属性正常展示

#### Scenario: 属性折叠
- **WHEN** 过滤后的属性超过 4 个
- **THEN** 展示前 4 个，其余以 "+N more" 标注折叠

#### Scenario: trace_id 无效
- **WHEN** 调用 trace_get 的 trace_id 不存在
- **THEN** 返回 ERROR

### Requirement: Service discovery
系统 SHALL 提供 `trace_services` 工具，列出可查询的服务名列表。

#### Scenario: Jaeger 服务发现
- **WHEN** provider 为 jaeger
- **THEN** 通过 /api/services 接口返回服务名列表

#### Scenario: Tempo 服务发现
- **WHEN** provider 为 tempo
- **THEN** 通过 /api/v2/search/tag/service.name/values 返回服务名列表

### Requirement: Dual backend support
系统 SHALL 通过 TracingBackend Protocol 抽象支持 Tempo 和 Jaeger 两种后端，使用统一的内部数据类（Span, TraceSummary）。

#### Scenario: Provider 自动检测
- **WHEN** 配置 URL 包含 "tempo" 或 "jaeger"/":16686" 关键字
- **THEN** 自动选择对应后端，无需显式配置 provider

#### Scenario: Provider 探测回退
- **WHEN** URL 无法从关键字判断后端类型
- **THEN** 尝试请求 Tempo 的 /api/search/tags，成功则选择 tempo，否则回退 jaeger

### Requirement: Tracing toolset compress
TracingToolset SHALL 实现 compress() 方法，对 trace_get 输出保留 root span、error/slow 标注的路径，折叠正常子树。

#### Scenario: 小 trace 不压缩
- **WHEN** trace_get 输出不超过 60 行
- **THEN** 原样返回，不做压缩

#### Scenario: 大 trace 压缩
- **WHEN** trace_get 输出超过 60 行
- **THEN** 保留包含 ❌/⚠️ 标记的行、trace 头部摘要行和 slow spans 汇总段，折叠正常子树

### Requirement: Tracing toolset configuration
系统 SHALL 支持通过 config.yaml 的 toolsets.tracing 配置项或环境变量 TEMPO_URL/JAEGER_URL/TRACING_URL 配置追踪后端。

#### Scenario: 环境变量优先级
- **WHEN** 同时设置了 TEMPO_URL 和 JAEGER_URL
- **THEN** TEMPO_URL 优先

#### Scenario: 未配置时优雅降级
- **WHEN** 未配置任何追踪 URL
- **THEN** 工具集标记为不可用，不注册工具
