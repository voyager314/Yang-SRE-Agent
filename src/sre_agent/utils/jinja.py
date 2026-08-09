"""Jinja 提示词渲染及 YAML 工具模板变量分析辅助函数。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

# DebugUndefined 会把缺失占位符保留在输出中，便于发现配置问题而非静默置空。
_env = Environment(loader=BaseLoader(), undefined=__import__("jinja2").DebugUndefined)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def render_template(template_str: str, variables: dict[str, Any]) -> str:
    """使用给定变量渲染一段内存中的 Jinja 模板。"""

    template = _env.from_string(template_str)
    return template.render(**variables)


def load_prompt(name: str, variables: dict[str, Any] | None = None) -> str:
    """按名称读取打包的 ``prompts/<name>.j2`` 并按需渲染。"""

    path = _PROMPTS_DIR / f"{name}.j2"
    template_str = path.read_text(encoding="utf-8")
    if variables:
        return render_template(template_str, variables)
    return template_str


def extract_variables(template_str: str) -> list[tuple[str, bool]]:
    """提取模板使用的变量，并标记是否通过 ``default`` 提供默认值。

    返回结果按变量名排序，使自动生成的 JSON Schema 和测试结果保持稳定。
    当前实现面向工具命令中的简单表达式，不承担完整 Jinja AST 分析。
    """

    var_pattern = re.compile(r"\{\{[^}]*?\b(\w+)\b[^}]*?\}\}")
    default_pattern = re.compile(r"\{\{[^}]*?(\w+)\s*\|\s*default\(")

    all_vars: set[str] = set()
    for match in var_pattern.finditer(template_str):
        inner = match.group(0)[2:-2]
        identifiers = re.findall(r"\b([a-zA-Z_]\w*)\b", inner)
        # 过滤 Jinja 关键字和过滤器名，只保留实际需要调用方提供的标识符。
        keywords = {"default", "true", "false", "none", "is", "not", "and", "or", "in"}
        for ident in identifiers:
            if ident not in keywords:
                all_vars.add(ident)

    defaults = set(default_pattern.findall(template_str))

    results: list[tuple[str, bool]] = []
    for var in sorted(all_vars):
        has_default = var in defaults
        results.append((var, has_default))
    return results
