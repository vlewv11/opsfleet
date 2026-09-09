import json
import re
import uuid
from datetime import datetime, timezone

from src.utils.config import settings

_DIR = settings.data_dir / "reports"


def save(user_id: str, title: str, body: str, tags: list[str] | None = None) -> dict:
    _DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "report"
    record = {
        "id": f"{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6]}",
        "user_id": user_id,
        "title": title,
        "slug": slug,
        "tags": tags or [],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "body": body,
    }
    (_DIR / f"{record['id']}.json").write_text(json.dumps(record, indent=2))
    return record


def listing(user_id: str | None = None) -> list[dict]:
    records = []
    for path in sorted(_DIR.glob("*.json"), reverse=True):
        record = json.loads(path.read_text())
        if user_id is None or record["user_id"] == user_id:
            records.append(record)
    return records
