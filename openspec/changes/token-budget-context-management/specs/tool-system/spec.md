## Purpose

对 tool-system 的修改：Toolset 基类新增 compress() 方法契约，各工具集按自身输出类型实现语义压缩。

## MODIFIED Requirements

### Requirement: Toolset container

Toolset 基类 SHALL 新增 `compress(tool_name, raw_output) -> str` 方法，用于将工具原始输出压缩为结构化摘要。

#### Scenario: 基类默认压缩
- **WHEN** Toolset 子类未覆盖 compress() 方法
- **THEN** 基类提供保守的默认实现：保留前 20 行 + 尾部 5 行 + 行数统计

#### Scenario: bash 工具集压缩
- **WHEN** bash 工具输出被压缩
- **THEN** 保留退出码、stderr、stdout 中的错误/警告行，丢弃正常输出的中间部分

#### Scenario: prometheus 工具集压缩
- **WHEN** prometheus 查询结果被压缩
- **THEN** 保留查询表达式、时间范围、异常区间数值和聚合结果，丢弃逐点数据

#### Scenario: logs 工具集压缩
- **WHEN** 日志查询结果被压缩
- **THEN** 按异常簇聚合，保留首现/末现时间、出现计数和代表性条目

#### Scenario: 压缩结果格式
- **WHEN** 任何 Toolset 的 compress() 被调用
- **THEN** 返回的摘要遵循结构化格式，包含 purpose、status、observations、evidence、uncertainty 等字段
