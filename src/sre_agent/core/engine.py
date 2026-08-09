"""驱动大模型与诊断工具协作的核心执行引擎。"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from pydantic import BaseModel

from sre_agent.core.llm import LLM
from sre_agent.core.tool_executor import ToolExecutor
from sre_agent.utils.streaming import StreamEvent, StreamEventType


class EngineResult(BaseModel):
    """一次完整调查的汇总结果。

    ``messages`` 指向调用方传入的消息列表；引擎执行期间会把助手消息和工具
    结果追加到该列表，以便调用方继续进行多轮对话。
    """

    answer: str
    tool_calls: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    iterations: int = 0


class Engine:
    """执行“请求模型 -> 调用工具 -> 将结果交还模型”的迭代循环。"""

    def __init__(
        self,
        llm: LLM,
        tool_executor: ToolExecutor,
        max_steps: int = 30,
        max_output_lines: int = 2000,
    ):
        """保存运行依赖及安全上限。

        ``max_steps`` 防止模型持续请求工具而无法收敛；``max_output_lines``
        限制单个工具返回给模型的文本量，避免迅速耗尽上下文窗口。
        """

        self.llm = llm
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.max_output_lines = max_output_lines

    def call(self, messages: list[dict[str, Any]]) -> EngineResult:
        """以非流式方式运行调查，并将流事件聚合成一个结果对象。

        该方法与 :meth:`call_stream` 共用同一套执行逻辑，避免流式和非流式
        两种入口出现行为差异。
        """

        answer = ""
        all_tool_calls: list[dict[str, Any]] = []
        iterations = 0

        # 消费全部事件，只保留最终答案、迭代次数及每次工具调用的结果。
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
        """逐步产出调查事件，供 CLI 等调用方实时展示执行进度。

        此方法会原地扩展 ``messages``：先记录包含 ``tool_calls`` 的 assistant
        消息，再追加对应的 tool 消息。这是大多数支持工具调用的模型 API 所
        要求的对话顺序。
        """

        # 工具只需在循环开始前转换一次为 OpenAI function schema。
        tools = self.tool_executor.get_openai_tools()
        iteration = 0

        while iteration < self.max_steps:
            # 首轮读取用户问题；后续轮次还会读取刚刚追加的工具结果。
            response = self.llm.completion(messages, tools=tools if tools else None)

            # 即使模型同时请求工具，也保留它附带的解释文本供界面展示。
            if response.content:
                yield StreamEvent(
                    event=StreamEventType.AI_MESSAGE,
                    data={"content": response.content},
                )

            if not response.tool_calls:
                # 没有工具调用表示模型已经形成最终结论，本次调查正常收敛。
                yield StreamEvent(
                    event=StreamEventType.ANSWER_END,
                    data={
                        "content": response.content or "",
                        "iterations": iteration + 1,
                    },
                )
                return

            # 先通知界面所有即将开始的工具，再真正执行，便于及时显示状态。
            for tc in response.tool_calls:
                yield StreamEvent(
                    event=StreamEventType.TOOL_START,
                    data={
                        "tool_call_id": tc["id"],
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                )

            # 工具结果必须关联在声明 tool_calls 的 assistant 消息之后。
            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": response.tool_calls,
            })

            # 同一轮中的工具调用彼此独立，可以并行执行以缩短调查时间。
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

        # 达到上限时也使用 ANSWER_END，让所有调用方走统一的收尾路径。
        yield StreamEvent(
            event=StreamEventType.ANSWER_END,
            data={
                "content": f"已达最大步数 ({self.max_steps})，调查未完成。",
                "iterations": iteration,
            },
        )
