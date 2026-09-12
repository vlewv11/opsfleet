import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import date

from src.utils.config import settings

trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_sink: tuple[date, object] | None = None


def new_trace() -> str:
    tid = uuid.uuid4().hex[:12]
    trace_id.set(tid)
    return tid


def event(name: str, **fields) -> None:
    global _sink
    today = date.today()
    if _sink is None or _sink[0] != today:
        if _sink is not None:
            _sink[1].close()
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        _sink = (today, open(settings.log_dir / f"trace-{today}.jsonl", "a", buffering=1))
    _sink[1].write(
        json.dumps(
            {"ts": time.time(), "trace": trace_id.get(), "event": name, **fields},
            default=str,
        )
        + "\n"
    )


def read_trace(tid: str) -> list[dict]:
    return [
        entry
        for path in sorted(settings.log_dir.glob("trace-*.jsonl"))
        for line in open(path)
        if (entry := json.loads(line))["trace"] == tid
    ]


logging.getLogger().addHandler(logging.NullHandler())
logging.getLogger("google.api_core").setLevel(logging.ERROR)
logging.getLogger("google.auth").setLevel(logging.ERROR)
