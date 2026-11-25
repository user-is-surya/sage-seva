"""Tamper-evident, hash-chained audit log.

Evolved from S.A.G.E's audit_log.py (append-only JSONL, args redacted). New
here: every row carries the SHA-256 of the previous row, so editing,
deleting or reordering any past row breaks verification from that point on.
ID numbers are masked before they are ever written.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from config import DATA_DIR

LOG = DATA_DIR / "audit-chain.jsonl"
GENESIS = "0" * 64
_lock = threading.Lock()

_ID_RE = re.compile(r"\b(\d[\d ]{6,}\d)\b")


def mask(value):
    """Mask long digit runs (Aadhaar-style / phone / card numbers) to last 4."""
    if isinstance(value, str):
        def _m(m):
            d = re.sub(r"\D", "", m.group(1))
            return "X" * (len(d) - 4) + d[-4:]
        return _ID_RE.sub(_m, value)
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


def _canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(obj) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _rows(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"_corrupt": line})
    return out


def record(event: str, detail: dict | None = None, actor: str = "agent") -> dict:
    with _lock:
        rows = _rows()
        prev = rows[-1].get("hash", GENESIS) if rows else GENESIS
        body = {
            "seq": len(rows) + 1,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "actor": actor,
            "event": event,
            "detail": mask(detail or {}),
            "prev": prev,
        }
        body["hash"] = sha(body)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(_canon(body) + "\n")
        return body


def verify() -> dict:
    """Recompute the chain. Returns ok flag and the first broken seq, if any."""
    rows = _rows()
    prev = GENESIS
    for i, r in enumerate(rows, start=1):
        if "_corrupt" in r:
            return {"ok": False, "count": len(rows), "broken_at": i, "reason": "unreadable row"}
        claimed = r.get("hash")
        body = {k: v for k, v in r.items() if k != "hash"}
        if r.get("prev") != prev:
            return {"ok": False, "count": len(rows), "broken_at": i, "reason": "link to previous row broken"}
        if sha(body) != claimed:
            return {"ok": False, "count": len(rows), "broken_at": i, "reason": "row content changed after it was written"}
        prev = claimed
    return {"ok": True, "count": len(rows), "head": prev}


def entries(limit: int = 200) -> list[dict]:
    return _rows()[-limit:]


def reset() -> None:
    with _lock:
        if LOG.exists():
            LOG.rename(LOG.with_suffix(f".{int(time.time())}.bak"))
