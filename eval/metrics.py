"""AC@k and Avg@5 evaluation metrics compatible with RCAEval scoring."""

from __future__ import annotations

from dataclasses import dataclass, field


def accuracy_at_k(predicted_services: list[str], answer: str, k: int) -> float:
    """计算单个 case 的 AC@k（前 k 个候选中是否包含真实服务）。

    命中返回 ``1.0``，未命中返回 ``0.0``；列表不足 k 项时按实际长度判断。
    ``answer`` 应与 ``predicted_services`` 使用同一服务名规范。
    """
    return 1.0 if answer in predicted_services[:k] else 0.0


def avg_at_k(predicted_services: list[str], answer: str, k: int = 5) -> float:
    """计算单个 case 的 Avg@k。

    该指标是 AC@1 到 AC@k 的平均值：真实根因排名越靠前，得分越高；
    即使在较小的 ``i`` 中已经命中，后续 ``i`` 也继续计为命中。
    """
    return sum(accuracy_at_k(predicted_services, answer, i) for i in range(1, k + 1)) / k


@dataclass
class Evaluator:
    """累积多个 case 的命中情况并计算总体指标。

    ``_ac_hits`` 的每一项固定为长度 5 的布尔列表，第 i 项表示真实服务
    是否出现在前 ``i + 1`` 名。补齐到 5 项可以让不同长度的模型输出使用
    同一套聚合逻辑。
    """

    _ac_hits: list[list[bool]] = field(default_factory=list)  # 每个 case 的 Top-5 命中轨迹。

    def add_case(self, predicted_services: list[str], answer_service: str) -> None:
        """添加一个 case 的预测结果。

        只记录去重后的前五名服务；不足五名时用 ``False`` 填充，避免聚合时
        因列表长度不同而改变分母。
        """
        hits = [answer_service == s for s in predicted_services[:5]]
        while len(hits) < 5:
            hits.append(False)
        self._ac_hits.append(hits)

    def accuracy(self, k: int) -> float | None:
        """返回所有已添加 case 的 AC@k；尚无数据时返回 ``None``。"""
        if not self._ac_hits:
            return None
        return sum(1.0 for hits in self._ac_hits if any(hits[:k])) / len(self._ac_hits)

    def average(self, k: int = 5) -> float | None:
        """返回所有 case 的 Avg@k；尚无数据时返回 ``None``。"""
        if not self._ac_hits:
            return None
        total = 0.0
        for hits in self._ac_hits:
            total += sum(1.0 for i in range(k) if any(hits[: i + 1])) / k
        return total / len(self._ac_hits)

    @property
    def count(self) -> int:
        return len(self._ac_hits)
