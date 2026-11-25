"""Model access with failover: Gemini first, Groq / edge-tts as fallbacks.

Pattern carried over from S.A.G.E's providers.py: per-task provider order,
and a provider that fails (quota, outage) is put on a short cooldown so the
next call goes straight to the fallback instead of paying the failure again.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
import wave

import config

_cooldown: dict[str, float] = {}
COOLDOWN_S = 90
last_used: dict[str, str] = {}  # task -> provider/model actually used (shown in UI)


def _ok(p: str) -> bool:
    return time.time() >= _cooldown.get(p, 0)


def _fail(p: str) -> None:
    _cooldown[p] = time.time() + COOLDOWN_S


_clients: dict = {}


def _gemini():
    # One long-lived client: a temporary one can be garbage-collected (and its
    # HTTP session closed) while its request is still in flight.
    if "gemini" not in _clients:
        from google import genai
        from google.genai import types

        # 25 s per attempt: an overloaded model should fail over, not hang the demo
        _clients["gemini"] = genai.Client(api_key=config.GEMINI_API_KEY,
                                          http_options=types.HttpOptions(timeout=25_000))
    return _clients["gemini"]


def _groq():
    if "groq" not in _clients:
        from groq import Groq

        _clients["groq"] = Groq(api_key=config.GROQ_API_KEY)
    return _clients["groq"]


def _gemini_chain() -> list[str]:
    """Gemini models to try in order, skipping ones on cooldown (overloaded / over quota)."""
    if not config.GEMINI_API_KEY:
        return []
    return [m for m in config.gemini_models()["chain"] if _ok("g:" + m)]


def _fail_model(model: str, e: Exception) -> None:
    s = str(e)
    if any(k in s.lower() for k in ("429", "resource_exhausted", "503", "unavailable", "500", "404", "not_found",
                                     "timeout", "timed out", "deadline")):
        _fail("g:" + model)


def _parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


# ---------------------------------------------------------------- text / JSON
def ask_json(system: str, user: str, images: list[tuple[bytes, str]] | None = None, temperature: float = 0.2) -> dict:
    """Return a JSON object. Images force Gemini (Groq path is text-only)."""
    errors = []
    for model in _gemini_chain():
        try:
            from google.genai import types

            parts = [types.Part.from_bytes(data=b, mime_type=mt) for b, mt in (images or [])]
            parts.append(types.Part.from_text(text=user))
            resp = _gemini().models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
            last_used["text"] = f"gemini:{model}"
            return _parse_json(resp.text)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{model}: {str(e)[:160]}")
            _fail_model(model, e)
    if images:
        raise RuntimeError("Vision needs Gemini, which is unavailable: " + "; ".join(errors))
    if config.GROQ_API_KEY and _ok("groq"):
        try:
            resp = _groq().chat.completions.create(
                model=config.GROQ_TEXT_MODEL,
                messages=[{"role": "system", "content": system + "\nReply with one JSON object only."},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            last_used["text"] = f"groq:{config.GROQ_TEXT_MODEL}"
            return _parse_json(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001
            errors.append(f"groq: {e}")
            _fail("groq")
    raise RuntimeError("No language model available: " + "; ".join(errors))


# ---------------------------------------------------------------- speech in
STT_PROMPT = (
    "Transcribe this speech exactly as spoken. The speaker may mix {lang} with English "
    "(code-mixing is normal). Write {lang} words in {lang} script and English words in "
    "Latin script. Write numbers as digits. Output only the transcript, nothing else."
)


def transcribe(audio: bytes, mime: str, lang: str) -> dict:
    lname = config.LANGS.get(lang, config.LANGS["en"])["name"]
    errors = []
    for model in _gemini_chain()[:3]:
        try:
            from google.genai import types

            resp = _gemini().models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=[
                    types.Part.from_bytes(data=audio, mime_type=mime or "audio/webm"),
                    types.Part.from_text(text=STT_PROMPT.format(lang=lname)),
                ])],
                config=types.GenerateContentConfig(temperature=0.0),
            )
            last_used["stt"] = f"gemini:{model}"
            return {"text": (resp.text or "").strip(), "engine": last_used["stt"]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{model}: {str(e)[:160]}")
            _fail_model(model, e)
    if config.GROQ_API_KEY and _ok("groq-stt"):
        try:
            ext = "webm" if "webm" in (mime or "") else "wav"
            r = _groq().audio.transcriptions.create(
                file=(f"audio.{ext}", audio),
                model=config.GROQ_STT_MODEL,
                language=lang if lang in config.LANGS else None,
                temperature=0.0,
            )
            last_used["stt"] = f"groq:{config.GROQ_STT_MODEL}"
            return {"text": (r.text or "").strip(), "engine": last_used["stt"]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"groq: {e}")
            _fail("groq-stt")
    raise RuntimeError("No speech-to-text available: " + "; ".join(errors))


# ---------------------------------------------------------------- speech out
TTS_DIR = config.DATA_DIR / "tts"
TTS_DIR.mkdir(exist_ok=True)


def _pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _gemini_tts(text: str, lang: str) -> bytes:
    from google.genai import types

    model = config.gemini_models()["tts"]
    if not model:
        raise RuntimeError("no Gemini TTS model visible to this key")
    lname = config.LANGS.get(lang, config.LANGS["en"])["name"]
    resp = _gemini().models.generate_content(
        model=model,
        contents=f"Say this clearly and warmly in {lname}, at a calm pace: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
        ),
    )
    data = resp.candidates[0].content.parts[0].inline_data.data
    last_used["tts"] = f"gemini:{model}"
    return _pcm_to_wav(data)


async def _edge_tts(text: str, lang: str) -> bytes:
    import edge_tts

    voice = config.LANGS.get(lang, config.LANGS["en"])["edge_voice"]
    out = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            out.extend(chunk["data"])
    if not out:
        raise RuntimeError("edge-tts returned no audio")
    last_used["tts"] = f"edge-tts:{voice}"
    return bytes(out)


async def speak(text: str, lang: str, prefer: str = "gemini") -> tuple[bytes, str]:
    """Return (audio bytes, mime). Cached on disk by (text, lang)."""
    key = hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()
    for ext, mime in (("wav", "audio/wav"), ("mp3", "audio/mpeg")):
        p = TTS_DIR / f"{key}.{ext}"
        if p.exists():
            return p.read_bytes(), mime
    errors = []
    order = ["gemini", "edge"] if prefer == "gemini" else ["edge", "gemini"]
    for prov in order:
        if prov == "gemini" and config.GEMINI_API_KEY and _ok("gemini-tts"):
            try:
                audio = await asyncio.to_thread(_gemini_tts, text, lang)
                (TTS_DIR / f"{key}.wav").write_bytes(audio)
                return audio, "audio/wav"
            except Exception as e:  # noqa: BLE001
                errors.append(f"gemini-tts: {e}")
                _fail("gemini-tts")
        if prov == "edge" and _ok("edge"):
            try:
                audio = await asyncio.wait_for(_edge_tts(text, lang), timeout=20)
                (TTS_DIR / f"{key}.mp3").write_bytes(audio)
                return audio, "audio/mpeg"
            except Exception as e:  # noqa: BLE001
                errors.append(f"edge-tts: {e}")
                _fail("edge")
    raise RuntimeError("; ".join(errors))
