"""模型自维护的调查状态追踪。"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml


@dataclass
class Scratchpad:
    """调查过程中的结构化状态，由模型通过 update_scratchpad 工具调用维护。

    所有字段均为完整覆盖语义：模型每次调用时传入完整列表，引擎直接替换。
    """

    findings: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    ruled_out: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def update(
        self,
        findings: list[str] | None = None,
        hypotheses: list[str] | None = None,
        ruled_out: list[str] | None = None,
        next_steps: list[str] | None = None,
    ) -> None:
        """以完整覆盖语义更新字段；传入 None 的字段保持原值不变。"""

        if findings is not None:
            self.findings = findings
        if hypotheses is not None:
            self.hypotheses = hypotheses
        if ruled_out is not None:
            self.ruled_out = ruled_out
        if next_steps is not None:
            self.next_steps = next_steps

    def is_empty(self) -> bool:
        """所有字段均为空列表时返回 True。"""

        return not any([self.findings, self.hypotheses, self.ruled_out, self.next_steps])

    def to_yaml(self) -> str:
        """序列化为 YAML 字符串，注入 system prompt 时使用。"""

        data = {
            "findings": self.findings,
            "hypotheses": self.hypotheses,
            "ruled_out": self.ruled_out,
            "next_steps": self.next_steps,
        }
        return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
