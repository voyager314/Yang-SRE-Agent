"""评测运行器：加载场景 → 构建 Mock Engine → 运行 → 评分 → 报告。

用法:
    # 跑所有场景
    python -m eval.runner

    # 跑单个场景
    python -m eval.runner --scenario 001-pod-oom-kill

    # 仅规则评分（不调 LLM Judge，零成本）
    python -m eval.runner --rule-only

    # 自定义场景目录
    python -m eval.runner --scenarios-dir eval/scenarios
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import os
import yaml

# 将项目根目录加入搜索路径，保证 eval/ 能 import src/sre_agent。
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from sre_agent.core.context_manager import ContextManager
from sre_agent.core.engine import Engine, EngineResult
from sre_agent.core.evidence_store import EvidenceStore
from sre_agent.core.llm import DefaultLLM
from sre_agent.core.scratchpad import Scratchpad
from sre_agent.core.tool_executor import ToolExecutor
from sre_agent.utils.jinja import load_prompt

from eval.judge import Judge, _load_env
from eval.mock_tools import build_mock_tools
from eval.scorer import EvalResult, Scorer

logger = logging.getLogger(__name__)

_EVAL_DIR = Path(__file__).parent
_SCENARIOS_DIR = _EVAL_DIR / "scenarios"
_RESULTS_DIR = _EVAL_DIR / "results"


# ────────────────────────────────────────────────────────────
# 场景加载
# ────────────────────────────────────────────────────────────


def load_scenario(path: Path) -> dict[str, Any]:
    """加载单个场景 YAML 文件。"""

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        raise ValueError(f"场景文件为空: {path}")
    return data


def discover_scenarios(scenarios_dir: Path, scenario_filter: str | None = None) -> list[Path]:
    """发现目录下所有场景文件，可选按 ID 过滤。"""

    files = sorted(scenarios_dir.glob("*.yaml")) + sorted(scenarios_dir.glob("*.yml"))
    if scenario_filter:
        files = [f for f in files if scenario_filter in f.stem]
    return files


# ────────────────────────────────────────────────────────────
# Engine 构建（使用 Mock 工具）
# ────────────────────────────────────────────────────────────


def _build_eval_engine(
    scenario: dict[str, Any],
    model: str,
    api_key: str,
    api_base: str,
    max_steps: int = 30,
) -> tuple[Engine, list[Any]]:
    """用 Mock 工具构建 Engine，返回 (engine, mock_tools)。"""

    llm = DefaultLLM(
        model=model,
        api_key=api_key,
        api_base=api_base,
    )

    tool_responses = scenario.get("tool_responses", {})
    mock_tools = build_mock_tools(tool_responses)

    executor = ToolExecutor()
    executor.register_all(mock_tools)

    evidence_store = EvidenceStore(base_dir=Path("temp/eval-evidence"))
    scratchpad = Scratchpad()
    context_manager = ContextManager(
        llm=llm,
        evidence_store=evidence_store,
        scratchpad=scratchpad,
        toolsets={},
    )

    engine = Engine(
        llm=llm,
        tool_executor=executor,
        max_steps=max_steps,
        context_manager=context_manager,
    )

    return engine, mock_tools


# ────────────────────────────────────────────────────────────
# 单场景执行
# ────────────────────────────────────────────────────────────


def run_scenario(
    scenario: dict[str, Any],
    model: str,
    api_key: str,
    api_base: str,
    max_steps: int = 30,
) -> dict[str, Any]:
    """执行单个场景，返回 Agent 的完整输出。"""

    engine, mock_tools = _build_eval_engine(scenario, model, api_key, api_base, max_steps)

    # 构建 system prompt —— 使用一个简化版，告知 Agent 它有哪些工具。
    system_prompt = (
        "You are an expert SRE AI assistant. Diagnose the issue using the available tools.\n"
        "Use update_scratchpad to record your findings, hypotheses, and ruled-out causes.\n"
        "Be systematic: gather data before drawing conclusions."
    )

    question = scenario.get("question", "")
    investigate_prompt = f"Investigate the following issue:\n\n{question}\n\nBe thorough but efficient."

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": investigate_prompt},
    ]

    start_time = time.time()
    result = engine.call(messages)
    elapsed = time.time() - start_time

    # 提取 scratchpad 状态。
    sp = engine.context_manager.scratchpad if engine.context_manager else Scratchpad()

    return {
        "answer": result.answer,
        "tool_calls": result.tool_calls,
        "iterations": result.iterations,
        "converged": result.converged,
        "scratchpad": {
            "findings": list(sp.findings),
            "hypotheses": list(sp.hypotheses),
            "ruled_out": list(sp.ruled_out),
            "next_steps": list(sp.next_steps),
        },
        "elapsed_seconds": round(elapsed, 2),
        "mock_call_logs": {
            tool.name: tool.call_log
            for tool in mock_tools
            if hasattr(tool, "call_log") and tool.call_log
        },
    }


# ────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="SRE Agent Evaluation Runner")
    parser.add_argument("--scenario", type=str, default=None, help="场景 ID 过滤")
    parser.add_argument("--scenarios-dir", type=str, default=str(_SCENARIOS_DIR))
    parser.add_argument("--rule-only", action="store_true", help="仅规则评分，不调 LLM Judge")
    parser.add_argument("--max-steps", type=int, default=30, help="Agent 最大步数")
    parser.add_argument("--output", type=str, default=None, help="结果输出路径")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 加载 .env 配置。
    _load_env()
    
    model = os.environ.get("model_name", "")
    api_key = os.environ.get("api_key", "")
    api_base = os.environ.get("base_url", "")

    if not model:
        print("ERROR: 未配置模型。请在 .env 中设置 model_name。", file=sys.stderr)
        sys.exit(1)

    # 发现场景。
    scenarios_dir = Path(args.scenarios_dir)
    scenario_files = discover_scenarios(scenarios_dir, args.scenario)

    if not scenario_files:
        print(f"未找到场景文件: {scenarios_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"SRE Agent Evaluation")
    print(f"Model: {model}")
    print(f"Scenarios: {len(scenario_files)}")
    print(f"Judge: {'disabled' if args.rule_only else 'enabled'}")
    print(f"{'='*60}\n")

    # 初始化评分器。
    judge = None if args.rule_only else Judge()
    scorer = Scorer(judge=judge)

    # 运行评测。
    all_results: list[dict[str, Any]] = []

    for scenario_path in scenario_files:
        scenario = load_scenario(scenario_path)
        scenario_id = scenario.get("id", scenario_path.stem)
        difficulty = scenario.get("difficulty", "unknown")

        print(f"> {scenario_id} [{difficulty}] ...", end=" ", flush=True)

        try:
            # 执行 Agent。
            agent_output = run_scenario(
                scenario, model, api_key, api_base, max_steps=args.max_steps,
            )

            # 评分。
            ground_truth = scenario.get("ground_truth", {})
            eval_result = scorer.score(
                scenario_id=scenario_id,
                answer=agent_output["answer"],
                ground_truth=ground_truth,
                scratchpad=agent_output["scratchpad"],
                tool_calls=agent_output["tool_calls"],
                iterations=agent_output["iterations"],
                converged=agent_output["converged"],
            )

            result_entry = {
                "scenario_id": scenario_id,
                "difficulty": difficulty,
                "elapsed_seconds": agent_output["elapsed_seconds"],
                "agent_output": {
                    "answer": agent_output["answer"][:500],
                    "iterations": agent_output["iterations"],
                    "converged": agent_output["converged"],
                    "tool_calls_count": len(agent_output["tool_calls"]),
                    "scratchpad": agent_output["scratchpad"],
                },
                "scores": eval_result.to_dict(),
            }
            all_results.append(result_entry)

            # 打印单场景结果。
            dims = {d.name: d.score for d in eval_result.dimensions}
            print(
                f"composite={eval_result.composite:.2f} "
                f"[root_cause={dims.get('root_cause', 0):.2f} "
                f"reasoning={dims.get('reasoning', 0):.2f} "
                f"report={dims.get('report', 0):.2f} "
                f"efficiency={dims.get('efficiency', 0):.2f}] "
                f"({agent_output['elapsed_seconds']:.1f}s)"
            )

        except Exception as e:
            print(f"FAILED: {e}")
            logger.exception("场景执行失败: %s", scenario_id)
            all_results.append({
                "scenario_id": scenario_id,
                "difficulty": difficulty,
                "error": str(e),
            })

    # 打印汇总。
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")

    scored = [r for r in all_results if "scores" in r]
    if scored:
        avg_composite = sum(r["scores"]["composite"] for r in scored) / len(scored)
        print(f"  Scenarios: {len(scored)} passed / {len(all_results)} total")
        print(f"  Average composite: {avg_composite:.3f}")

        # 按维度汇总。
        for dim_name in ("root_cause", "signal_coverage", "reasoning", "efficiency", "report"):
            dim_scores = [
                r["scores"]["dimensions"].get(dim_name, {}).get("score", 0) for r in scored
            ]
            if dim_scores:
                avg = sum(dim_scores) / len(dim_scores)
                print(f"  {dim_name:20s}: {avg:.3f}")
    else:
        print("  No scenarios completed successfully.")

    failed = [r for r in all_results if "error" in r]
    if failed:
        print(f"\n  Failed scenarios:")
        for r in failed:
            print(f"    - {r['scenario_id']}: {r['error']}")

    # 保存结果。
    output_path = args.output
    if not output_path:
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        output_path = str(_RESULTS_DIR / f"eval_{timestamp}.json")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "model": model,
                "rule_only": args.rule_only,
                "results": all_results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n  Results saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()
