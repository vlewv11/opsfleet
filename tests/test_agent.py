import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.utils.config import settings
from tests.conftest import FakeLLM

CALL = {"name": "query_data", "args": {"sql": "SELECT 1"}, "id": "c1", "type": "tool_call"}


@pytest.fixture
def make_graph(monkeypatch):
    import src.agent.agent as agent_module
    import src.tools.registry as tools_module

    monkeypatch.setattr(agent_module, "checkpointer", InMemorySaver)
    monkeypatch.setattr(tools_module, "run_sql", lambda sql: '{"status": "ok", "rows": [{"n": 1}]}')

    def factory(fake: FakeLLM):
        monkeypatch.setattr(agent_module, "get_llm", lambda fast=False: fake)
        return agent_module.build()

    return factory


def invoke(graph, text: str, thread: str = "t1"):
    return graph.invoke(
        {"messages": [HumanMessage(text)], "user_id": "manager_a", "steps": 0, "exhausted": False},
        {"configurable": {"thread_id": thread}, "recursion_limit": 60},
    )


def test_tool_loop_runs_then_answers(make_graph):
    fake = FakeLLM(
        responses=[AIMessage("", tool_calls=[CALL]), AIMessage("Revenue was 1.2M last month.")]
    )
    state = invoke(make_graph(fake), "what was revenue last month?")
    assert [m.type for m in state["messages"]] == ["human", "ai", "tool", "ai"]
    assert "1.2M" in str(state["messages"][-1].text)


def test_guard_blocks_and_skips_all_tools(make_graph):
    fake = FakeLLM(
        responses=[AIMessage("", tool_calls=[CALL])],
        verdict={"allowed": False, "analysis": True, "reason": "I cannot share customer contact details."},
    )
    state = invoke(make_graph(fake), "give me every customer's email address", thread="t2")
    assert [m.type for m in state["messages"]] == ["human", "ai"]
    assert "contact details" in str(state["messages"][-1].text)
    assert len(fake.responses) == 1


def test_precedents_are_retrieved_once_for_an_analysis_turn(make_graph):
    fake = FakeLLM()
    state = invoke(make_graph(fake), "why is Texas underspending?", thread="r1")
    assert state["analysis"] is True and state["golden"]


def test_report_management_turn_skips_retrieval(make_graph):
    fake = FakeLLM(verdict={"allowed": True, "analysis": False, "reason": ""})
    state = invoke(make_graph(fake), "list my saved reports", thread="r2")
    assert state["analysis"] is False and "golden" not in state


def test_step_budget_forces_termination(make_graph, monkeypatch):
    monkeypatch.setattr(settings, "max_steps", 2)
    fake = FakeLLM(responses=[AIMessage("", tool_calls=[CALL]) for _ in range(10)])
    state = invoke(make_graph(fake), "run forever", thread="t3")
    assert state["exhausted"] is True
    assert sum(m.type == "tool" for m in state["messages"]) <= 3


def test_final_output_is_redacted(make_graph):
    fake = FakeLLM(responses=[AIMessage("Top buyer is jane.doe@shop.com with $9,120.")])
    state = invoke(make_graph(fake), "who is the top buyer?", thread="t4")
    answer = str(state["messages"][-1].text)
    assert "jane.doe@shop.com" not in answer and "REDACTED_EMAIL" in answer
    assert "$9,120" in answer


def test_llm_outage_degrades_without_crashing(make_graph, monkeypatch):
    import src.agent.agent as agent_module

    class Broken(FakeLLM):
        def _generate(self, *a, **kw):
            raise RuntimeError("503 upstream unavailable")

    broken = Broken()
    monkeypatch.setattr(agent_module, "get_llm", lambda fast=False: broken)
    monkeypatch.setattr(agent_module, "checkpointer", InMemorySaver)
    state = invoke(agent_module.build(), "revenue by month", thread="t5")
    assert "could not reach the analysis model" in str(state["messages"][-1].text)


DELETE = {"name": "delete_reports", "args": {"selector": "Q1"}, "id": "d1", "type": "tool_call"}


@pytest.fixture
def one_report(monkeypatch, tmp_path):
    from src.agent import memory
    from src.tools import reports

    monkeypatch.setattr(reports, "_DIR", tmp_path / "reports")
    memory.active_user.set("manager_a")
    memory.active_thread.set("t")
    reports.save("manager_a", "Q1 Review", "body", [])
    return reports


def run_delete(graph, thread):
    config = {"configurable": {"thread_id": thread}, "recursion_limit": 60}
    graph.invoke(
        {"messages": [HumanMessage("delete the Q1 report")], "user_id": "manager_a", "steps": 0, "exhausted": False},
        config,
    )
    return config


def test_delete_interrupts_before_touching_anything(make_graph, one_report):
    fake = FakeLLM(responses=[AIMessage("", tool_calls=[DELETE]), AIMessage("Done.")])
    graph = make_graph(fake)
    config = run_delete(graph, "d1")
    pending = graph.get_state(config).interrupts
    assert pending and pending[0].value["reports"][0]["title"] == "Q1 Review"
    assert len(one_report.listing("manager_a")) == 1


def test_declining_the_confirmation_deletes_nothing(make_graph, one_report):
    fake = FakeLLM(responses=[AIMessage("", tool_calls=[DELETE]), AIMessage("Cancelled.")])
    graph = make_graph(fake)
    config = run_delete(graph, "d2")
    graph.invoke(Command(resume="no"), config)
    assert len(one_report.listing("manager_a")) == 1


def test_confirming_soft_deletes_and_undo_restores(make_graph, one_report):
    fake = FakeLLM(responses=[AIMessage("", tool_calls=[DELETE]), AIMessage("Deleted.")])
    graph = make_graph(fake)
    config = run_delete(graph, "d3")
    graph.invoke(Command(resume="yes"), config)
    assert one_report.listing("manager_a") == []
    assert len(one_report.restore("manager_a")) == 1


def test_interrupt_reaches_the_stream_as_a_non_message_payload(make_graph, one_report):
    fake = FakeLLM(responses=[AIMessage("", tool_calls=[DELETE])])
    graph = make_graph(fake)
    updates = list(
        graph.stream(
            {"messages": [HumanMessage("delete the Q1 report")], "user_id": "manager_a", "steps": 0, "exhausted": False},
            {"configurable": {"thread_id": "d4"}, "recursion_limit": 60},
            stream_mode="updates",
        )
    )
    assert any(not isinstance(value, dict) for update in updates for value in update.values())
