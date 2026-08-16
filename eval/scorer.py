"""规则评分 + LLM-as-Judge 混合评分管道。

维度 1-2 先用规则快速打分，不确定时交给 LLM 二审。
维度 3 (推理质量) 和维度 4 (结论可用性) 由 LLM Judge 主审。
维度 E (工具效率) 纯规则。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from eval.judge import Judge

logger = logging.getLogger(__name__)


@dataclass
class DimensionScore:
    """单维度评分结果，分数统一归一化到 0~1。

    ``method`` 标记分数来源，``details`` 保存简短证据，便于在结果 JSON 中
    解释为什么得到该分数。
    """

    name: str  # 维度标识：root_cause、signal_coverage、reasoning、efficiency 或 report。
    score: float  # 实际得分，归一化到 0~1。
    max_score: float = 1.0  # 理论满分，当前保留字段以兼容扩展。
    method: str = ""  # 评分来源：rule、llm、rule+llm 或 skipped。
    details: str = ""  # 面向人的证据/计算摘要，不参与数值计算。


@dataclass
class EvalResult:
    """一个场景的完整评分结果及其加权总分。"""

    scenario_id: str  # 场景 ID，用于和输入 YAML 及报告记录关联。
    dimensions: list[DimensionScore] = field(default_factory=list)  # 各评分维度明细。
    composite: float = 0.0  # 按 WEIGHTS 加权后的综合分数（0~1）。
    llm_judge_raw: dict[str, Any] = field(default_factory=dict)  # Judge 原始归一化响应。

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "composite": round(self.composite, 3),
            "dimensions": {
                d.name: {"score": round(d.score, 3), "method": d.method, "details": d.details}
                for d in self.dimensions
            },
            "llm_judge_raw": self.llm_judge_raw,
        }


# ────────────────────────────────────────────────────────────
# 维度权重
# ────────────────────────────────────────────────────────────

WEIGHTS = {
    "root_cause": 0.30,  # 是否定位到正确服务及故障类型。
    "signal_coverage": 0.15,  # 是否覆盖 ground_truth 声明的关键观测信号。
    "reasoning": 0.25,  # 调查过程是否有证据链和合理推理。
    "efficiency": 0.10,  # 工具调用数量、重复率及是否被迫停止。
    "report": 0.20,  # 最终报告是否清晰、可执行且对用户有帮助。
}


# ────────────────────────────────────────────────────────────
# 规则评分器
# ────────────────────────────────────────────────────────────


def _normalize_text(*sources: str) -> str:
    """合并多个文本源，统一小写，用于关键词匹配。"""

    return "\n".join(s.lower() for s in sources if s)


def score_root_cause_rule(
    answer: str,
    scratchpad: dict[str, Any],
    ground_truth: dict[str, Any],
) -> float:
    """维度 1：根因定位（规则评分，满分 1.0）。

    服务名和故障类型各占 0.4 分；没有复述 ground truth 中的错误结论再得
    0.2 分。文本来源同时包含最终答案、调查发现和候选假设。
    """

    text = _normalize_text(
        answer,
        *scratchpad.get("findings", []),
        *scratchpad.get("hypotheses", []),
    )

    score = 0.0

    # 服务定位 (0.4)
    service = ground_truth.get("root_cause_service", "").lower()
    if service and service in text:
        score += 0.4

    # 故障类型 (0.4)
    fault_type = ground_truth.get("root_cause_type", "").lower()
    # 支持常见等价表述。
    aliases: dict[str, list[str]] = {
        "oom-kill": ["oom", "out of memory", "outofmemory", "内存溢出", "内存不足", "heap space"],
        "cpu-throttle": ["cpu throttl", "cpu 限流", "cpu限流"],
        "connection-pool-exhaustion": ["connection pool", "连接池", "pool exhaust"],
        "disk-full": ["disk full", "no space left", "磁盘满", "磁盘空间不足"],
        "dns-failure": ["dns", "name resolution", "域名解析", "servfail", "no such host"],
        "certificate-expired": ["certificate", "cert", "tls", "ssl", "证书"],
        "rate-limiting": ["rate limit", "429", "too many requests", "限流", "throttl"],
        "slow-query": ["slow query", "慢查询", "seq scan", "missing index", "缺少索引", "全表扫描"],
        "config-drift-memory-leak": [
            "cache.ttl", "ttl", "infinite", "配置变更", "config",
            "配置.*泄漏", "cache.*无限", "config.*leak",
            "ttl changed", "配置漂移", "cache ttl",
        ],
    }
    type_matched = False
    if fault_type and fault_type in text:
        type_matched = True
    elif fault_type in aliases:
        type_matched = any(alias in text for alias in aliases[fault_type])
    if type_matched:
        score += 0.4

    # 无错误结论 (0.2)
    wrong_list = ground_truth.get("wrong_conclusions", [])
    has_wrong = any(wrong.lower() in text for wrong in wrong_list)
    if not has_wrong:
        score += 0.2

    return score


def score_signal_coverage_rule(
    answer: str,
    scratchpad: dict[str, Any],
    ground_truth: dict[str, Any],
) -> float:
    """维度 2：关键信号覆盖率（规则评分）。

    必需信号贡献 0.8 分，可选信号贡献 0.2 分；每个信号用 ``/`` 分隔同义
    关键词，命中任意一个关键词即视为识别。
    """

    text = _normalize_text(answer, *scratchpad.get("findings", []))

    signals = ground_truth.get("key_signals", [])
    if not signals:
        return 1.0

    required = [s for s in signals if s.get("required")]
    optional = [s for s in signals if not s.get("required")]

    def _hit(signal_text: str) -> bool:
        # 将信号文本拆成关键词组，任意一组全部命中即认为识别。
        keywords = [kw.strip().lower() for kw in signal_text.split("/")]
        return any(kw in text for kw in keywords if kw)

    req_hits = sum(1 for s in required if _hit(s["signal"]))
    opt_hits = sum(1 for s in optional if _hit(s["signal"]))

    base = (req_hits / len(required) * 0.8) if required else 0.8
    bonus = (opt_hits / len(optional) * 0.2) if optional else 0.0
    return base + bonus


def score_efficiency_rule(
    tool_calls: list[dict[str, Any]],
    iterations: int,
    converged: bool,
    max_steps: int = 30,
) -> float:
    """维度 E：工具使用效率（纯规则，初始分 1.0，按浪费行为扣分）。

    过多调用、重复的 name+arguments，以及 ``converged`` 为真（通常表示
    达到步数上限）都会扣分；结果始终截断在 0~1。
    """

    score = 1.0

    # 惩罚过多工具调用。
    n_calls = len(tool_calls)
    if n_calls > 25:
        score -= 0.3
    elif n_calls > 15:
        score -= 0.15

    # 惩罚重复调用（完全相同的 name+arguments）。
    seen: set[str] = set()
    duplicates = 0
    for tc in tool_calls:
        key = f"{tc.get('name', '')}:{tc.get('arguments', '')}"
        if key in seen:
            duplicates += 1
        seen.add(key)
    if duplicates > 2:
        score -= 0.2
    elif duplicates > 0:
        score -= 0.1

    # 惩罚被迫收敛。
    if converged:
        score -= 0.2

    return max(0.0, score)


# ────────────────────────────────────────────────────────────
# 混合评分管道
# ────────────────────────────────────────────────────────────


class Scorer:
    """混合评分器：规则打底，必要时由 LLM-as-Judge 补充语义判断。"""

    def __init__(self, judge: Judge | None = None) -> None:
        self.judge = judge

    def score(
        self,
        scenario_id: str,
        answer: str,
        ground_truth: dict[str, Any],
        scratchpad: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        iterations: int = 0,
        converged: bool = False,
    ) -> EvalResult:
        """运行完整评分管道，返回多维度结果。

        ``ground_truth`` 和 ``scratchpad`` 的字段含义与 Judge Prompt 保持一致；
        ``tool_calls``、``iterations``、``converged`` 仅用于效率维度和 Judge 上下文。
        当未提供 Judge 时，推理和报告维度会标记为 ``skipped`` 并计 0 分。
        """

        result = EvalResult(scenario_id=scenario_id)

        # ── 规则评分 ──

        d1_rule = score_root_cause_rule(answer, scratchpad, ground_truth)
        d2_rule = score_signal_coverage_rule(answer, scratchpad, ground_truth)
        d_eff = score_efficiency_rule(tool_calls, iterations, converged)

        # ── LLM Judge ──

        llm_scores: dict[str, Any] = {}
        if self.judge is not None:
            try:
                llm_scores = self.judge.evaluate(
                    answer=answer,
                    ground_truth=ground_truth,
                    scratchpad=scratchpad,
                    tool_calls=tool_calls,
                    iterations=iterations,
                    converged=converged,
                )
                result.llm_judge_raw = llm_scores
            except Exception:
                logger.warning("LLM Judge 调用失败，降级为纯规则评分", exc_info=True)

        # ── 合成各维度最终分数 ──

        # 维度 1: 根因定位
        # 规则评分 >= 0.6 时信任规则；否则取规则和 LLM 的较高值（LLM 二审捕获语义等价）。
        d1_llm = llm_scores.get("root_cause_accuracy", {}).get("score", 0) / 5.0
        if d1_rule >= 0.6 or not llm_scores:
            d1_final = d1_rule
            d1_method = "rule"
        else:
            d1_final = max(d1_rule, d1_llm)
            d1_method = "rule+llm"

        result.dimensions.append(DimensionScore(
            name="root_cause",
            score=d1_final,
            method=d1_method,
            details=f"rule={d1_rule:.2f} llm={d1_llm:.2f}",
        ))

        # 维度 2: 信号覆盖
        d2_llm = 0.0  # Judge prompt 不单独评信号，复用根因判断间接覆盖
        if d2_rule >= 0.6 or not llm_scores:
            d2_final = d2_rule
            d2_method = "rule"
        else:
            d2_final = d2_rule  # 信号覆盖以规则为准，LLM 不擅长逐条核对
            d2_method = "rule"

        result.dimensions.append(DimensionScore(
            name="signal_coverage",
            score=d2_final,
            method=d2_method,
            details=f"rule={d2_rule:.2f}",
        ))

        # 维度 3: 推理质量（LLM 主审）
        d3_llm = llm_scores.get("reasoning_quality", {}).get("score", 0) / 5.0
        d3_evidence = llm_scores.get("reasoning_quality", {}).get("evidence", "")
        result.dimensions.append(DimensionScore(
            name="reasoning",
            score=d3_llm if llm_scores else 0.0,
            method="llm" if llm_scores else "skipped",
            details=d3_evidence[:200],
        ))

        # 维度 4: 工具效率（纯规则）
        result.dimensions.append(DimensionScore(
            name="efficiency",
            score=d_eff,
            method="rule",
            details=f"calls={len(tool_calls)} iters={iterations} converged={converged}",
        ))

        # 维度 5: 报告可用性（LLM 主审）
        d5_llm = llm_scores.get("report_usefulness", {}).get("score", 0) / 5.0
        d5_evidence = llm_scores.get("report_usefulness", {}).get("evidence", "")
        result.dimensions.append(DimensionScore(
            name="report",
            score=d5_llm if llm_scores else 0.0,
            method="llm" if llm_scores else "skipped",
            details=d5_evidence[:200],
        ))

        # ── 加权合成 ──

        result.composite = sum(
            d.score * WEIGHTS.get(d.name, 0.0) for d in result.dimensions
        )

        return result
