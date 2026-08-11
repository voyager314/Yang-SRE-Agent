## Purpose

网络连通性诊断能力，提供 DNS 解析、端口探测、HTTP 健康检查和路由追踪，帮助模型排除网络层故障。

## ADDED Requirements

### Requirement: DNS lookup
系统 SHALL 提供 `dns_lookup` 工具，解析域名的 DNS 记录。

#### Scenario: A 记录查询
- **WHEN** 调用 dns_lookup，参数 domain="api.example.com"
- **THEN** 返回该域名的 A 记录 IP 地址列表

#### Scenario: 指定记录类型
- **WHEN** 调用 dns_lookup，参数 domain="api.example.com"、type="CNAME"
- **THEN** 返回对应类型的 DNS 记录

#### Scenario: 域名不存在
- **WHEN** 查询的域名无法解析
- **THEN** 返回 ERROR 或 NO_DATA，包含 NXDOMAIN 信息

### Requirement: Port connectivity check
系统 SHALL 提供 `port_check` 工具，检测 TCP 端口连通性。

#### Scenario: 端口可达
- **WHEN** 调用 port_check，参数 host="db.internal"、port=5432，且端口可连接
- **THEN** 返回 SUCCESS，指示端口可达

#### Scenario: 端口不可达
- **WHEN** 调用 port_check，目标端口无响应或被拒绝
- **THEN** 返回 ERROR，说明连接失败原因（超时/拒绝）

### Requirement: HTTP endpoint health check
系统 SHALL 提供 `http_check` 工具，检查 HTTP 端点的健康状态和响应时间。

#### Scenario: 健康端点
- **WHEN** 调用 http_check，参数 url="http://svc.internal/healthz"，端点返回 2xx
- **THEN** 返回 SUCCESS，包含 HTTP 状态码和响应耗时

#### Scenario: 不健康端点
- **WHEN** 目标端点返回 5xx 或连接失败
- **THEN** 返回 ERROR，包含状态码或连接错误详情

### Requirement: Traceroute
系统 SHALL 提供 `traceroute` 工具，追踪到目标主机的网络路由。

#### Scenario: 正常追踪
- **WHEN** 调用 traceroute，参数 host="10.0.1.50"
- **THEN** 返回每一跳的 IP 和延迟信息

#### Scenario: 命令不可用
- **WHEN** 系统未安装 traceroute 命令
- **THEN** 工具集前置条件检查失败，该工具不可用

### Requirement: Parameter safety validation
Network 工具集 SHALL 对 host/domain 参数实施 allowlist 字符集校验，仅允许 hostname 和 IP 地址合法字符（字母、数字、点、连字符、冒号），拒绝包含 shell 元字符的输入。

#### Scenario: 正常 hostname
- **WHEN** host 参数为 "api.prod.internal" 或 "10.0.1.50"
- **THEN** 正常执行命令

#### Scenario: 注入尝试
- **WHEN** host 参数包含 ";" 或 "|" 或 "$" 或 "`" 等 shell 元字符
- **THEN** 返回 ERROR，拒绝执行，说明参数包含非法字符

### Requirement: Platform graceful degradation
Network 工具集 SHALL 对每个工具独立检查命令可用性，不可用的工具不注册，不影响其他工具的使用。

#### Scenario: 部分工具可用
- **WHEN** 系统安装了 curl 但未安装 dig
- **THEN** http_check 工具可用，dns_lookup 工具不注册，工具集整体仍可用

#### Scenario: 全部不可用
- **WHEN** 所有网络诊断命令均不可用（如 Windows 环境）
- **THEN** 工具集标记为不可用，模型可使用 bash 工具集作为后备
