## 1. 模板文件

- [x] 1.1 创建 `src/sre_agent/defaults/__init__.py`（空文件）
- [x] 1.2 创建 `src/sre_agent/defaults/config.example.yaml`，包含所有 Config 字段默认值和五个工具集（prometheus, alertmanager, logs, tracing, bash）的配置示例
- [x] 1.3 创建 `src/sre_agent/defaults/models.example.yaml`，包含模型注册表示例条目

## 2. 初始化逻辑

- [x] 2.1 在 `src/sre_agent/__init__.py` 中新增 `ensure_config()` 函数：检测 `DEFAULT_CONFIG_DIR` 是否存在，不存在时创建目录、`memory/` 子目录，通过 `importlib.resources` 读取模板写入 `config.yaml` 和 `models.yaml`，使用 Rich Panel 输出提示

## 3. CLI 集成

- [x] 3.1 在 `src/sre_agent/cli.py` 的 `main()` 函数开头（Config 构造之前）调用 `ensure_config(console)`
