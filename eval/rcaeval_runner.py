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
    "cpu": "CPU",
    "mem": "MEM",
    "disk": "DISK",
    "delay": "DELAY",
    "loss": "LOSS",
    "socket": "SOCKET",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RCAEval benchmark against sre-agent")
    parser.add_argument("--data-dir", required=True, help="Path to dataset case directory (e.g., .../RE1-OB/RE1-OB)")
    parser.add_argument("--dataset", required=True, help="Dataset identifier (re1-ob, re1-ss, etc.)")
    parser.add_argument("--model", required=True, help="LLM model name or registry key")
    parser.add_argument("--test", action="store_true", help="Smoke test: run only first 2 cases")
    parser.add_argument("--output", default="eval/results", help="Output directory for results JSON")
    parser.add_argument("--length", type=int, default=20, help="Time window in minutes (default 20)")
    return parser.parse_args()


def _service_for_eval(s: str) -> str:
    """Normalize service name for evaluation, matching RCAEval convention."""
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

    evaluators: dict[str, Evaluator] = {}
    overall = Evaluator()

    case_results: list[dict] = []
    total_elapsed = 0.0
    errors = 0

    for i, case in enumerate(cases, 1):
        label = f"{case.service}_{case.fault}/{case.case_id}"
        try:
            summary = load_and_summarize(case, length_minutes=args.length)
            result = analyze_case(llm, summary, args.dataset)

            pred_services: list[str] = []
            seen: set[str] = set()
            for r in result.ranks:
                svc = _service_for_eval(r.split("_", 1)[0])
                if svc not in seen:
                    seen.add(svc)
                    pred_services.append(svc)

            answer_service = _service_for_eval(case.service)

            overall.add_case(pred_services, answer_service)

            fault_key = case.fault
            if fault_key not in evaluators:
                evaluators[fault_key] = Evaluator()
            evaluators[fault_key].add_case(pred_services, answer_service)

            top1 = pred_services[0] if pred_services else "???"
            hit = "OK" if top1 == answer_service else "MISS"
            print(f"[{i}/{len(cases)}] {label} -> {top1} {hit} ({result.elapsed:.1f}s)")

            case_results.append({
                "case": label,
                "service": case.service,
                "fault": case.fault,
                "answer_service": answer_service,
                "predicted_ranks": result.ranks,
                "predicted_services": pred_services[:5],
                "ac1": 1.0 if top1 == answer_service else 0.0,
                "elapsed": round(result.elapsed, 2),
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
    output_file = output_dir / f"{args.dataset}_{args.model}_{timestamp}.json"

    report = {
        "dataset": args.dataset,
        "model": args.model,
        "total_cases": len(cases),
        "errors": errors,
        "ac1": ac1,
        "ac5": ac5,
        "avg5": avg5,
        "avg_speed": round(avg_speed, 2),
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
