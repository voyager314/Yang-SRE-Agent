## Why

SRE-Agent 当前的工具集仅覆盖 Kubernetes、Prometheus 指标、日志（Loki/ES）和通用 Bash，缺少分布式追踪、告警状态和网络连通性诊断能力。调查时模型频繁退化到 bash 调用 curl/dig 等命令，失去结构化输出和 compress 能力。补齐 Tier 1 可观测性栈后，模型可以完成"指标异常 → 追踪定位 → 日志确认 → 网络排除"的完整闭环，而不依赖 bash 兜底。

## What Changes

- 新增 **Tracing 工具集**（Python/httpx）：支持 Grafana Tempo 和 Jaeger 双后端，提供 trace 搜索、span tree 渲染、服务发现三个工具
- 新增 **Alertmanager 工具集**（Python/httpx）：查询活跃告警和静默规则，按 severity 分组格式化
- 新增 **Network Diagnostics 工具集**（YAML 声明式）：DNS 解析、端口探测、HTTP 健康检查、traceroute，带参数安全校验
- 提取 `_parse_relative_time` 到 `utils/time.py` 公共模块，Prometheus 和 Tracing 共同引用
- `toolsets/__init__.py` 注册新工具集，Config 新增对应配置项

## Capabilities

### New Capabilities
- `toolset-tracing`: 分布式追踪查询能力，支持 Tempo/Jaeger 双后端搜索 trace、获取 span tree、发现服务列表
- `toolset-alertmanager`: Alertmanager 告警状态查询能力，支持按标签过滤活跃告警和查看静默规则
- `toolset-network`: 网络连通性诊断能力，支持 DNS/端口/HTTP/traceroute 探测

### Modified Capabilities
- `tool-system`: 新增共享时间解析模块 `utils/time.py`，YAMLTool 增加参数校验钩子支持 network 工具的安全约束

## Impact

- 新增文件：`src/sre_agent/toolsets/tracing.py`, `alertmanager.py`, `network.yaml`, `src/sre_agent/utils/time.py`
- 修改文件：`src/sre_agent/toolsets/__init__.py`（注册）, `src/sre_agent/toolsets/prometheus.py`（改用共享 time util）, `src/sre_agent/core/toolset_manager.py`（param validator hook）, `src/sre_agent/config.py`（新增配置项）
- 新增依赖：无（httpx 已存在，YAML 工具用标准 subprocess）
- 环境变量：`TEMPO_URL` / `JAEGER_URL` / `TRACING_URL`, `ALERTMANAGER_URL`
