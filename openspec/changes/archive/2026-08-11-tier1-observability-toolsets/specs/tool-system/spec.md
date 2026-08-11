## MODIFIED Requirements

### Requirement: YAML tool definition
系统 SHALL 支持通过 YAML 文件定义工具，使用 Jinja2 模板描述命令，参数从模板变量自动推断。YAML 工具 SHALL 支持可选的 `param_validators` 字段，定义参数级别的校验规则。

#### Scenario: 从 YAML 定义工具
- **WHEN** YAML 定义 `command: "kubectl get {{ kind }} -n {{ namespace }}"`
- **THEN** 系统自动推断参数为 kind 和 namespace，无需手动声明 parameters

#### Scenario: Jinja2 默认值
- **WHEN** YAML 定义 `command: "kubectl logs {{ pod }} --tail={{ lines | default(100) }}"`
- **THEN** lines 参数为可选，默认值为 100

#### Scenario: 参数校验器 — hostname allowlist
- **WHEN** YAML 工具定义 `param_validators: {host: hostname}` 且调用时 host 参数包含 shell 元字符
- **THEN** invoke() 在执行命令前返回 ERROR，说明参数包含非法字符

#### Scenario: 参数校验器 — 合法输入通过
- **WHEN** YAML 工具定义 `param_validators: {host: hostname}` 且调用时 host 参数为合法 hostname 或 IP
- **THEN** 正常渲染模板并执行命令

## ADDED Requirements

### Requirement: Shared time parsing utility
系统 SHALL 提供 `utils/time.py` 公共模块，包含 `parse_relative_time(value, now)` 函数，将相对时间字符串（如 "-15m"、"-1h"、"-1d"）或 Unix 时间戳字符串转换为 float 时间戳。

#### Scenario: 相对时间解析
- **WHEN** 调用 parse_relative_time("-15m", now=1700000000)
- **THEN** 返回 1700000000 - 900 = 1699999100.0

#### Scenario: 绝对时间戳
- **WHEN** 调用 parse_relative_time("1699999100", now=1700000000)
- **THEN** 返回 1699999100.0

#### Scenario: 无法识别的值回退
- **WHEN** 调用 parse_relative_time("invalid", now=1700000000)
- **THEN** 返回 now 值（1700000000），不抛异常

#### Scenario: Prometheus 工具集引用共享函数
- **WHEN** prometheus.py 中需要解析相对时间
- **THEN** 从 utils.time 导入 parse_relative_time，不再使用模块内私有实现
