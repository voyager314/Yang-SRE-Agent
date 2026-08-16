"""RCAEval benchmark runner: iterate cases, call adapter, aggregate scores, write report.

Usage:
    cd D:\\14297\\vsc_project\\python\\kkk\\SRE-Agent
    python -m eval.rcaeval_runner \\
        --data-dir D:\\14297\\vsc_project\\python\\kkk\\RCAEval\\data\\RE1-OB\\RE1-OB \\
        --dataset re1-ob \\
        --model <model_name> \\
        --test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure src/ is on the path for sre_agent imports.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from sre_agent.config import Config
from sre_agent.core.llm import DefaultLLM

from eval.adapter import analyze_case
from eval.data_loader import discover_cases, load_and_summarize
from eval.metrics import Evaluator

FAULT_DISPLAY = {
    # 数据集目录中的故障键 -> 终端报告使用的展示名称。
    "cpu": "CPU",
    "mem": "MEM",
    "disk": "DISK",
    "delay": "DELAY",
    "loss": "LOSS",
    "socket": "SOCKET",
}


def parse_args() -> argparse.Namespace:
    """解析命令行参数；各参数含义也会显示在 ``--help`` 中。"""
    parser = argparse.ArgumentParser(description="Run RCAEval benchmark against sre-agent")
    parser.add_argument("--data-dir", required=True, help="数据集 case 根目录（例如 .../RE1-OB/RE1-OB）")
    parser.add_argument("--dataset", required=True, help="数据集标识（re1-ob、re1-ss 等）")
    parser.add_argument("--model", required=True, help="模型名或配置文件中的模型注册键")
    parser.add_argument("--test", action="store_true", help="冒烟测试：只运行排序后的前 2 个 case")
    parser.add_argument("--output", default="eval/results", help="结果 JSON 的输出目录")
    parser.add_argument("--length", type=int, default=20, help="正常/异常合计时间窗口（分钟，默认 20）")
    return parser.parse_args()


def _service_for_eval(s: str) -> str:
    """按 RCAEval 约定规范化服务名。

    数据中 ``foo-db`` 表示数据库伴生服务，但评分只比较逻辑服务 ``foo``，
    因此这里统一去掉 ``-db`` 后缀。
    """
    return s.replace("-db", "")


def main() -> None:
    args = parse_args()

    cases = discover_cases(args.data_dir)
    if not cases:
        print(f"No cases found in {args.data_dir}")
        sys.exit(1)

    if args.test:
        cases = cases[:2]

    print(f"Dataset: {args.dataset}")
    print(f"Model: {args.model}")
    print(f"Cases: {len(cases)}")
    print()

    config = Config(model=args.model, memory_enabled=False)
    model_entry = config.resolve_model(args.model)
    llm = DefaultLLM(
        model=model_entry.model,
        api_key=model_entry.api_key.get_secret_value() if model_entry.api_key else None,
        api_base=model_entry.api_base,
        api_version=model_entry.api_version,
    )

    # 每种 fault 一个独立聚合器；overall 跨全部 fault 汇总。
    evaluators: dict[str, Evaluator] = {}
    overall = Evaluator()

    case_results: list[dict] = []  # 每个 case 的预测、命中情况和错误信息。
    total_elapsed = 0.0  # 成功 case 的 LLM 调用耗时总和（秒）。
    errors = 0  # 执行失败的 case 数量，不计入 Evaluator 分母。

    for i, case in enumerate(cases, 1):
        label = f"{case.service}_{case.fault}/{case.case_id}"
        try:
            summary = load_and_summarize(case, length_minutes=args.length)
            result = analyze_case(llm, summary, args.dataset)

            # 模型输出的是 service_metric，评分只看服务；同时去重保持排名顺序。
            pred_services: list[str] = []
            seen: set[str] = set()
            for r in result.ranks:
                svc = _service_for_eval(r.split("_", 1)[0])
                if svc not in seen:
                    seen.add(svc)
                    pred_services.append(svc)

            answer_service = _service_for_eval(case.service)  # 真实根因服务。

            overall.add_case(pred_services, answer_service)

            fault_key = case.fault
            if fault_key not in evaluators:
                evaluators[fault_key] = Evaluator()
            evaluators[fault_key].add_case(pred_services, answer_service)

            top1 = pred_services[0] if pred_services else "???"
            hit = "OK" if top1 == answer_service else "MISS"
            print(f"[{i}/{len(cases)}] {label} -> {top1} {hit} ({result.elapsed:.1f}s)")

            case_results.append({
                "case": label,  # 可读标签：service_fault/case_id。
                "service": case.service,  # 数据集原始服务名。
                "fault": case.fault,  # 数据集原始故障类型。
                "answer_service": answer_service,  # 规范化后的真实服务。
                "predicted_ranks": result.ranks,  # 模型返回的 service_metric 排名。
                "predicted_services": pred_services[:5],  # 去重后的 Top-5 服务排名。
                "ac1": 1.0 if top1 == answer_service else 0.0,  # 本 case 的 AC@1。
                "elapsed": round(result.elapsed, 2),  # 本 case 的 LLM 调用耗时（秒）。
            })
            total_elapsed += result.elapsed

        except Exception as e:
            print(f"[{i}/{len(cases)}] {label} -> ERROR: {e}")
            errors += 1
            case_results.append({
                "case": label,
                "service": case.service,
                "fault": case.fault,
                "error": str(e),
            })

    print()
    print(f"--- Evaluation Results ({args.dataset}, {args.model}) ---")
    for fault_key in sorted(evaluators.keys()):
        ev = evaluators[fault_key]
        display = FAULT_DISPLAY.get(fault_key, fault_key.upper())
        avg5 = ev.average(5)
        if avg5 is not None:
            print(f"Avg@5-{display}:".ljust(16) + f"{avg5:.2f}")
    print("---")

    ac1 = overall.accuracy(1)
    ac5 = overall.accuracy(5)
    avg5 = overall.average(5)
    if ac1 is not None:
        print(f"AC@1 overall:   {ac1:.2f}")
    if ac5 is not None:
        print(f"AC@5 overall:   {ac5:.2f}")
    if avg5 is not None:
        print(f"Avg@5 overall:  {avg5:.2f}")

    completed = len(cases) - errors
    avg_speed = total_elapsed / completed if completed > 0 else 0
    print(f"Avg speed:      {avg_speed:.2f} s/case")
    if errors:
        print(f"Errors:         {errors}")

    output_dir = Path(args.output).absolute()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    t=args.model
    args.model=t[t.index('/')+1:]
    output_file = output_dir / f"{args.dataset}_{args.model}_{timestamp}.json"

    report = {
        "dataset": args.dataset,  # 数据集标识。
        "model": args.model,  # 实际用于调用的模型名（去掉 provider 前缀后的文件名版本）。
        "total_cases": len(cases),  # 计划运行的 case 总数，包含失败项。
        "errors": errors,  # 运行失败的 case 数。
        "ac1": ac1,  # 全部成功 case 的 AC@1。
        "ac5": ac5,  # 全部成功 case 的 AC@5。
        "avg5": avg5,  # 全部成功 case 的 Avg@5。
        "avg_speed": round(avg_speed, 2),  # 平均每个成功 case 的耗时（秒）。
        "per_fault": {
            fault_key: {
                "count": ev.count,
                "ac1": ev.accuracy(1),
                "ac5": ev.accuracy(5),
                "avg5": ev.average(5),
            }
            for fault_key, ev in sorted(evaluators.items())
        },
        "cases": case_results,
    }

    with output_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
