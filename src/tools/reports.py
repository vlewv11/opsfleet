import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from src.agent import memory
from src.utils.config import settings
from src.utils.logger import event

_DIR = settings.data_dir / "reports"
UNDO_WINDOW = timedelta(days=30)


def save(user_id: str, title: str, body: str, tags: list[str] | None = None) -> dict:
    _DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "report"
    record = {
        "id": f"{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6]}",
        "user_id": user_id,
        "thread": memory.active_thread.get(),
        "title": title,
        "slug": slug,
        "tags": tags or [],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "body": body,
    }
    (_DIR / f"{record['id']}.json").write_text(json.dumps(record, indent=2))
    return record


def _records() -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted(_DIR.glob("*.json"), reverse=True)]


def listing(user_id: str | None = None) -> list[dict]:
    return [
        record
        for record in _records()
        if not record.get("deleted_at") and user_id in (None, record["user_id"])
    ]


def resolve(user_id: str, selector: str, this_conversation: bool = False) -> list[dict]:
    scope = [
        record
        for record in listing(user_id)
        if not this_conversation or record.get("thread") == memory.active_thread.get()
    ]
    needle = selector.strip().lower()
    if needle in ("", "*", "all", "all reports", "everything"):
        return scope
    return [
        record
        for record in scope
        if needle == record["id"]
        or needle in record["title"].lower()
        or needle in record["body"].lower()
        or any(needle in tag.lower() for tag in record["tags"])
    ]


def delete(user_id: str, ids: list[str]) -> int:
    owned = sorted({record["id"] for record in listing(user_id)} & set(ids))
    batch = uuid.uuid4().hex[:8]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for report_id in owned:
        path = _DIR / f"{report_id}.json"
        path.write_text(
            json.dumps(
                json.loads(path.read_text()) | {"deleted_at": stamp, "delete_batch": batch},
                indent=2,
            )
        )
    event("reports_deleted", user=user_id, batch=batch, ids=owned, requested=len(ids))
    return len(owned)


def restore(user_id: str) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - UNDO_WINDOW
    deleted = [
        record
        for record in _records()
        if record["user_id"] == user_id
        and record.get("deleted_at")
        and datetime.fromisoformat(record["deleted_at"]) > cutoff
    ]
    if not deleted:
        return []
    batch = max(deleted, key=lambda record: record["deleted_at"])["delete_batch"]
    restored = [record for record in deleted if record["delete_batch"] == batch]
    for record in restored:
        (_DIR / f"{record['id']}.json").write_text(
            json.dumps(
                {k: v for k, v in record.items() if k not in ("deleted_at", "delete_batch")},
                indent=2,
            )
        )
    event("reports_restored", user=user_id, batch=batch, ids=[r["id"] for r in restored])
    return restored
