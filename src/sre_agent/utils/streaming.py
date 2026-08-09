"""引擎与终端展示层之间的流式事件协议。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class StreamEventType(StrEnum):
    """调查生命周期中可观察的事件类型。"""

    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    AI_MESSAGE = "ai_message"
    ANSWER_END = "answer_end"


class StreamEvent(BaseModel):
    """单个流事件；``data`` 的字段由对应事件类型定义。"""

    event: StreamEventType
    data: dict[str, Any] = {}
