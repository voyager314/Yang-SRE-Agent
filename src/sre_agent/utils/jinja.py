from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

_env = Environment(loader=BaseLoader(), undefined=__import__("jinja2").DebugUndefined)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def render_template(template_str: str, variables: dict[str, Any]) -> str:
    template = _env.from_string(template_str)
    return template.render(**variables)


def load_prompt(name: str, variables: dict[str, Any] | None = None) -> str:
    path = _PROMPTS_DIR / f"{name}.j2"
    template_str = path.read_text(encoding="utf-8")
    if variables:
        return render_template(template_str, variables)
    return template_str


def extract_variables(template_str: str) -> list[tuple[str, bool]]:
    var_pattern = re.compile(r"\{\{[^}]*?\b(\w+)\b[^}]*?\}\}")
    default_pattern = re.compile(r"\{\{[^}]*?(\w+)\s*\|\s*default\(")

    all_vars: set[str] = set()
    for match in var_pattern.finditer(template_str):
        inner = match.group(0)[2:-2]
        identifiers = re.findall(r"\b([a-zA-Z_]\w*)\b", inner)
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
