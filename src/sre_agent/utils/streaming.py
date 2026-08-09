from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class StreamEventType(StrEnum):
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    AI_MESSAGE = "ai_message"
    ANSWER_END = "answer_end"


class StreamEvent(BaseModel):
    event: StreamEventType
    data: dict[str, Any] = {}
