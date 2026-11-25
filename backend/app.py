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


def err(e: Exception, status: int = 502):
    return JSONResponse({"error": str(e)[:600]}, status_code=status)


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
    try:
        return await asyncio.to_thread(ai.transcribe, data, audio.content_type or "audio/webm", lang)
    except Exception as e:  # noqa: BLE001
        return err(e)


@app.post("/api/tts")
async def tts(req: Request):
    body = await req.json()
    text, lang = (body.get("text") or "").strip(), body.get("lang", "te")
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
 "reply": "<a short, warm spoken reply in {lang} script (1-2 sentences), telling the user what happens next>"
}}
Rules:
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
    b = await req.json()
    lang = b.get("lang", "te")
    s = load_skill(b.get("skill", "income_certificate"))
    slots = ", ".join(f'"{k}": "<{v}>"' for k, v in s["voice_slots"].items())
    system = AGENT_SYSTEM.format(lang=lang_name(lang), service=s["title"]["en"],
                                 state=json.dumps(b.get("state", {}), ensure_ascii=False)[:1500], slots=slots)
    try:
        out = await asyncio.to_thread(ai.ask_json, system, b.get("text", ""))
    except Exception as e:  # noqa: BLE001
        return err(e)
    audit.record("voice_command", {"intent": out.get("intent"), "slots": out.get("slots", {}), "lang": lang}, "user")
    out["engine"] = ai.last_used.get("text")
    return out


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
    b = await req.json()
    docs, lang = b.get("docs", []), b.get("lang", "te")
    name = name_guard.reconcile(docs, "name_latin", lang)
    father = name_guard.reconcile(docs, "father_name_latin", lang)
    dob = name_guard.compare_simple([(d.get("label", ""), d.get("dob", "")) for d in docs])
    audit.record("name_check", {"name_status": name["status"], "canonical": name.get("canonical"),
                                "father_status": father["status"], "dob_consistent": dob["consistent"]}, "agent")
    return {"name": name, "father": father, "dob": dob, "spoken": guard_message(name, lang)}


GUARD_MSG = {
    "te": {"consistent": "మీ పత్రాలన్నింటిలో పేరు ఒకేలా ఉంది.",
           "variant": "మీ పత్రాల్లో పేరు వేర్వేరుగా రాసి ఉంది. ఫారంలో {src} లో ఉన్నట్లే రాస్తాను. అక్షరాలు ఇవి: {spell}. ఇది సరైనదేనా?",
           "needs_check": "పేర్లు కొంచెం భిన్నంగా ఉన్నాయి, దయచేసి తనిఖీ చేయండి. అక్షరాలు: {spell}.",
           "conflict": "ఒక పత్రంలో పూర్తిగా వేరే పేరు ఉంది. ఆ పత్రం ఇదే వ్యక్తిదేనా తనిఖీ చేయండి."},
    "ta": {"consistent": "உங்கள் எல்லா ஆவணங்களிலும் பெயர் ஒன்றாக உள்ளது.",
           "variant": "உங்கள் ஆவணங்களில் பெயர் வெவ்வேறு விதமாக எழுதப்பட்டுள்ளது. {src} இல் உள்ளபடியே படிவத்தில் எழுதுவேன். எழுத்துகள்: {spell}. இது சரியா?",
           "needs_check": "பெயர்கள் சற்று வேறுபடுகின்றன, தயவுசெய்து சரிபார்க்கவும். எழுத்துகள்: {spell}.",
           "conflict": "ஒரு ஆவணத்தில் முற்றிலும் வேறு பெயர் உள்ளது. அது இதே நபருடையதா என சரிபார்க்கவும்."},
    "hi": {"consistent": "आपके सभी दस्तावेज़ों में नाम एक जैसा है।",
           "variant": "आपके दस्तावेज़ों में नाम अलग-अलग तरह से लिखा है। फ़ॉर्म में मैं {src} के अनुसार लिखूँगा। अक्षर हैं: {spell}. क्या यह सही है?",
           "needs_check": "नाम थोड़े अलग हैं, कृपया जाँच लें। अक्षर: {spell}.",
           "conflict": "एक दस्तावेज़ में बिल्कुल अलग नाम है। कृपया जाँचें कि वह इसी व्यक्ति का है।"},
    "en": {"consistent": "The name matches on all your documents.",
           "variant": "Your documents spell the name differently. I will type it exactly as on the {src}: {spell}. Is that correct?",
           "needs_check": "The names differ slightly, please check. Letters: {spell}.",
           "conflict": "One document has a completely different name. Please check it belongs to this person."},
}


def guard_message(name: dict, lang: str) -> str:
    if name.get("status") == "missing":
        return ""
    t = GUARD_MSG.get(lang, GUARD_MSG["en"])[name["status"]]
    return t.format(src=name.get("canonical_source", ""), spell=name.get("spell_back", ""))


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
    b = await req.json()
    lang, q = b.get("lang", "te"), b.get("question", "")
    s = load_skill(b.get("skill", "income_certificate"))
    have = b.get("docs_present", [])
    ctx = _retrieve(s["_knowledge"], q + " documents required reasons")
    system = (f"Answer the citizen's question using ONLY the context sections below. Reply in {lang_name(lang)} script, "
              "2-3 short spoken sentences. If the context does not answer it, say you are not sure and suggest asking "
              "the issuing office. Documents the user already has: " + ", ".join(have) + ". Mention what is still missing. "
              'Return JSON {"answer": "...", "sources": ["<section titles used>"], "missing": ["<missing document types in English>"]}'
              "\n\nCONTEXT:\n" + "\n\n".join(f"### {t}\n{bd}" for t, bd in ctx))
    try:
        out = await asyncio.to_thread(ai.ask_json, system, q or "Which documents do I need?")
    except Exception as e:  # noqa: BLE001
        return err(e)
    audit.record("question_answered", {"question": q[:200], "sources": out.get("sources", [])}, "agent")
    return out


# ------------------------------------------------------------------ form fill
def _base(req: Request) -> str:
    return str(req.base_url).rstrip("/")


@app.post("/api/fill")
async def fill(req: Request):
    b = await req.json()
    s = load_skill(b.get("skill", "income_certificate"))
    values = b.get("values", {})
    try:
        out = await asyncio.to_thread(browser.fill, _base(req), s["portal_url"], s["fields"], values)
    except Exception as e:  # noqa: BLE001
        return err(e)
    audit.record("form_filled", {"skill": s["id"], "values_hash": audit.sha(out["on_page_values"])[:16],
                                 "all_match": out["all_match"], "missing": out["missing_required"]}, "agent")
    return out


CONSENT_MSG = {
    "te": "నేను {name} పేరుతో {service} దరఖాస్తును సమర్పించబోతున్నాను. ఇది మీ తరపున పంపబడుతుంది, పంపిన తర్వాత మార్చలేము. మీరు అంగీకరిస్తే, ఈ కోడ్ చెప్పండి: {code_spoken}.",
    "ta": "{name} பெயரில் {service} விண்ணப்பத்தை சமர்ப்பிக்கப் போகிறேன். இது உங்கள் சார்பில் அனுப்பப்படும், அனுப்பிய பின் மாற்ற முடியாது. நீங்கள் ஒப்புக்கொண்டால், இந்தக் குறியீட்டைச் சொல்லுங்கள்: {code_spoken}.",
    "hi": "मैं {name} के नाम से {service} का आवेदन जमा करने जा रहा हूँ। यह आपकी ओर से भेजा जाएगा और भेजने के बाद बदला नहीं जा सकता। अगर आप सहमत हैं, तो यह कोड बोलिए: {code_spoken}.",
    "en": "I am about to submit the {service} application for {name}. It will be sent on your behalf and cannot be changed afterwards. If you agree, say this code: {code_spoken}.",
}


@app.post("/api/consent/challenge")
async def consent_challenge(req: Request):
    b = await req.json()
    lang = b.get("lang", "te")
    s = load_skill(b.get("skill", "income_certificate"))
    try:
        on_page = await asyncio.to_thread(browser.current_values, _base(req), s["portal_url"], s["fields"])
    except Exception as e:  # noqa: BLE001
        return err(e)
    payload = {"skill": s["id"], "values": on_page}
    summary = {"service": s["title"]["en"], "applicant": on_page.get("applicant_name")}
    ch = consent.challenge("submit_form", payload, summary)
    code_spoken = " ".join(ch["code"]) if ch["code"] else ""
    ch["spoken"] = CONSENT_MSG.get(lang, CONSENT_MSG["en"]).format(
        name=on_page.get("applicant_name") or "", service=s["title"].get(lang, s["title"]["en"]), code_spoken=code_spoken)
    ch["values"] = on_page
    return ch


@app.post("/api/consent/verify")
async def consent_verify(req: Request):
    b = await req.json()
    s = load_skill(b.get("skill", "income_certificate"))
    try:
        on_page = await asyncio.to_thread(browser.current_values, _base(req), s["portal_url"], s["fields"])
    except Exception as e:  # noqa: BLE001
        return err(e)
    payload = {"skill": s["id"], "values": on_page}
    res = consent.verify(b.get("challenge_id", ""), b.get("heard", ""), "submit_form", payload, b.get("method", "voice"))
    if not res["ok"]:
        return res
    try:
        sub = await asyncio.to_thread(browser.submit, _base(req), s["portal_url"], s["submit_button"])
    except Exception as e:  # noqa: BLE001
        audit.record("submit_failed", {"error": str(e)[:200]}, "system")
        return err(e)
    audit.record("application_submitted", {"skill": s["id"], "application_no": sub["application_no"],
                                           "action_hash": res["action_hash"][:16]}, "agent")
    return {"ok": True, **sub, "audit": audit.verify()}


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
    data = await req.json()
    appno = f"SSP-IC-{time.strftime('%y%m%d')}-{secrets.randbelow(90000) + 10000}"
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

    uvicorn.run(app, host="127.0.0.1", port=8000, loop="asyncio")
