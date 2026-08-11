"""时间解析工具函数，供多个工具集共享。"""

from __future__ import annotations


def parse_relative_time(value: str, now: float) -> float:
    """将相对时间字符串或 Unix 时间戳字符串转换为时间戳。

    支持 ``-15m``、``-1h``、``-1d`` 等相对格式和纯数字时间戳。
    无法识别的值回退到 ``now``，保证工具返回结构化查询结果或远端错误，
    而不是在参数预处理阶段使整个调查中断。
    """

    # 相对时间统一以负号开头，例如 ``-15m`` 表示从当前时刻向前 15 分钟。
    if value.startswith("-"):
        # 单位映射使用秒作为内部单位，便于直接与 Unix 时间戳相加减。
        unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit = value[-1]
        try:
            # 去掉首尾的 ``-`` 和单位后，只解析中间的整数部分。
            num = int(value[1:-1])
        except ValueError:
            # 参数来自模型时可能格式不完整；回退到 now 比抛异常更适合诊断流程。
            return now
        # 未知单位按秒处理，保持宽容并避免阻断一次远端查询。
        return now - num * unit_map.get(unit, 1)
    try:
        # 非相对格式按绝对 Unix 时间戳处理（允许整数和小数）。
        return float(value)
    except ValueError:
        # ``now`` 同时也是所有无法识别输入的安全默认值。
        return now
