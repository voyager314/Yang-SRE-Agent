"""Adapter: build prompts from case data and call LLM to get RCA rankings."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from sre_agent.core.llm import DefaultLLM
from sre_agent.utils.jinja import render_template

from eval.data_loader import CaseSummary

_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "rca_analyze.j2"
_TEMPLATE: str | None = None

SYSTEM_NAMES = {
    "re1-ob": "Online Boutique",
    "re1-ss": "Sock Shop",
    "re2-ob": "Online Boutique",
    "re2-ss": "Sock Shop",
    "re2-tt": "Train Ticket",
}


@dataclass
class AnalysisResult:
    """单个 RCAEval case 的模型分析结果。

    ``ranks`` 保存模型认为最可能的根因指标，顺序就是模型的置信度顺序；
    ``raw_response`` 保留未经裁剪的模型原文，便于排查 JSON 解析或提示词问题；
    ``elapsed`` 是本次 LLM 调用耗时（秒），用于统计评测速度。
    """

    ranks: list[str]  # 归一化后的候选指标，例如 ``frontend_cpu``。
    raw_response: str  # 模型返回的原始文本，不保证是合法 JSON。
    elapsed: float  # 从发起请求到收到响应的墙钟时间，单位为秒。


def _load_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _TEMPLATE


def analyze_case(llm: DefaultLLM, summary: CaseSummary, dataset: str) -> AnalysisResult:
    """将一个 case 的统计摘要交给 LLM，并解析出根因排序。

    ``summary`` 已经由 :func:`load_and_summarize` 压缩成提示词所需的字段，
    因而本函数不再读取原始 CSV。模型响应可能包含 Markdown 或解释性文本，
    最终统一交给 :func:`parse_ranks` 做容错解析。
    """
    system_name = SYSTEM_NAMES.get(dataset, dataset)
    template = _load_template()

    user_prompt = render_template(template, {
        "system_name": system_name,
        "services": summary.services,
        "inject_time": summary.inject_time,
        "normal_rows": summary.normal_rows,
        "anomal_rows": summary.anomal_rows,
        "total_columns": summary.total_columns,
        "metric_table": summary.metric_table,
    })

    messages = [
        {"role": "system", "content": "You are an expert SRE performing root cause analysis. Respond with ONLY a JSON array."},
        {"role": "user", "content": user_prompt},
    ]

    start = time.time()
    response = llm.completion(messages)
    elapsed = time.time() - start

    ranks = parse_ranks(response.content or "", summary.services)
    return AnalysisResult(ranks=ranks, raw_response=response.content or "", elapsed=elapsed)


def parse_ranks(text: str, known_services: list[str]) -> list[str]:
    """从模型文本中提取候选指标列表。

    解析按“可靠性从高到低”依次尝试：完整 JSON 数组、文本中的 JSON 数组、
    ``service_metric`` 正则匹配。全部失败时返回每个服务的 ``_unknown`` 占位项，
    这样调用方仍可稳定计算指标，而不会因空列表触发额外分支。
    """

    # 第一优先级：响应本身就是 JSON 数组。
    cleaned = text.strip()
    # Strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to find JSON array in text
    match = re.search(r'\[[\s\S]*?\]', text)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: extract "service_metric" patterns from text
    pattern = r'\b(' + '|'.join(re.escape(s) for s in known_services) + r')_(cpu|mem|memory|latency|disk|diskio|delay|loss|load|error|socket)\b'
    matches = re.findall(pattern, text, re.IGNORECASE)
    if matches:
        return [f"{svc}_{metric}" for svc, metric in matches]

    return [f"{s}_unknown" for s in known_services[:5]]
