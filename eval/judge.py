"""LLM-as-Judge 客户端，从根目录 .env 读取模型配置。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

logger = logging.getLogger(__name__)

_EVAL_DIR = Path(__file__).parent
_PROMPT_DIR = _EVAL_DIR / "prompts"
_jinja_env = Environment(loader=BaseLoader())


def _load_env(env_path: Path | None = None) -> None:
    """从 .env 文件加载配置到 os.environ（已存在的变量不覆盖）。"""

    path = env_path or Path(__file__).parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _render_prompt(template_name: str, variables: dict[str, Any]) -> str:
    """渲染 eval/prompts/ 下的 Jinja 模板。"""

    path = _PROMPT_DIR / template_name
    template_str = path.read_text(encoding="utf-8")
    template = _jinja_env.from_string(template_str)
    return template.render(**variables)


class Judge:
    """通过 LiteLLM 调用 Judge 模型进行评分。

    配置来自根目录 ``.env`` 中的 ``base_url``、``api_key``、``model_name``。
    可通过环境变量 ``JUDGE_MODEL``、``JUDGE_API_KEY``、``JUDGE_BASE_URL``
    覆盖，优先级高于 .env。
    """

    def __init__(self, env_path: Path | None = None) -> None:
        _load_env(env_path)

        self.model = os.environ.get("model_name", "")
        self.api_key = os.environ.get("api_key", "")
        self.api_base = os.environ.get("base_url", "")

        if not self.model:
            raise ValueError(
                "Judge 模型未配置。请在 .env 中设置 model_name 或环境变量 JUDGE_MODEL"
            )

    def evaluate(
        self,
        answer: str,
        ground_truth: dict[str, Any],
        scratchpad: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        iterations: int = 0,
        converged: bool = False,
        retries: int = 3,
    ) -> dict[str, Any]:
        """使用 Judge Prompt 评分，返回解析后的 JSON 结果。

        调用失败时重试 ``retries`` 次；全部失败返回全零分并附带错误信息。
        """

        prompt = _render_prompt(
            "judge.j2",
            {
                "answer": answer,
                "root_cause_service": ground_truth.get("root_cause_service", ""),
                "root_cause_type": ground_truth.get("root_cause_type", ""),
                "key_signals": ground_truth.get("key_signals", []),
                "wrong_conclusions": ground_truth.get("wrong_conclusions", []),
                "findings": scratchpad.get("findings", []),
                "hypotheses": scratchpad.get("hypotheses", []),
                "ruled_out": scratchpad.get("ruled_out", []),
                "tool_calls": tool_calls,
                "iterations": iterations,
                "converged": converged,
            },
        )

        import litellm

        for attempt in range(retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.api_base:
                    kwargs["api_base"] = self.api_base

                response = litellm.completion(**kwargs)
                content = response.choices[0].message.content or ""
                return self._parse_response(content)
            except Exception:
                logger.warning("Judge 调用失败 (attempt %d/%d)", attempt + 1, retries, exc_info=True)

        return self._empty_result("Judge 调用全部失败")

    def _parse_response(self, content: str) -> dict[str, Any]:
        """从 Judge 响应中提取 JSON，容忍 markdown 代码块包裹。"""

        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines[1:] if not line.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试从文本中提取第一个 JSON 对象。
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    result = json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    return self._empty_result(f"Judge 返回无法解析的内容: {cleaned[:200]}")
            else:
                return self._empty_result(f"Judge 返回无法解析的内容: {cleaned[:200]}")

        # 归一化结构，确保下游始终拿到一致的字段。
        normalized: dict[str, Any] = {}
        for key in ("root_cause_accuracy", "reasoning_quality", "report_usefulness"):
            entry = result.get(key, {})
            if isinstance(entry, dict):
                normalized[key] = {
                    "evidence": entry.get("evidence", ""),
                    "score": int(entry.get("score", 0)),
                }
            else:
                normalized[key] = {"evidence": "", "score": 0}
        return normalized

    @staticmethod
    def _empty_result(error: str) -> dict[str, Any]:
        """生成全零分的降级结果。"""

        return {
            "root_cause_accuracy": {"evidence": error, "score": 0},
            "reasoning_quality": {"evidence": error, "score": 0},
            "report_usefulness": {"evidence": error, "score": 0},
        }
