"""AC@k and Avg@5 evaluation metrics compatible with RCAEval scoring."""

from __future__ import annotations

from dataclasses import dataclass, field


def accuracy_at_k(predicted_services: list[str], answer: str, k: int) -> float:
    return 1.0 if answer in predicted_services[:k] else 0.0


def avg_at_k(predicted_services: list[str], answer: str, k: int = 5) -> float:
    return sum(accuracy_at_k(predicted_services, answer, i) for i in range(1, k + 1)) / k


@dataclass
class Evaluator:
    """Accumulates per-case results and computes aggregate scores."""

    _ac_hits: list[list[bool]] = field(default_factory=list)

    def add_case(self, predicted_services: list[str], answer_service: str) -> None:
        hits = [answer_service == s for s in predicted_services[:5]]
        while len(hits) < 5:
            hits.append(False)
        self._ac_hits.append(hits)

    def accuracy(self, k: int) -> float | None:
        if not self._ac_hits:
            return None
        return sum(1.0 for hits in self._ac_hits if any(hits[:k])) / len(self._ac_hits)

    def average(self, k: int = 5) -> float | None:
        if not self._ac_hits:
            return None
        total = 0.0
        for hits in self._ac_hits:
            total += sum(1.0 for i in range(k) if any(hits[: i + 1])) / k
        return total / len(self._ac_hits)

    @property
    def count(self) -> int:
        return len(self._ac_hits)
