## Purpose

Prometheus 工具集，提供 PromQL 查询能力，让 LLM 能够查询和分析监控指标。

## ADDED Requirements

### Requirement: PromQL instant query
系统 SHALL 提供 Prometheus 即时查询工具，向配置的 Prometheus 地址发送 PromQL 查询。

#### Scenario: 查询 HTTP 错误率
- **WHEN** LLM 调用 prometheus_query(query="rate(http_requests_total{status=~'5..'}[5m])")
- **THEN** 系统向 Prometheus `/api/v1/query` 发送请求并返回查询结果

#### Scenario: Prometheus 不可达
- **WHEN** 配置的 Prometheus URL 无法连接
- **THEN** 工具返回 status=ERROR，error 包含连接失败信息

### Requirement: PromQL range query
系统 SHALL 提供 Prometheus 范围查询工具，支持指定时间范围和步长。

#### Scenario: 查询过去 1 小时的 CPU 使用率
- **WHEN** LLM 调用 prometheus_query_range(query="node_cpu_seconds_total", start="-1h", step="60s")
- **THEN** 系统向 Prometheus `/api/v1/query_range` 发送请求并返回时序数据

### Requirement: Prometheus prerequisite
Prometheus 工具集 SHALL 要求配置有效的 prometheus_url。

#### Scenario: URL 未配置
- **WHEN** config.yaml 中未设置 prometheus_url 且环境变量 PROMETHEUS_URL 不存在
- **THEN** Prometheus 工具集标记为不可用
