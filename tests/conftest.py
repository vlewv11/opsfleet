from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field


class FakeLLM(BaseChatModel):
    responses: list[AIMessage] = Field(default_factory=list)
    verdict: dict[str, Any] = Field(default_factory=lambda: {"allowed": True, "reason": ""})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.responses.pop(0) if self.responses else AIMessage("Final answer.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda _: schema(**self.verdict))

    @property
    def _llm_type(self) -> str:
        return "fake"
