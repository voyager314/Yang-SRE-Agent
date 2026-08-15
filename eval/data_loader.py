"""Load RCAEval case data and produce per-metric anomaly summaries."""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class CaseInfo:
    data_path: str
    service: str
    fault: str
    case_id: str


@dataclass
class CaseSummary:
    case: CaseInfo
    inject_time: int
    services: list[str]
    metric_table: str
    normal_rows: int
    anomal_rows: int
    total_columns: int


def discover_cases(data_dir: str) -> list[CaseInfo]:
    pattern = os.path.join(data_dir, "**", "data.csv")
    paths = sorted(glob.glob(pattern, recursive=True))
    cases: list[CaseInfo] = []
    for p in paths:
        case_id = os.path.basename(os.path.dirname(p))
        service_fault = os.path.basename(os.path.dirname(os.path.dirname(p)))
        parts = service_fault.split("_", 1)
        if len(parts) != 2:
            continue
        cases.append(CaseInfo(data_path=p, service=parts[0], fault=parts[1], case_id=case_id))
    return cases


def load_and_summarize(case: CaseInfo, length_minutes: int = 20) -> CaseSummary:
    df = pd.read_csv(case.data_path)

    inject_time_path = os.path.join(os.path.dirname(case.data_path), "inject_time.txt")
    with open(inject_time_path) as f:
        inject_time = int(f.readline().strip())

    df = df.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

    # Drop duplicate 'time' column if present (RE1-OB has two)
    cols = list(df.columns)
    seen = set()
    keep = []
    for c in cols:
        if c in seen:
            continue
        seen.add(c)
        keep.append(c)
    df = df[keep]

    # Window: take length_minutes of normal + anomalous data
    window = length_minutes * 60 // 2
    normal_df = df[df["time"] < inject_time].tail(window)
    anomal_df = df[df["time"] >= inject_time].head(window)
    df = pd.concat([normal_df, anomal_df], ignore_index=True)

    metric_cols = [c for c in df.columns if c != "time"]

    # Extract unique service names from columns
    services = _extract_services(metric_cols)

    # Compute per-metric statistics
    records = []
    for col in metric_cols:
        n_vals = normal_df[col] if col in normal_df.columns else pd.Series(dtype=float)
        a_vals = anomal_df[col] if col in anomal_df.columns else pd.Series(dtype=float)

        n_mean = n_vals.mean() if len(n_vals) > 0 else 0.0
        a_mean = a_vals.mean() if len(a_vals) > 0 else 0.0
        n_std = n_vals.std() if len(n_vals) > 1 else 0.0
        a_std = a_vals.std() if len(a_vals) > 1 else 0.0

        if n_mean != 0:
            change_ratio = (a_mean - n_mean) / abs(n_mean)
        elif a_mean != 0:
            change_ratio = float("inf") if a_mean > 0 else float("-inf")
        else:
            change_ratio = 0.0

        if n_std != 0:
            std_change = (a_std - n_std) / n_std
        else:
            std_change = 0.0

        records.append({
            "metric": col,
            "service": _extract_service(col),
            "normal_mean": n_mean,
            "anomal_mean": a_mean,
            "change_ratio": change_ratio,
            "normal_std": n_std,
            "anomal_std": a_std,
            "std_change": std_change,
        })

    # Sort by absolute change ratio, take top 40
    records.sort(key=lambda r: abs(r["change_ratio"]) if np.isfinite(r["change_ratio"]) else 1e10, reverse=True)
    top = records[:40]

    # Format as text table
    lines = [f"{'Metric':<55} {'Service':<25} {'Normal Mean':>14} {'Anomal Mean':>14} {'Change%':>10} {'StdChange%':>10}"]
    lines.append("-" * 132)
    for r in top:
        cr = f"{r['change_ratio'] * 100:+.1f}" if np.isfinite(r["change_ratio"]) else "INF"
        sc = f"{r['std_change'] * 100:+.1f}" if np.isfinite(r["std_change"]) else "INF"
        lines.append(
            f"{r['metric']:<55} {r['service']:<25} {r['normal_mean']:>14.4f} {r['anomal_mean']:>14.4f} {cr:>10} {sc:>10}"
        )

    return CaseSummary(
        case=case,
        inject_time=inject_time,
        services=services,
        metric_table="\n".join(lines),
        normal_rows=len(normal_df),
        anomal_rows=len(anomal_df),
        total_columns=len(metric_cols),
    )


def _extract_service(col_name: str) -> str:
    return col_name.split("_", 1)[0]


def _extract_services(columns: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for col in columns:
        svc = _extract_service(col)
        if svc not in seen:
            seen.add(svc)
            result.append(svc)
    return result
