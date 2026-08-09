## Purpose

日志工具集，支持 Loki 和 Elasticsearch 两种后端，让 LLM 能够查询和分析应用日志。

## ADDED Requirements

### Requirement: Loki log query
系统 SHALL 提供 Loki 日志查询工具，支持 LogQL 语法查询。

#### Scenario: 按标签查询日志
- **WHEN** LLM 调用 logs_query(query='{app="checkout-service"} |= "error"', limit=100)
- **THEN** 系统向 Loki `/loki/api/v1/query_range` 发送请求并返回日志条目

#### Scenario: Loki 不可达
- **WHEN** 配置的 Loki URL 无法连接
- **THEN** 工具返回 status=ERROR，error 包含连接失败信息

### Requirement: Elasticsearch log query
系统 SHALL 提供 Elasticsearch 日志查询工具，支持 Lucene 查询语法。

#### Scenario: 按关键词查询日志
- **WHEN** LLM 调用 logs_query(query="level:ERROR AND service:checkout", limit=100) 且 provider 为 elasticsearch
- **THEN** 系统向 Elasticsearch `/_search` 发送请求并返回日志条目

### Requirement: Log provider configuration
日志工具集 SHALL 根据配置选择后端（loki 或 elasticsearch），需要有效的 URL 配置。

#### Scenario: 未配置日志后端
- **WHEN** config.yaml 中 logs provider 和 url 均未设置
- **THEN** 日志工具集标记为不可用

#### Scenario: 配置 Loki 后端
- **WHEN** config.yaml 设置 `logs: {provider: loki, url: "http://loki:3100"}`
- **THEN** 日志工具集使用 Loki 客户端实现
