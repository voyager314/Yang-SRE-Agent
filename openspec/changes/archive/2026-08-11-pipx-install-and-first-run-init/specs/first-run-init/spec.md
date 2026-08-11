## Purpose

首次运行时自动检测配置目录，若不存在则创建目录结构并写入含注释的示例配置文件，实现零手动配置即可启动。

## ADDED Requirements

### Requirement: Auto-detect missing config directory
系统 SHALL 在启动时检测 `~/.sre-agent/` 目录是否存在，不存在时触发初始化流程。

#### Scenario: 目录不存在
- **WHEN** `~/.sre-agent/` 目录不存在
- **THEN** 系统创建该目录及其子目录 `memory/`

#### Scenario: 目录已存在
- **WHEN** `~/.sre-agent/` 目录已存在
- **THEN** 系统不做任何写入操作，直接进入正常启动流程

### Requirement: Generate example config files
系统 SHALL 从打包的模板文件生成 `config.yaml` 和 `models.yaml` 到 `~/.sre-agent/`。

#### Scenario: 生成 config.yaml
- **WHEN** 首次运行初始化触发
- **THEN** `~/.sre-agent/config.yaml` 被写入，内容包含所有可配置字段及其默认值和中文注释

#### Scenario: 生成 models.yaml
- **WHEN** 首次运行初始化触发
- **THEN** `~/.sre-agent/models.yaml` 被写入，内容包含模型注册表示例条目

### Requirement: Template files packaged in wheel
模板文件 SHALL 作为 Python 包数据随 wheel 分发，通过 `importlib.resources` 读取。

#### Scenario: pipx 安装后模板可用
- **WHEN** 用户通过 `pipx install sre-agent` 安装
- **THEN** `sre_agent.defaults` 包中的 `config.example.yaml` 和 `models.example.yaml` 可通过 `importlib.resources` 读取

### Requirement: User notification on init
系统 SHALL 在初始化完成后向终端输出提示，告知用户配置文件路径和下一步操作。

#### Scenario: 初始化提示
- **WHEN** 首次运行初始化完成
- **THEN** 终端显示配置目录路径，并提示用户编辑 `config.yaml` 和 `models.yaml`

### Requirement: Example config covers all toolsets
示例 `config.yaml` SHALL 包含所有内置工具集的配置段，每个工具集列出其实际支持的 config 键。

#### Scenario: 工具集配置完整性
- **WHEN** 用户打开生成的 `config.yaml`
- **THEN** 文件包含 prometheus、alertmanager、logs、tracing、bash 五个工具集的配置示例，各工具集的 url/provider/timeout 等键均有示例值
