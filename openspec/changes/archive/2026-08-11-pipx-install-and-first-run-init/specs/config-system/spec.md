## ADDED Requirements

### Requirement: Bundled default config templates
配置系统 SHALL 在 `sre_agent.defaults` 包中携带 `config.example.yaml` 和 `models.example.yaml` 模板文件，作为首次运行初始化的数据来源。

#### Scenario: 模板作为包数据可访问
- **WHEN** 代码调用 `importlib.resources.files("sre_agent.defaults").joinpath("config.example.yaml")`
- **THEN** 返回有效的可读资源，内容为完整的配置示例
