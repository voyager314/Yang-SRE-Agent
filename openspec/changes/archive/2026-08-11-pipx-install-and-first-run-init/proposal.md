## Why

项目已具备 `pipx install` 所需的打包结构（entry point、hatchling build backend），但首次运行时 `~/.sre-agent/` 不存在，用户必须手动创建配置文件才能使用。需要一个零配置的首次运行体验：安装后直接 `sre-agent` 即可启动，缺失的配置目录和示例文件自动生成。

## What Changes

- 新增 `src/sre_agent/defaults/` 包，内含 `config.example.yaml` 和 `models.example.yaml` 两个模板文件，随 wheel 一起打包分发
- 在 `src/sre_agent/__init__.py` 中新增 `ensure_config()` 函数，检测 `~/.sre-agent/` 是否存在，不存在时通过 `importlib.resources` 读取模板并写入目标路径，同时创建 `memory/` 子目录
- 在 `src/sre_agent/cli.py` 的 `main()` 入口开头调用 `ensure_config(console)`，初始化完成后用 Rich Panel 提示用户配置文件位置

## Capabilities

### New Capabilities
- `first-run-init`: 首次运行自动检测并生成配置目录和示例文件的能力

### Modified Capabilities
- `config-system`: 新增打包的默认配置模板文件作为配置来源
- `cli-interface`: 在 CLI 入口增加首次运行初始化调用

## Impact

- 新增文件: `src/sre_agent/defaults/__init__.py`, `src/sre_agent/defaults/config.example.yaml`, `src/sre_agent/defaults/models.example.yaml`
- 修改文件: `src/sre_agent/__init__.py`, `src/sre_agent/cli.py`
- 新增依赖: 无（`importlib.resources` 为标准库）
- `pyproject.toml` 无需修改，hatchling 自动包含 `src/sre_agent/` 下所有文件
