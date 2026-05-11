from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping


SENSITIVE_KEYS = {
    "password",
    "confirmpassword",
    "newpassword",
    "oldpassword",
    "token",
    "authorization",
}


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).replace("_", "").lower() in SENSITIVE_KEYS:
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class AuditLogger:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else None

    def api_error(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        response_body: str,
        payload: Any = None,
    ) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": int(time.time()),
            "event": "api_error",
            "method": method,
            "path": path,
            "status_code": status_code,
            "response_body": response_body[:4000],
            "payload": redact(payload),
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            stream.write("\n")

