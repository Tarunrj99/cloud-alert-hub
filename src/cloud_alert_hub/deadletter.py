from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_dead_letter(event: dict[str, Any]) -> str:
    target = os.getenv("DEAD_LETTER_FILE_PATH", "/tmp/alerting-dead-letter.jsonl")
    path = Path(target)
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"recorded_at": datetime.now(timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")
    return str(path)
