## Context

项目已有完整的 pyproject.toml 打包配置（hatchling backend, entry point `sre-agent = "sre_agent:main"`），`pipx install .` 机制上已可用。当前问题在首次运行体验：`~/.sre-agent/` 不存在时 Config 静默使用默认值，用户不知道要手动创建配置文件。见 proposal.md 了解动机。

## Goals / Non-Goals

**Goals:**
- 首次运行自动生成 `~/.sre-agent/{config.yaml, models.yaml, memory/}`
- 模板随 wheel 打包，通过 `importlib.resources` 读取
- `ensure_config()` 放在 `__init__.py`，CLI 入口调用

**Non-Goals:**
- 不拆分 memory 重依赖为 optional extras（暂定）
- 不新增 `sre-agent init` 子命令（自动检测已覆盖该需求）
- 不提供 `--force` 重新初始化能力

## Decisions

### 1. 初始化逻辑放在 CLI 层而非 Config 内部

在 `cli.py` 的 `main()` 开头调用 `ensure_config(console)`，而非在 `Config._load_yaml_config` 中执行写入。

**理由**: Config 作为 pydantic-settings 模型应保持纯读取语义，副作用放在用户可见的 CLI 层更清晰，且可以使用 Rich 输出提示。

**备选方案**: 在 Config model_validator 中检测并写入 — 但这让数据模型承担了文件系统副作用，且无法方便地打印彩色提示。

### 2. ensure_config() 定义在 `__init__.py` 而非独立模块

函数体不超过 20 行，不值得单独建 `init.py` 模块。

**理由**: 保持包结构紧凑，减少文件数。

### 3. 模板文件使用 `importlib.resources` 而非硬编码字符串

在 `src/sre_agent/defaults/` 下放置 `.example.yaml` 文件，运行时通过 `importlib.resources.files("sre_agent.defaults")` 读取。

**理由**: 模板内容较长（含注释），硬编码为 Python 字符串可读性差且难以维护。模板文件方式允许直接编辑 YAML、有语法高亮、与实际配置格式一致。hatchling 自动包含包内所有文件，无需额外配置。

### 4. 触发条件为目录级检测

检测 `~/.sre-agent/` 目录整体是否存在，而非逐文件检查。

**理由**: 简单可预测。用户删除整个目录即可重新触发初始化。避免意外覆盖用户已编辑的单个文件。

## Risks / Trade-offs

- [模板与代码不同步] 如果 Config 新增字段但忘记更新 `config.example.yaml`，示例文件会过时 → 可以在 CI 中添加检查，但当前暂不实施
- [目录已存在但文件缺失] 如果用户手动删除了 `config.yaml` 但保留了目录，不会重新生成 → 用户需要自行恢复或删除整个目录重新初始化。这是有意的设计选择，避免覆盖用户意图
