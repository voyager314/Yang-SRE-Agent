"""时间解析工具函数，供多个工具集共享。"""

from __future__ import annotations


def parse_relative_time(value: str, now: float) -> float:
    """将相对时间字符串或 Unix 时间戳字符串转换为时间戳。

    支持 ``-15m``、``-1h``、``-1d`` 等相对格式和纯数字时间戳。
    无法识别的值回退到 ``now``，保证工具返回结构化查询结果或远端错误，
    而不是在参数预处理阶段使整个调查中断。
    """

    if value.startswith("-"):
        unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit = value[-1]
        try:
            num = int(value[1:-1])
        except ValueError:
            return now
        return now - num * unit_map.get(unit, 1)
    try:
        return float(value)
    except ValueError:
        return now
