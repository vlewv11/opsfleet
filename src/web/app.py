import json
import secrets
import time
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel

from src.agent import memory
from src.agent.agent import build
from src.cli.chat import brief, outcome
from src.utils.config import ROOT, settings
from src.utils.logger import event, new_trace, trace_id

_PAGE = Path(__file__).parent / "index.html"
_LOGIN = Path(__file__).parent / "login.html"
_DEMO = ROOT / "docs" / "demo" / "demo-questions.txt"

LOCKOUT = (5, 60.0)

app = FastAPI(title="Retail Analytics Assistant")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or secrets.token_urlsafe(32),
    max_age=86_400,
    same_site="lax",
    https_only=False,
)

_failures: dict[str, tuple[int, float]] = {}


class Turn(BaseModel):
    thread: str
    message: str = ""
    resume: str | None = None


class Credentials(BaseModel):
    user: str
    password: str


def viewer(request: Request) -> str:
    if not settings.app_password:
        return settings.app_user
    if signed_in := request.session.get("user"):
        return signed_in
    raise HTTPException(status_code=401, detail="Sign in to use the assistant.")


@lru_cache(maxsize=1)
def _graph():
    return build()


def _sse(**payload) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _stream(turn: Turn, user: str):
    config = {"configurable": {"thread_id": f"{user}:{turn.thread}"}, "recursion_limit": 60}
    payload = (
        Command(resume=turn.resume)
        if turn.resume is not None
        else {"messages": [HumanMessage(turn.message)], "user_id": user, "steps": 0, "exhausted": False}
    )
    try:
        for update in _graph().stream(payload, config, stream_mode="updates"):
            for node_payload in update.values():
                if not isinstance(node_payload, dict):
                    continue
                for message in node_payload.get("messages", []) or []:
                    for call in getattr(message, "tool_calls", None) or []:
                        yield _sse(kind="call", text=f"{call['name']} {brief(call['args'])}")
                    if message.type == "tool":
                        yield _sse(kind="result", text=outcome(str(message.text)))
    except Exception as exc:
        event("web_stream_failed", error=str(exc)[:300])
        yield _sse(kind="error", text=str(exc), trace=trace_id.get())
        return

    state = _graph().get_state(config)
    if state.interrupts:
        yield _sse(kind="confirm", **state.interrupts[0].value)
        return
    answer = str(state.values["messages"][-1].text)
    event("answer", text=answer)
    yield _sse(kind="answer", text=answer, trace=trace_id.get())


@app.get("/login")
async def login_page(request: Request) -> Response:
    if not settings.app_password or request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return FileResponse(_LOGIN)


@app.post("/login")
async def login(request: Request, credentials: Credentials) -> dict:
    attempts, since = _failures.get(request.client.host, (0, 0.0))
    if attempts >= LOCKOUT[0] and time.monotonic() - since < LOCKOUT[1]:
        event("login_locked_out", host=request.client.host)
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a minute.")
    ok = secrets.compare_digest(credentials.user, settings.app_user) and secrets.compare_digest(
        credentials.password, settings.app_password
    )
    event("login", user=credentials.user[:40], ok=ok)
    if not ok:
        _failures[request.client.host] = (attempts + 1, time.monotonic())
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    _failures.pop(request.client.host, None)
    request.session["user"] = credentials.user
    return {"user": credentials.user}


@app.post("/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"user": None}


@app.get("/me")
async def me(user: str = Depends(viewer)) -> dict:
    return {"user": user, "login_required": bool(settings.app_password)}


@app.post("/chat")
async def chat(turn: Turn, user: str = Depends(viewer)) -> StreamingResponse:
    memory.active_user.set(user)
    memory.active_thread.set(turn.thread)
    new_trace()
    return StreamingResponse(_stream(turn, user), media_type="text/event-stream")


@app.post("/stop")
async def stop(turn: Turn, user: str = Depends(viewer)) -> dict:
    config = {"configurable": {"thread_id": f"{user}:{turn.thread}"}}
    messages = (_graph().get_state(config).values or {}).get("messages") or []
    calls = getattr(messages[-1], "tool_calls", None) or [] if messages else []
    if calls:
        _graph().update_state(
            config,
            {"messages": [ToolMessage("Cancelled by the user.", tool_call_id=call["id"]) for call in calls]},
        )
    event("web_stopped", answered=len(calls))
    return {"answered": len(calls)}


@app.get("/demo")
async def demo(user: str = Depends(viewer)) -> dict:
    return {"demo": [line for line in _DEMO.read_text().splitlines() if line.strip()] if _DEMO.exists() else []}


@app.get("/")
async def page(request: Request) -> Response:
    if settings.app_password and not request.session.get("user"):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(_PAGE)
