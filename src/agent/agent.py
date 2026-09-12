from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from src.agent.memory import checkpointer
from src.agent.state import AgentState
from src.agent.llm_client import get_llm
from src.prompts import agent_prompts, system_prompts
from src.tools import golden
from src.tools.registry import TOOLS
from src.utils.config import settings
from src.utils.logger import event
from src.utils.pii import scrub

REFUSAL = "I can only help with analysis of our retail data. {reason}"


class Verdict(BaseModel):
    allowed: bool = Field(description="True unless the message matches a BLOCK rule.")
    reason: str = Field(description="One plain sentence for the manager. Empty when allowed.")


def _guard(state: AgentState) -> dict:
    recent = "\n".join(
        f"{m.type}: {str(m.text)[:400]}" for m in state["messages"][-4:] if m.type in ("human", "ai")
    )
    try:
        verdict = (
            get_llm(fast=True)
            .with_structured_output(Verdict)
            .invoke([SystemMessage(agent_prompts.GUARD), HumanMessage(recent)])
        )
    except Exception as exc:
        event("guard_unavailable", error=str(exc)[:200])
        return {}
    event("guard", allowed=verdict.allowed, reason=verdict.reason[:200])
    if verdict.allowed:
        return {}
    return {"messages": [AIMessage(REFUSAL.format(reason=verdict.reason))], "exhausted": True}


def _retrieve(state: AgentState) -> dict:
    question = next(
        (str(m.text) for m in reversed(state["messages"]) if m.type == "human"), ""
    )
    return {"golden": golden.render(golden.search(question))}


def _llm(state: AgentState) -> dict:
    try:
        model = get_llm()
        if not state.get("exhausted"):
            model = model.bind_tools(TOOLS)
        system = system_prompts.build(state["user_id"], state.get("golden", ""))
        response = model.invoke([SystemMessage(system)] + state["messages"])
    except Exception as exc:
        event("llm_unavailable", error=str(exc)[:300])
        return {
            "messages": [
                AIMessage(
                    "I could not reach the analysis model just now, so I have not answered your "
                    "question. Nothing was lost — ask me again in a moment."
                )
            ],
            "exhausted": True,
        }
    return {"messages": [response], "steps": state.get("steps", 0) + 1}


def _budget(state: AgentState) -> dict:
    last = state["messages"][-1]
    event("budget_exhausted", steps=state.get("steps", 0))
    return {
        "exhausted": True,
        "messages": [
            ToolMessage(
                "Step budget for this question is spent. Answer now using what you already have, "
                "and tell the user which part you could not complete.",
                tool_call_id=call["id"],
            )
            for call in last.tool_calls
        ],
    }


def _redact(state: AgentState) -> dict:
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        return {}
    original = str(last.text)
    clean = scrub(original)
    dangling = bool(getattr(last, "tool_calls", None))
    if clean == original and not dangling:
        return {}
    if dangling:
        event("dangling_tool_calls_dropped", count=len(last.tool_calls))
        clean = clean.strip() or (
            "I ran out of the step budget for this question before I could finish. "
            "Ask me a narrower version and I will get there."
        )
    if clean != original:
        event("output_redacted")
    return {"messages": [AIMessage(clean, id=last.id)]}


def _route(state: AgentState) -> str:
    last = state["messages"][-1]
    if state.get("exhausted") or not getattr(last, "tool_calls", None):
        return "redact"
    return "budget" if state.get("steps", 0) >= settings.max_steps else "tools"


def build():
    graph = StateGraph(AgentState)
    graph.add_node("guard", _guard)
    graph.add_node("retrieve", _retrieve)
    graph.add_node("llm", _llm)
    graph.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
    graph.add_node("budget", _budget)
    graph.add_node("redact", _redact)

    graph.add_edge(START, "guard")
    graph.add_conditional_edges(
        "guard", lambda s: "redact" if s.get("exhausted") else "retrieve", ["redact", "retrieve"]
    )
    graph.add_edge("retrieve", "llm")
    graph.add_conditional_edges("llm", _route, ["tools", "budget", "redact"])
    graph.add_edge("tools", "llm")
    graph.add_edge("budget", "llm")
    graph.add_edge("redact", END)
    return graph.compile(checkpointer=checkpointer())
