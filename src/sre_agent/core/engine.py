from __future__ import annotations

from collections.abc import Generator
from typing import Any

from pydantic import BaseModel

from sre_agent.core.llm import LLM
from sre_agent.core.tool_executor import ToolExecutor
from sre_agent.utils.streaming import StreamEvent, StreamEventType


class EngineResult(BaseModel):
    answer: str
    tool_calls: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    iterations: int = 0


class Engine:
    def __init__(
        self,
        llm: LLM,
        tool_executor: ToolExecutor,
        max_steps: int = 30,
        max_output_lines: int = 2000,
    ):
        self.llm = llm
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.max_output_lines = max_output_lines

    def call(self, messages: list[dict[str, Any]]) -> EngineResult:
        answer = ""
        all_tool_calls: list[dict[str, Any]] = []
        iterations = 0

        for event in self.call_stream(messages):
            if event.event == StreamEventType.ANSWER_END:
                answer = event.data.get("content", "")
                iterations = event.data.get("iterations", 0)
            elif event.event == StreamEventType.TOOL_RESULT:
                all_tool_calls.append(event.data)

        return EngineResult(
            answer=answer,
            tool_calls=all_tool_calls,
            messages=messages,
            iterations=iterations,
        )

    def call_stream(
        self, messages: list[dict[str, Any]]
    ) -> Generator[StreamEvent]:
        tools = self.tool_executor.get_openai_tools()
        iteration = 0

        while iteration < self.max_steps:
            response = self.llm.completion(messages, tools=tools if tools else None)

            if response.content:
                yield StreamEvent(
                    event=StreamEventType.AI_MESSAGE,
                    data={"content": response.content},
                )

            if not response.tool_calls:
                yield StreamEvent(
                    event=StreamEventType.ANSWER_END,
                    data={
                        "content": response.content or "",
                        "iterations": iteration + 1,
                    },
                )
                return

            for tc in response.tool_calls:
                yield StreamEvent(
                    event=StreamEventType.TOOL_START,
                    data={
                        "tool_call_id": tc["id"],
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                )

            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": response.tool_calls,
            })

            tool_results = self.tool_executor.execute_parallel(
                response.tool_calls, max_output_lines=self.max_output_lines
            )

            for tr in tool_results:
                yield StreamEvent(
                    event=StreamEventType.TOOL_RESULT,
                    data=tr,
                )
                messages.append(tr)

            iteration += 1

        yield StreamEvent(
            event=StreamEventType.ANSWER_END,
            data={
                "content": f"已达最大步数 ({self.max_steps})，调查未完成。",
                "iterations": iteration,
            },
        )
