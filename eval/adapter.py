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
    ranks: list[str]
    raw_response: str
    elapsed: float


def _load_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _TEMPLATE


def analyze_case(llm: DefaultLLM, summary: CaseSummary, dataset: str) -> AnalysisResult:
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
    # Try direct JSON parse
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
