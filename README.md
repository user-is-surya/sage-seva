# SAGE Seva

**Say it in your language. See exactly what gets submitted.**

SAGE Seva is a voice agent for Indian e-service forms. A citizen-service operator, or a first-time user,
speaks in Telugu, Tamil, Hindi or English, often mixed with English (Tenglish, Tanglish, Hinglish). They
show photos of their documents, and the agent fills the application form. Before anything is sent, the
agent proves three things:

1. **The name is right.** Indian names have no single English spelling (Venkata / Venkat / Vemkata,
   Subba Rao / Subbarao, initials vs full surname). Documents of the same person routinely disagree, and
   mismatched spellings are a reported reason applications get sent back. SAGE Seva's **name-consistency
   guard** reconciles the spellings across documents. It picks the one on the primary ID, shows a
   word-by-word diff, and **spells the English letters back in the user's own language**. Someone who
   cannot read English can then still check exactly what will be typed.
2. **The form says what we think it says.** After filling, the agent reads every field **back from the
   page** and shows intended vs actual. It never reports a field as filled without checking.
3. **The person really agreed to this exact submission.** A spoken "yes" binds to nothing. For
   high-risk actions, the agent explains the action aloud in the user's language. The user must then
   repeat a **code derived from the hash of the exact action** (which form, which values), by voice or by
   typing. If anything on the form changes after consent, the code no longer matches and submission is
   refused.

Every step is written to a **hash-chained, tamper-evident audit log**. Each row carries the SHA-256 of
the previous row, so editing any past entry breaks verification from that point. ID numbers are masked to
their last 4 digits before they are ever written.

> Built for HackWithAditya 2026 (AI for Bharat track). It is demonstrated on a **mock portal with
> synthetic documents**. No real government system is touched and no real ID data is used.

---

## Quick start (Windows / macOS / Linux)

Requirements: Python 3.11+, Node 18+, a free **Gemini API key** (https://aistudio.google.com/apikey).
A free **Groq key** (https://console.groq.com) is optional and used as a fallback.

```bash
git clone https://github.com/user-is-surya/sage-seva.git
cd sage-seva

# 1. backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# 2. keys
cp .env.example .env        # then paste GEMINI_API_KEY (and optionally GROQ_API_KEY)

# 3. frontend (built once, served by the backend)
cd frontend && npm install && npm run build && cd ..

# 4. run
python backend/app.py
```

Open **http://127.0.0.1:8000**. Click **Use sample documents**, then talk to it, or type.
A Chromium window opens and shows the agent filling the mock portal. Set `SEVA_HEADED=0` in `.env` to
hide it.

Dev mode with hot reload: run `python backend/app.py` and `cd frontend && npm run dev`, then open
http://localhost:5173.

### Try the trust features
- **Name guard:** the three sample cards spell the same fictional person three ways.
- **Wrong consent code:** type any other 4 digits and the submission is refused.
- **Change after consent:** edit a field in the portal window after the code is shown. The code is then
  refused, because the action changed.
- **Tamper with the receipts:** run `python scripts/tamper_demo.py` and press **Verify chain**. The chain
  shows broken at the edited row. Restore it with `python scripts/tamper_demo.py --undo`.
- **Measure the guard:** `python eval/name_guard_eval.py`.

---

## How it works

```
 Browser UI (React)                       Backend (FastAPI, Python)                         Mock portal
 ───────────────────                      ──────────────────────────                        ───────────
 mic ─► /api/stt ───────────────────────► Gemini audio transcription  (fallback: Groq Whisper)
 text ─► /api/agent ────────────────────► intent + slot extraction in te/ta/hi/en (Gemini → Groq)
 photos ─► /api/extract ────────────────► Gemini vision → fields (ID numbers masked)
 /api/reconcile ────────────────────────► name_guard.py  (deterministic, no model call)
 /api/ask ──────────────────────────────► retrieval over the skill's knowledge pack → grounded answer
 /api/fill ─────────────────────────────► Playwright fills form ─────────────────────────► reads back
 /api/consent/challenge ────────────────► hash(action) → 4-digit code, explained in user's language
 /api/consent/verify ───────────────────► re-hash on-page values, check code ─► submit ─► app. no.
 receipts panel ◄── /api/audit ◄────────── audit.py  (SHA-256 hash chain, verify())
 speaker ◄── /api/tts ◄─────────────────── Gemini TTS  (fallback: edge-tts, then browser voice)
```

| Piece | File | Notes |
|---|---|---|
| Name-consistency guard | `backend/name_guard.py` | Phonetic folding for Indic transliteration (anusvara m/n, aspirates, long vowels, w/v, doubled letters, trailing schwa, x/ks), word-order and initials handling, a hard-negative check, and letter-name spell-back in te/ta/hi |
| Action-bound consent | `backend/consent.py` | Risk tiers, a code from SHA-256 of the action, native-numeral and spoken-digit parsing in 4 languages, refusal on change |
| Tamper-evident receipts | `backend/audit.py` | Append-only JSONL, each row hashes the previous, ID masking |
| Browser tool | `backend/browser.py` | Playwright on a dedicated thread; fill → read back → submit |
| Model failover | `backend/ai.py` | Gemini first, Groq / edge-tts fallbacks, provider cooldown on quota errors; models auto-detected from your key |
| Skill packs | `skills/<service>/` | `skill.json` (portal URL, field map, voice slots) + `knowledge.md` (grounding for Q&A). **Adding a new service is adding a folder.** |
| UI | `frontend/src/App.tsx` | Assistant (Orb + voice), application steps, trust-receipt timeline, 4-language UI, large-text mode |

### Extending it
- **New service:** copy `skills/income_certificate/`, change the field map and knowledge, and point
  `portal_url` at the form.
- **New language:** add one entry to `LANGS` in `backend/config.py`, a letter-name table in
  `name_guard.py`, and UI strings in `frontend/src/i18n.ts`.

---

## Evaluation

`python eval/name_guard_eval.py` runs on 50 labelled name pairs: 30 same-person spelling variants and 20
different-person hard negatives (shared surname or first name, one letter apart).

| | Exact match (no guard) | SAGE Seva name guard |
|---|---|---|
| Same-person variants recognised | 0 / 30 | **30 / 30** auto-reconciled |
| Different people wrongly merged | 0 / 20 | **0 / 20** (13 sent to human review, 7 kept apart) |

**Caveat:** the team wrote this set while developing the rules, so it is a development set, not an
independent benchmark. A held-out set from real (consented, anonymised) documents is future work.

## Limitations (honest list)
- **Mock portal only.** Real portals need official integration (APIs, CAPTCHA and OTP steps that a
  human must do). The agent never handles OTPs or passwords.
- **Telugu and Tamil speech recognition is imperfect,** especially for names and numbers. That is why
  names, dates and ID digits come from document photos, not speech, and why the consent code can also be
  typed. We have not yet measured speech accuracy per language.
- **The knowledge pack is sample guidance,** not an official checklist. It must be replaced with the
  state's official requirements.
- **Free-tier API limits** can throttle a live demo. The app fails over to Groq or edge-tts, and finally
  to the browser voice.
- **The name guard is rule-based.** Unusual names may go to human review, which is the safe default.

## Provenance and AI disclosure
- SAGE Seva is derived from **S.A.G.E**, the team lead's earlier personal AI assistant (Sept 2026). These
  ideas and parts were carried over and adapted:
  - the risk-tiered permission gate
  - the audit-log design
  - the Playwright browser tool pattern
  - multi-provider failover
  - the `Orb` UI component and colour tokens

  The name guard, action-bound consent, hash chain, skill packs, mock portal, multilingual UI and
  evaluation are new in this project.
- **AI tools used:** Claude Code (Anthropic) helped write code and documentation. Gemini and Groq APIs
  run inside the product. The team reviewed, tested and can explain all code.

## License
MIT
