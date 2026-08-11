## Purpose

Alertmanager 告警状态查询能力，提供活跃告警列表和静默规则查询，帮助模型快速了解当前告警态势。

## ADDED Requirements

### Requirement: List active alerts
系统 SHALL 提供 `alertmanager_list` 工具，查询 Alertmanager 当前活跃告警，支持按 matcher 过滤。

#### Scenario: 查询所有活跃告警
- **WHEN** 调用 alertmanager_list 无额外参数
- **THEN** 返回所有 active 状态的告警，按 severity 分组（critical → warning → info），每条告警展示 alertname、namespace、pod、message 核心 label

#### Scenario: 按 matcher 过滤
- **WHEN** 调用 alertmanager_list，参数 filter='namespace="production"'
- **THEN** 仅返回匹配该 label matcher 的告警

#### Scenario: 包含已静默告警
- **WHEN** 调用 alertmanager_list，参数 silenced=true
- **THEN** 返回结果包含被 silence 规则匹配的告警（默认不包含）

#### Scenario: 包含已抑制告警
- **WHEN** 调用 alertmanager_list，参数 inhibited=true
- **THEN** 返回结果包含被 inhibition 规则抑制的告警（默认不包含）

#### Scenario: 无活跃告警
- **WHEN** Alertmanager 无匹配的活跃告警
- **THEN** 返回 status=NO_DATA

### Requirement: List silence rules
系统 SHALL 提供 `alertmanager_silences` 工具，查询当前活跃的 silence 规则。

#### Scenario: 查询活跃 silence
- **WHEN** 调用 alertmanager_silences
- **THEN** 返回所有状态为 active 的 silence 规则，展示 matchers、创建者、过期时间、备注

#### Scenario: 无活跃 silence
- **WHEN** 无活跃 silence 规则
- **THEN** 返回 status=NO_DATA

### Requirement: Read-only operation
Alertmanager 工具集 SHALL 仅支持读操作，不提供创建 silence、ack 或修改告警状态的能力。

#### Scenario: 无写操作工具
- **WHEN** 工具集被加载
- **THEN** 仅注册 alertmanager_list 和 alertmanager_silences 两个工具，不包含任何修改状态的工具

### Requirement: Alertmanager toolset compress
AlertmanagerToolset SHALL 实现 compress() 方法，对大量告警按 alertname 去重并计数。

#### Scenario: 少量告警不压缩
- **WHEN** alertmanager_list 输出不超过 50 行
- **THEN** 原样返回

#### Scenario: 大量告警压缩
- **WHEN** alertmanager_list 输出超过 50 行
- **THEN** 按 alertname 聚合，展示每个 alertname 的计数和代表性实例，折叠重复项

### Requirement: Alertmanager toolset configuration
系统 SHALL 支持通过 config.yaml 的 toolsets.alertmanager 配置项或环境变量 ALERTMANAGER_URL 配置 Alertmanager 地址。

#### Scenario: 未配置时降级
- **WHEN** 未配置 ALERTMANAGER_URL 且 config 中无 url
- **THEN** 工具集标记为不可用，不注册工具

#### Scenario: 连接失败
- **WHEN** 配置的 URL 无法连接
- **THEN** 工具返回 ERROR，包含连接失败的具体地址
