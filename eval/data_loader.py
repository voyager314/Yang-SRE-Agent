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
    """RCAEval 目录中一个故障样本的定位信息。

    数据集通常按 ``<service>_<fault>/<case_id>/data.csv`` 组织；这些字段
    是从路径推导出的标签，不是从 CSV 内容猜测出来的。
    """

    data_path: str  # ``data.csv`` 的完整路径。
    service: str  # 注入故障的目标服务，例如 ``frontend``。
    fault: str  # 故障类型，例如 ``cpu``、``mem`` 或 ``delay``。
    case_id: str  # 当前实验用例目录名，用于在报告中唯一标识样本。


@dataclass
class CaseSummary:
    """供提示词使用的时序数据摘要。

    该对象把长 CSV 转换成有限大小的统计表，避免把全部采样点直接发送给
    LLM，同时保留评测所需的时间窗口和服务标签。
    """

    case: CaseInfo  # 原始 case 的路径及真实故障标签。
    inject_time: int  # 故障注入时刻；与 CSV ``time`` 列使用同一时间单位。
    services: list[str]  # 从指标列名前缀提取出的去重服务名，保持首次出现顺序。
    metric_table: str  # 按变化幅度排序后的可读统计表，作为提示词正文。
    normal_rows: int  # 注入前窗口实际保留的采样行数。
    anomal_rows: int  # 注入后窗口实际保留的采样行数。
    total_columns: int  # 去掉 ``time`` 后的指标列数量。


def discover_cases(data_dir: str) -> list[CaseInfo]:
    """递归发现所有包含 ``data.csv`` 的 case 目录。

    路径的上两级目录必须能按第一个下划线拆成 ``service`` 和 ``fault``；
    不符合约定的目录会被静默跳过，以兼容数据集中的辅助文件。
    """
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
    """读取一个 case，并生成正常/异常窗口的逐指标统计摘要。

    ``length_minutes`` 表示总窗口长度：函数将它平均分配给注入前和注入后
    两段（每段 ``length_minutes * 60 / 2`` 个时间单位），分别计算均值、标准差
    和相对变化率，再只保留变化最大的 40 个指标用于展示。
    """
    df = pd.read_csv(case.data_path)

    inject_time_path = os.path.join(os.path.dirname(case.data_path), "inject_time.txt")
    with open(inject_time_path) as f:
        inject_time = int(f.readline().strip())

    df = df.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

    # Drop duplicate column if present (RE1-OB has two)
    cols = list(df.columns)
    seen = set()
    keep = []
    for c in cols:
        if c in seen:
            continue
        seen.add(c)
        keep.append(c)
    df = df[keep] # 根据标签列表去索引DataFrame，返回一个只包含指定列的新DataFrame

    # 窗口总长度由调用方控制，并平均分成“正常”和“异常”两半。
    window = length_minutes * 60 // 2
    normal_df = df[df["time"] < inject_time].tail(window)
    anomal_df = df[df["time"] >= inject_time].head(window)
    df = pd.concat([normal_df, anomal_df], ignore_index=True)

    metric_cols = [c for c in df.columns if c != "time"]

    # Extract unique service names from columns
    services = _extract_services(metric_cols)

    # 对每个指标分别计算两段窗口的水平变化和波动变化。
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
            "metric": col,  # 原始指标列名，通常包含服务和指标类型。
            "service": _extract_service(col),  # 指标所属服务。
            "normal_mean": n_mean,  # 注入前窗口均值。
            "anomal_mean": a_mean,  # 注入后窗口均值。
            "change_ratio": change_ratio,  # 均值相对变化：(异常-正常)/|正常|。
            "normal_std": n_std,  # 注入前窗口标准差。
            "anomal_std": a_std,  # 注入后窗口标准差。
            "std_change": std_change,  # 标准差相对变化：(异常-正常)/正常。
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
