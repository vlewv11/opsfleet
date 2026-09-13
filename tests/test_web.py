import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from src.agent import memory
from src.utils.config import settings
from src.web.app import app

CALL = {"name": "query_data", "args": {"sql": "SELECT 1"}, "id": "c1", "type": "tool_call"}


class FakeGraph:
    def __init__(self, seen, interrupts=(), final=AIMessage("Revenue was 1.2M.")):
        self.seen, self.interrupts, self.final, self.updates = seen, list(interrupts), final, []

    def stream(self, payload, config, stream_mode):
        self.seen.append((memory.active_user.get(), memory.active_thread.get(), payload))
        yield {"llm": {"messages": [AIMessage("", tool_calls=[CALL])]}}
        yield {"tools": {"messages": [ToolMessage('{"status": "ok", "row_count": 3, "repairs": 0}', tool_call_id="c1")]}}

    def get_state(self, config):
        return SimpleNamespace(interrupts=self.interrupts, values={"messages": [self.final]})

    def update_state(self, config, values):
        self.updates.append(values)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "app_user", "alex")
    monkeypatch.setattr(settings, "app_password", "")

    def use(graph):
        monkeypatch.setattr("src.web.app._graph", lambda: graph)
        return TestClient(app), graph.seen

    return use


def events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_a_turn_streams_tool_activity_then_the_answer(client):
    http, _ = client(FakeGraph([]))
    stream = events(http.post("/chat", json={"thread": "t1", "message": "what was revenue?"}))
    assert [e["kind"] for e in stream] == ["call", "result", "answer"]
    assert "query_data" in stream[0]["text"] and "3 rows" in stream[1]["text"]
    assert stream[2]["text"] == "Revenue was 1.2M." and stream[2]["trace"] != "-"


def test_the_client_cannot_choose_who_it_is(client):
    http, seen = client(FakeGraph([]))
    http.post("/chat", json={"user": "manager_b", "thread": "t2", "message": "hi"})
    assert seen[0][:2] == ("alex", "t2")


def test_a_password_shuts_every_door_until_you_sign_in(client, monkeypatch):
    monkeypatch.setattr(settings, "app_password", "3233")
    http, _ = client(FakeGraph([]))
    assert http.post("/chat", json={"thread": "t7", "message": "hi"}).status_code == 401
    assert http.get("/demo").status_code == 401
    assert http.post("/login", json={"user": "alex", "password": "wrong"}).status_code == 401
    assert http.get("/", follow_redirects=False).headers["location"] == "/login"
    assert "Sign in" in http.get("/login").text
    assert http.post("/login", json={"user": "alex", "password": "3233"}).json() == {"user": "alex"}
    assert http.get("/me").json()["user"] == "alex"
    assert http.get("/demo").status_code == 200
    assert http.get("/login", follow_redirects=False).headers["location"] == "/"


def test_repeated_wrong_passwords_lock_the_door(client, monkeypatch):
    monkeypatch.setattr(settings, "app_password", "3233")
    http, _ = client(FakeGraph([]))
    codes = [http.post("/login", json={"user": "alex", "password": "0000"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_a_pending_confirmation_is_sent_instead_of_an_answer(client):
    pending = SimpleNamespace(value={"action": "delete_reports", "reports": [{"id": "r1", "title": "Q1"}]})
    http, _ = client(FakeGraph([], interrupts=[pending]))
    stream = events(http.post("/chat", json={"thread": "t3", "message": "delete the Q1 report"}))
    assert stream[-1]["kind"] == "confirm" and stream[-1]["reports"][0]["title"] == "Q1"


def test_confirming_resumes_the_graph_rather_than_asking_again(client):
    http, seen = client(FakeGraph([]))
    http.post("/chat", json={"thread": "t4", "resume": "yes"})
    assert seen[0][2].resume == "yes"


def test_stopping_mid_tool_call_closes_the_call_off(client):
    graph = FakeGraph([], final=AIMessage("", tool_calls=[CALL]))
    http, _ = client(graph)
    assert http.post("/stop", json={"thread": "t5"}).json() == {"answered": 1}
    answered = graph.updates[0]["messages"][0]
    assert answered.tool_call_id == "c1" and "Cancelled" in answered.text


def test_stopping_a_settled_turn_changes_nothing(client):
    graph = FakeGraph([])
    http, _ = client(graph)
    assert http.post("/stop", json={"thread": "t6"}).json() == {"answered": 0}
    assert graph.updates == []


def test_the_page_and_demo_script_are_served(client):
    http, _ = client(FakeGraph([]))
    assert "Retail Analytics Assistant" in http.get("/").text
    assert any("Texas" in question for question in http.get("/demo").json()["demo"])
