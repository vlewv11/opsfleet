import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import date

from src.utils.config import settings

trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_sink = None


def new_trace() -> str:
    tid = uuid.uuid4().hex[:12]
    trace_id.set(tid)
    return tid


def event(name: str, **fields) -> None:
    global _sink
    if _sink is None:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        _sink = open(settings.log_dir / f"trace-{date.today()}.jsonl", "a", buffering=1)
    _sink.write(
        json.dumps(
            {"ts": time.time(), "trace": trace_id.get(), "event": name, **fields},
            default=str,
        )
        + "\n"
    )


def read_trace(tid: str) -> list[dict]:
    path = settings.log_dir / f"trace-{date.today()}.jsonl"
    if not path.exists():
        return []
    with open(path) as fh:
        return [e for line in fh if (e := json.loads(line))["trace"] == tid]


logging.getLogger("google.api_core").setLevel(logging.ERROR)
logging.getLogger("google.auth").setLevel(logging.ERROR)
