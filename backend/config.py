"""Configuration and model discovery.

Model IDs change often, so nothing is hard-wired: each slot can be set in
.env, and anything left blank is picked at startup from the models the
user's own Gemini key can actually see.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_dd = os.getenv("SEVA_DATA_DIR", "").strip()
DATA_DIR = (Path(_dd) if Path(_dd).is_absolute() else ROOT / _dd) if _dd else ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
try:
    PORT = int(os.getenv("SEVA_PORT", "8000"))
except ValueError:
    PORT = 8000

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_TEXT_MODEL = os.getenv("SEVA_GROQ_TEXT_MODEL", "").strip() or "openai/gpt-oss-120b"
GROQ_STT_MODEL = os.getenv("SEVA_GROQ_STT_MODEL", "").strip() or "whisper-large-v3"
HEADED = os.getenv("SEVA_HEADED", "1").strip() != "0"

# Languages the app speaks. Adding one = one entry here + UI strings.
LANGS = {
    "te": {"name": "Telugu", "native": "తెలుగు", "edge_voice": "te-IN-ShrutiNeural"},
    "ta": {"name": "Tamil", "native": "தமிழ்", "edge_voice": "ta-IN-PallaviNeural"},
    "hi": {"name": "Hindi", "native": "हिंदी", "edge_voice": "hi-IN-SwaraNeural"},
    "en": {"name": "English", "native": "English", "edge_voice": "en-IN-NeerjaNeural"},
}


def _rank_text(name: str) -> tuple:
    """Prefer newest 'flash' (fast + free tier), avoid lite/preview/tts/live variants."""
    n = name.lower()
    bad = any(k in n for k in ("tts", "live", "image", "embedding", "transcribe", "audio", "thinking", "exp"))
    flash = "flash" in n
    lite = "lite" in n
    preview = "preview" in n
    nums = [float(p) for p in n.replace("gemini-", "").split("-")[0:1] if p.replace(".", "").isdigit()]
    ver = nums[0] if nums else 0.0
    return (not bad, flash, not lite, not preview, ver)


def _rank_tts(name: str) -> tuple:
    n = name.lower()
    nums = [float(p) for p in n.replace("gemini-", "").split("-")[0:1] if p.replace(".", "").isdigit()]
    return ("tts" in n, "flash" in n, not ("pro" in n), nums[0] if nums else 0.0)


@lru_cache(maxsize=1)
def gemini_models() -> dict:
    """Return {'text': id, 'tts': id|None, 'available': [...]} for this key."""
    text = os.getenv("SEVA_GEMINI_TEXT_MODEL", "").strip()
    tts = os.getenv("SEVA_GEMINI_TTS_MODEL", "").strip()
    available: list[str] = []
    if GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)
            for m in client.models.list():
                nm = (m.name or "").split("/")[-1]
                if nm.startswith("gemini"):
                    available.append(nm)
        except Exception as e:  # noqa: BLE001
            available = [f"ERROR listing models: {e}"]
    good = [a for a in available if not a.startswith("ERROR")]
    ranked = [a for a in sorted(good, key=_rank_text, reverse=True) if _rank_text(a)[0] and "flash" in a]
    chain = ([text] if text else []) + [a for a in ranked if a != text]
    if not text and good:
        text = (ranked or sorted(good, key=_rank_text, reverse=True))[0]
    if not tts:
        tts_c = [a for a in good if "tts" in a.lower()]
        tts = sorted(tts_c, key=_rank_tts, reverse=True)[0] if tts_c else ""
    chain = chain or [text or "gemini-flash-latest"]
    return {"text": chain[0], "chain": chain[:6], "tts": tts or None, "available": available}
