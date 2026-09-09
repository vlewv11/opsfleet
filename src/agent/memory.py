import json
import sqlite3
from contextvars import ContextVar

from langgraph.checkpoint.sqlite import SqliteSaver

from src.utils.config import settings
from src.utils.logger import event

_PREFS = settings.data_dir / "preferences.json"
DEFAULTS = {"format": "concise prose with a short table when numbers are compared", "depth": "executive summary first, then supporting detail"}


def checkpointer() -> SqliteSaver:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(settings.data_dir / "checkpoints.db", check_same_thread=False))


def _all() -> dict:
    return json.loads(_PREFS.read_text()) if _PREFS.exists() else {}


def preferences(user_id: str) -> dict:
    return DEFAULTS | _all().get(user_id, {})


def remember(user_id: str, key: str, value: str) -> dict:
    store = _all()
    store.setdefault(user_id, {})[key] = value
    _PREFS.parent.mkdir(parents=True, exist_ok=True)
    _PREFS.write_text(json.dumps(store, indent=2))
    event("preference_saved", user=user_id, key=key, value=value)
    return store[user_id]


active_user: ContextVar[str] = ContextVar("active_user", default="manager")
