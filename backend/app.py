"""SAGE Seva API server.

Run:  python backend/app.py   (serves API, mock portal and built frontend on :8000)
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import ai  # noqa: E402
import audit  # noqa: E402
import browser  # noqa: E402
import config  # noqa: E402
import consent  # noqa: E402
import name_guard  # noqa: E402

ROOT = config.ROOT
SKILLS = ROOT / "skills"
PORTAL = ROOT / "portal"
DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="SAGE Seva")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def load_skill(sid: str) -> dict:
    p = SKILLS / sid / "skill.json"
    if not p.exists():
        raise HTTPException(404, f"unknown skill {sid}")
    s = json.loads(p.read_text(encoding="utf-8"))
    s["_knowledge"] = (SKILLS / sid / s.get("knowledge", "knowledge.md")).read_text(encoding="utf-8")
    return s


def lang_name(lang: str) -> str:
    return config.LANGS.get(lang, config.LANGS["en"])["name"]


def _plain(e: Exception | str | None) -> str:
    """Turn an internal exception into a short plain-language sentence (no stack traces, no keys)."""
    s = str(e or "")
    low = s.lower()
    if any(k in low for k in ("429", "resource_exhausted", "quota")):
        return "The AI service is busy right now (quota reached). Please try again in a minute."
    if any(k in low for k in ("503", "unavailable", "overloaded", "timeout", "timed out", "deadline")):
        return "The AI service is overloaded right now. Please try again in a few seconds."
    if "no language model" in low or "vision needs gemini" in low:
        return "No AI model is reachable right now. Please check the internet connection and try again."
    if "speech-to-text" in low:
        return "I could not understand the recording. Please try again or type instead."
    if "has been closed" in low or "browser" in low or "playwright" in low:
        return "The form window was closed or stopped responding. Please press Fill the form again."
    s = re.sub(r"(?i)(api[_-]?key|key)=\S+", "key=***", s)
    return (s.splitlines()[0] if s else "Something went wrong. Please try again.")[:240]


def err(e: Exception | str | None, status: int = 502):
    return JSONResponse({"error": _plain(e)}, status_code=status)


@app.exception_handler(HTTPException)
async def _http_exc(_req: Request, exc: HTTPException):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def _any_exc(_req: Request, exc: Exception):
    return JSONResponse({"error": _plain(exc)}, status_code=500)


async def _body(req: Request) -> dict:
    try:
        b = await req.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "The request was not valid JSON.")
    if not isinstance(b, dict):
        raise HTTPException(400, "The request body must be a JSON object.")
    return b


def _lang(b: dict) -> str:
    lang = str(b.get("lang") or "en")
    return lang if lang in config.LANGS else "en"


# ------------------------------------------------------------------ health
@app.get("/api/health")
def health():
    m = config.gemini_models()
    return {
        "gemini_key": bool(config.GEMINI_API_KEY), "groq_key": bool(config.GROQ_API_KEY),
        "models": {"text": m["text"], "tts": m["tts"], "groq_text": config.GROQ_TEXT_MODEL, "groq_stt": config.GROQ_STT_MODEL},
        "gemini_models_visible": len(m["available"]), "last_used": ai.last_used, "langs": config.LANGS,
        "audit": audit.verify(),
    }


@app.get("/api/skills/{sid}")
def skill(sid: str):
    s = load_skill(sid)
    s.pop("_knowledge", None)
    return s


# ------------------------------------------------------------------ speech
@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), lang: str = Form("te")):
    data = await audio.read()
    if len(data) < 800:  # a click, not speech
        return JSONResponse({"error": "The recording was too short. Hold the button and speak, or type instead."},
                            status_code=400)
    try:
        return await asyncio.to_thread(ai.transcribe, data, audio.content_type or "audio/webm", lang)
    except Exception as e:  # noqa: BLE001
        return err(e)


@app.post("/api/tts")
async def tts(req: Request):
    body = await _body(req)
    text, lang = str(body.get("text") or "").strip(), _lang(body)
    if not text:
        raise HTTPException(400, "empty text")
    try:
        audio, mime = await ai.speak(text[:1200], lang, prefer=body.get("prefer", "gemini"))
        return Response(audio, media_type=mime, headers={"X-TTS-Engine": ai.last_used.get("tts", "")})
    except Exception as e:  # noqa: BLE001
        return err(e, 503)


# ------------------------------------------------------------------ agent turn
AGENT_SYSTEM = """You are SAGE Seva, a patient assistant that helps a citizen-service operator or a first-time
user apply for government e-services. The user speaks {lang}, often mixed with English.
Service in progress: {service}.
Current state: {state}

Classify the user's utterance and extract details. Return JSON:
{{
 "intent": one of ["start_service","give_details","ask_question","fill_form","submit","provide_code","cancel","smalltalk"],
 "slots": {{ {slots} }}   // only slots actually mentioned; omit others
 "question": "<the user's question in English, if intent is ask_question, else empty>",
 "digits": "<any code digits the user spoke, as digits only, else empty>",
 "reply": "<ONE short sentence in {lang} script, at most 12 words, saying the single next step>"
}}
Rules:
- The reply is spoken aloud: ONE sentence, at most 12 words, no lists, no greetings, no repetition of what the
  user said, no explanations. Write the reply in {lang} SCRIPT even if the user typed in Latin letters.
  Number words: lakh=100000, iravai/irupathu/bees=20; 'oka lakh iravai velu' = 120000. Never state any fact (name, amount, date, rule) that is not in the utterance or state.
- Never invent personal details. Convert spoken amounts to plain integers (e.g. 'oka lakh iravai velu' -> 120000).
- Slot values go into an English-language government form: write them in ENGLISH (e.g. 'రైతు' -> 'Farmer',
  'बेटी की scholarship' -> 'Scholarship for daughter'), with a capital first letter.
- The app's steps are only: read document photos -> check names -> collect details -> fill the form and read it back
  -> ask for a spoken consent code -> submit -> show an application number. Never mention OTPs, payments, SMS,
  visits to an office or any step not in this list.
- If details are still missing (occupation, annual income, purpose), ask for the missing one. If documents are not
  added yet, ask the user to show their document photos. If everything is ready, offer to fill the form.
- If the user asks to submit, intent is "submit" (the app will ask for a consent code separately).
"""


@app.post("/api/agent")
async def agent(req: Request):
    b = await _body(req)
    lang = _lang(b)
    s = load_skill(b.get("skill", "income_certificate"))
    text = str(b.get("text") or "").strip()
    if not text:
        return {"intent": "smalltalk", "slots": {}, "question": "", "digits": "",
                "reply": AGENT_MSG[lang]["empty"], "engine": "rule"}
    slots = ", ".join(f'"{k}": "<{v}>"' for k, v in s["voice_slots"].items())
    system = AGENT_SYSTEM.format(lang=lang_name(lang), service=s["title"]["en"],
                                 state=json.dumps(b.get("state", {}), ensure_ascii=False)[:1500], slots=slots)
    try:
        out = await asyncio.to_thread(ai.ask_json, system, text[:1000], None, 0.1)
    except Exception as e:  # noqa: BLE001
        return err(e)
    out = _clean_agent(out, s, lang)
    audit.record("voice_command", {"intent": out["intent"], "slots": out["slots"], "lang": lang}, "user")
    out["engine"] = ai.last_used.get("text")
    return out


INTENTS = {"start_service", "give_details", "ask_question", "fill_form", "submit", "provide_code", "cancel", "smalltalk"}
AGENT_MSG = {
    "te": {"empty": "నేను ఏమీ వినలేదు, దయచేసి మళ్ళీ చెప్పండి.", "fallback": "సరే, తర్వాతి దశకు వెళ్దాం."},
    "ta": {"empty": "நான் எதுவும் கேட்கவில்லை, மீண்டும் சொல்லுங்கள்.", "fallback": "சரி, அடுத்த படிக்குச் செல்வோம்."},
    "hi": {"empty": "मुझे कुछ सुनाई नहीं दिया, कृपया फिर से बोलिए।", "fallback": "ठीक है, अगले कदम पर चलते हैं।"},
    "en": {"empty": "I did not hear anything, please say it again.", "fallback": "Okay, let's go to the next step."},
}
_BANNED = re.compile(r"(?i)\botp\b|payments?\b|\bpay\b|\bfees?\b|\bsms\b|office|ఓటీపీ|ఆఫీసు|కార్యాలయ|ओटीपी|कार्यालय|दफ़्तर|ஓடிபி|அலுவலக")


def _short(reply: str, lang: str, max_words: int = 15) -> str:
    reply = re.sub(r"\s+", " ", str(reply or "")).strip()
    if not reply or _BANNED.search(reply):
        return AGENT_MSG[lang]["fallback"]
    # keep only the first sentence
    m = re.match(r"^(.+?[.!?।]|.+?\?)(\s|$)", reply)
    if m:
        reply = m.group(1).strip()
    words = reply.split()
    if len(words) > max_words:
        reply = " ".join(words[:max_words]).rstrip(",;:") + ("।" if lang == "hi" else ".")
    return reply


def _clean_agent(out, s: dict, lang: str) -> dict:
    if not isinstance(out, dict):
        out = {}
    intent = out.get("intent") if out.get("intent") in INTENTS else "smalltalk"
    raw_slots = out.get("slots") if isinstance(out.get("slots"), dict) else {}
    slots = {k: str(v).strip() for k, v in raw_slots.items()
             if k in s["voice_slots"] and v not in (None, "") and str(v).strip() and not str(v).startswith("<")}
    if "annual_income" in slots:
        digits = re.sub(r"[^\d]", "", slots["annual_income"].split(".")[0])
        if digits:
            slots["annual_income"] = digits
        else:
            slots.pop("annual_income")
    return {"intent": intent, "slots": slots, "question": str(out.get("question") or ""),
            "digits": re.sub(r"\D", "", str(out.get("digits") or "")), "reply": _short(out.get("reply"), lang)}


# ------------------------------------------------------------------ documents
EXTRACT_SYSTEM = """You read photos of Indian identity and household documents. Extract fields exactly as printed.
Return JSON:
{"doc_type": one of ["identity_card","ration_card","voter_id","other"],
 "label": "<short English name of the document>",
 "name_native": "<holder name in Indic script if printed, else empty>",
 "name_latin": "<holder name in English letters EXACTLY as printed, keep initials and spacing>",
 "father_name_native": "", "father_name_latin": "<father/spouse name in English letters as printed>",
 "dob": "<DD/MM/YYYY or empty>", "gender": "<Male/Female/Other or empty>",
 "address": "<address in English letters as printed, or transliterated if only Indic script>",
 "district": "", "state": "",
 "id_number": "<document number as printed>",
 "confidence_notes": "<anything hard to read>"}
Do not guess fields that are not printed; leave them empty."""


@app.post("/api/extract")
async def extract(image: UploadFile = File(...), lang: str = Form("te")):
    data = await image.read()
    # Same photo -> same result: cache by content hash (saves quota, survives model overload)
    import hashlib
    cache = config.DATA_DIR / "extract_cache"
    cache.mkdir(exist_ok=True)
    cfile = cache / (hashlib.sha256(data).hexdigest() + ".json")
    out = None
    if cfile.exists():
        out = json.loads(cfile.read_text(encoding="utf-8"))
    else:
        last = None
        for attempt in range(2):  # one retry after a short pause if every model was busy
            try:
                out = await asyncio.to_thread(ai.ask_json, EXTRACT_SYSTEM, "Extract the fields from this document.",
                                              [(data, image.content_type or "image/png")])
                break
            except Exception as e:  # noqa: BLE001
                last = e
                ai._cooldown.clear()
                await asyncio.sleep(2)
        if out is None:
            return err(last)
    if "id_last4" not in out:
        digits = re.sub(r"\D", "", out.get("id_number", "") or "")
        out["id_last4"] = digits[-4:] if len(digits) >= 4 else ""
    out["id_number"] = audit.mask(out.get("id_number", ""))  # never keep full ID numbers
    if out.get("name_latin") and not cfile.exists():
        cfile.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")  # masked before caching
    out["engine"] = ai.last_used.get("text")
    audit.record("document_read", {"doc_type": out.get("doc_type"), "name_latin": out.get("name_latin"),
                                   "file": image.filename}, "agent")
    return out


@app.post("/api/reconcile")
async def reconcile(req: Request):
    b = await _body(req)
    lang = _lang(b)
    docs = [d for d in (b.get("docs") or []) if isinstance(d, dict)]
    name = name_guard.reconcile(docs, "name_latin", lang)
    father = name_guard.reconcile(docs, "father_name_latin", lang)
    dob = name_guard.compare_simple([(d.get("label", ""), d.get("dob", "")) for d in docs])
    audit.record("name_check", {"name_status": name["status"], "canonical": name.get("canonical"),
                                "father_status": father["status"], "dob_consistent": dob["consistent"]}, "agent")
    return {"name": name, "father": father, "dob": dob, "spoken": guard_message(name, lang),
            "spell_spoken": spell_message(name, lang)}


# One short sentence each: the letter-by-letter spell-back lives in SPELL_MSG and is only
# spoken when the user presses Play.
GUARD_MSG = {
    "te": {"consistent": "మీ పత్రాలన్నింటిలో పేరు ఒకేలా ఉంది.",
           "variant": "పేరు స్పెల్లింగ్ వేరుగా ఉంది, {src} లో ఉన్నట్లే రాస్తాను.",
           "needs_check": "పేర్లు కొంచెం భిన్నంగా ఉన్నాయి, దయచేసి తనిఖీ చేయండి.",
           "conflict": "ఒక పత్రంలో పూర్తిగా వేరే పేరు ఉంది, దయచేసి తనిఖీ చేయండి."},
    "ta": {"consistent": "உங்கள் எல்லா ஆவணங்களிலும் பெயர் ஒன்றாக உள்ளது.",
           "variant": "பெயர் எழுத்துக்கூட்டல் வேறுபடுகிறது, {src} இல் உள்ளபடி எழுதுவேன்.",
           "needs_check": "பெயர்கள் சற்று வேறுபடுகின்றன, தயவுசெய்து சரிபார்க்கவும்.",
           "conflict": "ஒரு ஆவணத்தில் முற்றிலும் வேறு பெயர் உள்ளது, சரிபார்க்கவும்."},
    "hi": {"consistent": "आपके सभी दस्तावेज़ों में नाम एक जैसा है।",
           "variant": "नाम की स्पेलिंग अलग है, मैं {src} के अनुसार लिखूँगा।",
           "needs_check": "नाम थोड़े अलग हैं, कृपया जाँच लें।",
           "conflict": "एक दस्तावेज़ में बिल्कुल अलग नाम है, कृपया जाँचें।"},
    "en": {"consistent": "The name matches on all your documents.",
           "variant": "The spelling differs; I will use the one on the {src}.",
           "needs_check": "The names differ slightly, please check them.",
           "conflict": "One document has a completely different name, please check it."},
}
SPELL_MSG = {
    "te": "ఫారంలో పేరు అక్షరాలు: {spell}.",
    "ta": "படிவத்தில் பெயரின் எழுத்துகள்: {spell}.",
    "hi": "फ़ॉर्म में नाम के अक्षर: {spell}।",
    "en": "The name on the form is spelled: {spell}.",
}


def guard_message(name: dict, lang: str) -> str:
    t = GUARD_MSG.get(lang, GUARD_MSG["en"]).get(name.get("status", ""))
    return t.format(src=name.get("canonical_source", "") or "ID") if t else ""


def spell_message(name: dict, lang: str) -> str:
    spell = name.get("spell_back") or ""
    return SPELL_MSG.get(lang, SPELL_MSG["en"]).format(spell=spell) if spell else ""


# ------------------------------------------------------------------ grounded Q&A (RAG over the skill pack)
def _sections(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## ", md, flags=re.M)
    head = parts[0]
    out = [("Overview", head)]
    for p in parts[1:]:
        title, _, body = p.partition("\n")
        out.append((title.strip(), body.strip()))
    return out


def _retrieve(md: str, query: str, k: int = 3) -> list[tuple[str, str]]:
    q = set(re.findall(r"[a-z]{3,}", query.lower()))
    scored = []
    for title, body in _sections(md):
        words = set(re.findall(r"[a-z]{3,}", (title + " " + body).lower()))
        scored.append((len(q & words) + (2 if q & set(title.lower().split()) else 0), title, body))
    scored.sort(key=lambda x: -x[0])
    return [(t, b) for _, t, b in scored[:k]]


@app.post("/api/ask")
async def ask(req: Request):
    b = await _body(req)
    lang, q = _lang(b), str(b.get("question") or "")
    s = load_skill(b.get("skill", "income_certificate"))
    have = [str(x) for x in (b.get("docs_present") or [])]
    ctx = _retrieve(s["_knowledge"], q + " documents required reasons")
    system = (f"Answer the citizen's question using ONLY the context sections below. Reply in {lang_name(lang)} script, "
              "2-3 short spoken sentences. If the context does not answer it, say you are not sure and suggest asking "
              "the issuing office. Documents the user already has: " + ", ".join(have) + ". Mention what is still missing. "
              'Return JSON {"answer": "...", "sources": ["<section titles used>"], "missing": ["<missing document types in English>"]}'
              "\n\nCONTEXT:\n" + "\n\n".join(f"### {t}\n{bd}" for t, bd in ctx))
    try:
        out = await asyncio.to_thread(ai.ask_json, system, q or "Which documents do I need?", None, 0.1)
    except Exception as e:  # noqa: BLE001
        return err(e)
    if not isinstance(out, dict):
        out = {}
    out.setdefault("answer", "")
    out.setdefault("sources", [])
    out.setdefault("missing", [])
    audit.record("question_answered", {"question": q[:200], "sources": out.get("sources", [])}, "agent")
    return out


# ------------------------------------------------------------------ form fill
def _base(req: Request) -> str:
    return str(req.base_url).rstrip("/")


@app.post("/api/fill")
async def fill(req: Request):
    b = await _body(req)
    s = load_skill(b.get("skill", "income_certificate"))
    values = b.get("values") if isinstance(b.get("values"), dict) else {}
    values = {k: ("" if v is None else str(v).strip()) for k, v in values.items()}
    try:
        out = await asyncio.to_thread(browser.fill, _base(req), s["portal_url"], s["fields"], values)
    except Exception as e:  # noqa: BLE001
        return err(e)
    audit.record("form_filled", {"skill": s["id"], "values_hash": audit.sha(out["on_page_values"])[:16],
                                 "all_match": out["all_match"], "missing": out["missing_required"]}, "agent")
    return out


# ONE short sentence that ends with the code digits.
CONSENT_MSG = {
    "te": "{name} దరఖాస్తు పంపడానికి మీరు అంగీకరిస్తే ఈ కోడ్ చెప్పండి: {code_spoken}.",
    "ta": "{name} விண்ணப்பத்தை அனுப்ப ஒப்புக்கொண்டால் இந்தக் குறியீட்டைச் சொல்லுங்கள்: {code_spoken}.",
    "hi": "{name} का आवेदन भेजने के लिए सहमत हैं तो यह कोड बोलिए: {code_spoken}.",
    "en": "To send {name}'s application, say this code: {code_spoken}.",
}
CONSENT_ERR = {
    "missing_fields": {
        "te": "ఈ వివరాలు ఇంకా లేవు: {fields}. ముందు అవి చెప్పండి.",
        "ta": "இந்த விவரங்கள் இன்னும் இல்லை: {fields}. முதலில் அவற்றைச் சொல்லுங்கள்.",
        "hi": "ये जानकारी अभी बाकी है: {fields}. पहले इन्हें बताइए।",
        "en": "These details are still missing: {fields}. Please give them first."},
    "code_mismatch": {
        "te": "కోడ్ సరిపోలలేదు, దయచేసి మళ్ళీ చెప్పండి లేదా టైప్ చేయండి.",
        "ta": "குறியீடு பொருந்தவில்லை, மீண்டும் சொல்லுங்கள் அல்லது தட்டச்சு செய்யுங்கள்.",
        "hi": "कोड मेल नहीं खाया, कृपया फिर से बोलिए या टाइप कीजिए।",
        "en": "The code did not match, please say or type it again."},
    "action_changed": {
        "te": "ఫారంలో వివరాలు మారాయి, కొత్త కోడ్ కోసం మళ్ళీ సమర్పించు నొక్కండి.",
        "ta": "படிவ விவரங்கள் மாறிவிட்டன, புதிய குறியீட்டிற்கு மீண்டும் சமர்ப்பி அழுத்தவும்.",
        "hi": "फ़ॉर्म की जानकारी बदल गई है, नए कोड के लिए फिर से जमा करें दबाइए।",
        "en": "The form changed after the code was given; press Submit again for a new code."},
    "expired": {
        "te": "కోడ్ గడువు ముగిసింది, కొత్త కోడ్ కోసం మళ్ళీ సమర్పించు నొక్కండి.",
        "ta": "குறியீட்டின் நேரம் முடிந்தது, புதிய குறியீட்டிற்கு மீண்டும் சமர்ப்பி அழுத்தவும்.",
        "hi": "कोड की समय-सीमा खत्म हो गई, नए कोड के लिए फिर से जमा करें दबाइए।",
        "en": "The code has expired; press Submit again for a new code."},
    "no_pending_consent": {
        "te": "ఈ కోడ్ ఇప్పటికే వాడారు లేదా లేదు, మళ్ళీ సమర్పించు నొక్కండి.",
        "ta": "இந்தக் குறியீடு ஏற்கனவே பயன்படுத்தப்பட்டது, மீண்டும் சமர்ப்பி அழுத்தவும்.",
        "hi": "यह कोड पहले ही इस्तेमाल हो चुका है, फिर से जमा करें दबाइए।",
        "en": "This code was already used or is unknown; press Submit again."},
    "page_lost": {
        "te": "ఫారం విండో మూసివేయబడింది, దయచేసి ఫారం మళ్ళీ నింపండి.",
        "ta": "படிவச் சாளரம் மூடப்பட்டது, தயவுசெய்து படிவத்தை மீண்டும் நிரப்பவும்.",
        "hi": "फ़ॉर्म की विंडो बंद हो गई, कृपया फ़ॉर्म फिर से भरें।",
        "en": "The form window was closed; please fill the form again."},
    "submit_failed": {
        "te": "పోర్టల్ దరఖాస్తును తీసుకోలేదు. {fields}",
        "ta": "போர்டல் விண்ணப்பத்தை ஏற்கவில்லை. {fields}",
        "hi": "पोर्टल ने आवेदन स्वीकार नहीं किया। {fields}",
        "en": "The portal did not accept the application. {fields}"},
    "submit_failed_fields": {
        "te": "ఈ వివరాలు సరిచేయండి: {fields}.",
        "ta": "இவற்றைச் சரிசெய்யுங்கள்: {fields}.",
        "hi": "इन्हें ठीक कीजिए: {fields}।",
        "en": "Please fix: {fields}."},
}


def cmsg(key: str, lang: str, fields: list[str] | None = None) -> str:
    t = CONSENT_ERR[key].get(lang, CONSENT_ERR[key]["en"])
    f = ", ".join(fields or [])
    if key == "submit_failed":
        f = cmsg("submit_failed_fields", lang, fields) if fields else ""
    return t.format(fields=f).strip()


async def _live_form(req: Request, s: dict) -> dict | None:
    """Read back the live form (re-opening and re-filling it if the window was closed)."""
    try:
        return await asyncio.to_thread(browser.current, _base(req), s["portal_url"], s["fields"])
    except Exception as e:  # noqa: BLE001
        audit.record("page_lost", {"error": _plain(e)}, "system")
        return None


@app.post("/api/consent/challenge")
async def consent_challenge(req: Request):
    b = await _body(req)
    lang = _lang(b)
    s = load_skill(b.get("skill", "income_certificate"))
    if not browser.last_values():
        req_labels = [f["label"] for f in s["fields"] if f.get("required")]
        return {"ok": False, "reason": "missing_fields", "missing": req_labels,
                "message": cmsg("missing_fields", lang, req_labels)}
    live = await _live_form(req, s)
    if live is None:
        return {"ok": False, "reason": "page_lost", "message": cmsg("page_lost", lang)}
    if live["missing_required"]:
        audit.record("consent_refused", {"reason": "missing_fields", "missing": live["missing_required"]}, "system")
        return {"ok": False, "reason": "missing_fields", "missing": live["missing_required"],
                "message": cmsg("missing_fields", lang, live["missing_required"])}
    on_page = live["on_page_values"]
    payload = {"skill": s["id"], "values": on_page}
    summary = {"service": s["title"]["en"], "applicant": on_page.get("applicant_name")}
    ch = consent.challenge("submit_form", payload, summary)
    code_spoken = " ".join(ch["code"]) if ch["code"] else ""
    ch["spoken"] = CONSENT_MSG.get(lang, CONSENT_MSG["en"]).format(
        name=on_page.get("applicant_name") or "", code_spoken=code_spoken)
    ch["values"] = on_page
    ch["ok"] = True
    return ch


@app.post("/api/consent/verify")
async def consent_verify(req: Request):
    b = await _body(req)
    lang = _lang(b)
    s = load_skill(b.get("skill", "income_certificate"))
    live = await _live_form(req, s)
    if live is None:
        return {"ok": False, "reason": "page_lost", "message": cmsg("page_lost", lang)}
    payload = {"skill": s["id"], "values": live["on_page_values"]}
    res = consent.verify(str(b.get("challenge_id") or ""), str(b.get("heard") or ""), "submit_form", payload,
                         str(b.get("method") or "voice"))
    if not res["ok"]:
        res["message"] = cmsg(res["reason"], lang)
        return res
    try:
        sub = await asyncio.to_thread(browser.submit, _base(req), s["portal_url"], s["submit_button"], s["fields"])
    except Exception as e:  # noqa: BLE001
        audit.record("submit_failed", {"error": _plain(e)}, "system")
        consent.release(b.get("challenge_id", ""))
        return {"ok": False, "reason": "submit_failed", "message": cmsg("submit_failed", lang)}
    if not sub.get("submitted"):
        audit.record("submit_failed", {"missing": sub.get("missing", [])}, "system")
        consent.release(b.get("challenge_id", ""))
        return {"ok": False, "reason": "submit_failed", "missing": sub.get("missing", []),
                "message": cmsg("submit_failed", lang, sub.get("missing"))}
    audit.record("application_submitted", {"skill": s["id"], "application_no": sub["application_no"],
                                           "action_hash": res["action_hash"][:16]}, "agent")
    return {"ok": True, "submitted": True, "application_no": sub["application_no"], "audit": audit.verify()}


# ------------------------------------------------------------------ audit
@app.get("/api/audit")
def audit_list():
    return {"entries": audit.entries(), "verify": audit.verify()}


@app.post("/api/audit/reset")
def audit_reset():
    audit.reset()
    audit.record("session_started", {}, "system")
    return {"ok": True}


# ------------------------------------------------------------------ mock portal
@app.get("/portal/income-certificate", response_class=HTMLResponse)
def portal_page():
    return (PORTAL / "income-certificate.html").read_text(encoding="utf-8")


@app.post("/portal/api/submit")
async def portal_submit(req: Request):
    data = await _body(req)
    appno =f"SSP-IC-{time.strftime('%y%m%d')}-{secrets.randbelow(90000) + 10000}"
    with (config.DATA_DIR / "applications.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"application_no": appno, "data": audit.mask(data), "ts": time.time()}, ensure_ascii=False) + "\n")
    return {"application_no": appno}


# ------------------------------------------------------------------ samples + frontend
SAMPLES = ROOT / "samples"
if SAMPLES.exists():
    app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=config.PORT, loop="asyncio")
