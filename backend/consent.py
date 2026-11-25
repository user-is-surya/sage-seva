"""Action-bound consent.

Evolved from S.A.G.E's risk tiers (risk.py) and permission gate
(permissions.py): low-risk actions run, high-risk ones ask. New here:

* A spoken "yes" binds to nothing. So for a high-risk action the user must
  repeat a short code that is derived from the SHA-256 of the exact action
  (which form, which values). The code is explained aloud in the user's own
  language before it is asked for.
* At execution time the action is hashed again. If anything changed after
  consent (a field edited, a different form), the consent no longer matches
  and the action is refused.
* Speech often mishears digits, so the same code can be typed or tapped.
"""
from __future__ import annotations

import re
import secrets
import time

import audit

LOW, HIGH = "low", "high"
RISK = {
    "read_document": LOW,
    "check_requirements": LOW,
    "fill_form": LOW,        # fills fields on screen, nothing is sent
    "submit_form": HIGH,     # sends an application on the person's behalf
    "delete_data": HIGH,
}

_pending: dict[str, dict] = {}
TTL_S = 300

# Spoken digit words in the four supported languages -> digit
_DIGIT_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "సున్నా": 0, "ఒకటి": 1, "రెండు": 2, "మూడు": 3, "నాలుగు": 4, "ఐదు": 5, "ఆరు": 6, "ఏడు": 7, "ఎనిమిది": 8, "తొమ్మిది": 9,
    "பூஜ்ஜியம்": 0, "ஒன்று": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5, "ஆறு": 6, "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9,
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9,
}
_NATIVE_DIGITS = str.maketrans("౦౧౨౩౪౫౬౭౮౯०१२३४५६७८९௦௧௨௩௪௫௬௭௮௯", "012345678901234567890123456789")


def action_hash(action: str, payload: dict) -> str:
    return audit.sha({"action": action, "payload": payload})


def _code_from(h: str, nonce: str) -> str:
    n = int(audit.sha({"h": h, "n": nonce})[:8], 16)
    return f"{n % 9000 + 1000}"  # 4 digits, never starts with 0


def challenge(action: str, payload: dict, summary: dict) -> dict:
    """Create a consent challenge. summary = human-readable description for the UI/voice."""
    risk = RISK.get(action, HIGH)
    h = action_hash(action, payload)
    cid = secrets.token_hex(6)
    nonce = secrets.token_hex(8)
    code = _code_from(h, nonce) if risk == HIGH else None
    _pending[cid] = {"action": action, "hash": h, "code": code, "risk": risk, "t": time.time(), "used": False}
    audit.record("consent_requested", {"action": action, "risk": risk, "action_hash": h[:16], "summary": summary}, "agent")
    return {"challenge_id": cid, "risk": risk, "code": code, "action_hash": h}


def extract_digits(heard: str) -> str:
    s = (heard or "").translate(_NATIVE_DIGITS).lower()
    out = []
    for tok in re.findall(r"\d|[^\s\d,.\-]+", s):
        if tok.isdigit():
            out.append(tok)
        elif tok in _DIGIT_WORDS:
            out.append(str(_DIGIT_WORDS[tok]))
    return "".join(out)


def verify(cid: str, heard: str, action: str, payload: dict, method: str) -> dict:
    p = _pending.get(cid)
    if not p or p["used"]:
        return {"ok": False, "reason": "no_pending_consent"}
    if time.time() - p["t"] > TTL_S:
        return {"ok": False, "reason": "expired"}
    h = action_hash(action, payload)
    if h != p["hash"]:
        audit.record("consent_rejected", {"action": action, "reason": "action changed after consent"}, "system")
        return {"ok": False, "reason": "action_changed"}
    if p["risk"] == HIGH:
        got = extract_digits(heard)
        if p["code"] not in got:
            audit.record("consent_rejected", {"action": action, "reason": "code mismatch", "method": method}, "user")
            return {"ok": False, "reason": "code_mismatch", "heard_digits": got}
    p["used"] = True
    audit.record("consent_given", {"action": action, "action_hash": h[:16], "method": method}, "user")
    return {"ok": True, "action_hash": h}
