# SAGE Seva: HackWithAditya 2026 registration text

Each section below maps to one registration field. Copy the text under the heading.

---

## Project title
SAGE Seva

## Tagline
Say it in your language. See exactly what gets submitted.

## Theme / track
AI for Bharat: agents, RAG, Telugu/Hindi voice AI, computer vision.

## Problem statement
Millions of Indians apply for government certificates through an intermediary: a Common Service Centre, a village secretariat or a Mee Seva counter. There are 5.67 lakh functional CSCs (MeitY/PIB, Oct 2025) and 15,004 village and ward secretariats in Andhra Pradesh alone (AP Ordinance 2 of 2026). The reason is digital access. Only 25.0% of Indians aged 15+ can search, email and bank online, only 55.8% of people in AP can use the internet, and only 6.7% of AP households own a computer (MoSPI CAMS 2022-23). Yet about 98% of active internet users use Indic languages (IAMAI-Kantar 2024), while e-service forms are in English. The citizen speaks Telugu and cannot check what was typed. Indian names have many English spellings, and mismatched spellings across documents are a reported reason applications get sent back. Today the citizen has no way to confirm that the submitted form matches what they said.

## Target users
- **Primary:** operators at CSCs, village/ward secretariats and Mee Seva centres who fill forms for citizens all day.
- **Beneficiaries:** first-time and low-literacy applicants who speak Telugu, Tamil or Hindi, often mixed with English, and cannot read the English form.
- **Secondary:** students, farmers and daily-wage workers who need income, caste or residence certificates for scholarships, fee reimbursement and schemes.

## Abstract
SAGE Seva is a voice agent that fills Indian e-service forms and proves to the citizen, in their own language, what it is about to submit. The user adds photos of their documents. Gemini vision extracts the fields and masks ID numbers to their last four digits. A deterministic name-consistency guard reconciles different English spellings of the same name across documents (Venkata / Vemkata, Subba Rao / Subbarao, initials versus full surname). It then spells the chosen English letters back in Telugu, Tamil or Hindi, so a person who cannot read English can still check them. The user gives occupation, income and purpose by voice or typing in Telugu, Tamil, Hindi, English or code-mixed speech. Playwright fills the form in a real browser and reads every field back from the page. Before submitting, the agent issues a 4-digit code derived from the SHA-256 hash of the exact on-page values. The user says or types the code. If any field changes after consent, the code no longer matches and submission is refused. Every step goes into a hash-chained, tamper-evident audit log. The prototype runs end to end on a mock income-certificate portal with synthetic documents. On a 50-pair development set, the name guard reconciled 30/30 same-person variants and wrongly merged 0/20 different people.

## Key features
1. **Name-consistency guard** with letter-by-letter spell-back in the user's language.
2. **Read-back verification:** every field is read back from the live page and shown as intended vs actual.
3. **Action-bound consent:** a code tied to the hash of the exact submission, said aloud or typed, refused if anything changes.
4. **Tamper-evident receipts:** SHA-256 hash chain with one-click verification.
5. **Four languages and code-mixed speech:** Telugu, Tamil, Hindi, English, including Tenglish, Tanglish and Hinglish.

## How it works / Technical approach
1. **Documents → fields.** `/api/extract` sends each photo to Gemini vision with a strict JSON schema. ID numbers are masked before storage or logging.
2. **Name guard** (`name_guard.py`, no model call). Names are folded with Indic transliteration rules: anusvara m/n, aspirates, long vowels, w/v, doubled letters, trailing schwa and x/ks. The guard also handles word order and initials and runs a hard-negative check. It prefers the spelling on the primary ID, shows a word-level diff and generates letter names in te/ta/hi. If it is unsure, it asks a human.
3. **Voice → slots.** `/api/stt` uses Gemini audio transcription, with Groq Whisper as fallback. `/api/agent` extracts intent and slots, for example "oka lakh iravai velu" → 120000.
4. **Grounded Q&A.** `/api/ask` retrieves from the service's knowledge pack and answers only from it.
5. **Fill and read back.** Playwright on a dedicated thread fills the portal from the skill's field map, then reads each field back.
6. **Consent.** `/api/consent/challenge` hashes {action, on-page values} and derives a 4-digit code with a per-challenge nonce. `/api/consent/verify` re-reads the page and re-hashes the values. It accepts native numerals and spoken digit words in four languages. The challenge expires after 5 minutes and works once.
7. **Audit.** Every event is appended to JSONL. Each row contains the SHA-256 of the previous row, so `verify()` finds the first broken row.
8. **Failover.** Five Gemini text models are tried in turn, with retries and per-document caching. Groq is the next fallback. Speech output goes Gemini TTS → edge-tts → browser voice.

## Tech stack, hardware and dependencies
- **Backend:** Python 3.11+, FastAPI, Uvicorn, Playwright (Chromium), google-genai, Groq SDK, edge-tts.
- **Frontend:** React + Vite + TypeScript, plain CSS, Atkinson Hyperlegible font, Web Audio for the mic and the Orb.
- **AI services:** Google Gemini (vision, transcription, text, optional TTS), Groq (Llama / Whisper fallback). Both have free tiers.
- **Hardware:** any laptop with a microphone. No GPU needed. Internet access is needed for the model APIs.
- **Data:** synthetic sample documents (`scripts/make_samples.py`) and a mock portal (`portal/income-certificate.html`).

## Features list
- Upload document photos or use the bundled samples.
- Field extraction with ID masking.
- Name reconciliation across documents with a diff and native-script spell-back.
- Voice or typed input in te/ta/hi/en and code-mixed speech.
- Language switch at any time; English UI by default.
- Grounded answers about requirements from the skill's knowledge pack.
- Live browser filling in a visible Chromium window.
- Intended-vs-actual read-back table.
- Hash-bound 4-digit consent by voice or keyboard.
- Refusal when the form changes after consent.
- Application number on success.
- Trust-receipt timeline with Verify chain.
- Spoken replies, large-text mode, 44px touch targets, visible keyboard focus and screen-reader announcements.
- Skill packs: a new service is a new folder (`skill.json` + `knowledge.md`).

## Limitations
- Runs on a mock portal with synthetic documents only. Real portals need official integration, and their CAPTCHA, OTP and login steps stay with a human. The agent never handles OTPs or passwords.
- Telugu and Tamil speech recognition is imperfect, especially for names and numbers. For that reason, names, dates and IDs come from document photos, not speech. We have not yet measured speech accuracy per language.
- The name guard is rule-based. Unusual names may go to human review, which is the safe default. It was evaluated on a team-authored development set, not a held-out benchmark.
- The knowledge pack is sample guidance, not an official checklist.
- Free-tier API limits and Gemini overload can slow extraction (30 to 55 s per document when overloaded). Failover and caching reduce this but do not remove it.
- One service (income certificate) is implemented so far.
- Consent challenges live in server memory. A production version would need persistent, multi-operator storage.

## What is novel
Voice browser agents already exist. The closest is SAHAY, an open-source Gemini agent that takes Hindi and Telugu voice commands, drives Playwright and asks permission before login or submit. Form-filling bots and OCR-to-form tools also exist. SAGE Seva does not claim the voice agent itself is new. Its contribution is the trust layer around the submission:

| | Voice browser agents (e.g. SAHAY) / form bots | SAGE Seva |
|---|---|---|
| Document photos as the source of names, dates and IDs | No / OCR only | Yes, with ID masking |
| Name spellings reconciled across documents | No | Yes, Indic phonetic folding plus a hard-negative check |
| English spelling spelled back in Telugu/Tamil/Hindi | No | Yes |
| Every field read back from the page after filling | Not shown | Yes, intended vs actual |
| Consent bound to the exact values | Generic "yes / allow" | Code from the SHA-256 of the on-page values; refused if anything changes |
| Tamper-evident record | Plain log | Hash chain with a verify button |
| Measured component | None | Name guard: 50-pair evaluation |

## Evaluation results
`python eval/name_guard_eval.py` runs on 50 labelled name pairs: 30 same-person spelling variants and 20 different-person hard negatives (shared surname or first name, one letter apart).

| | Exact string match (baseline) | SAGE Seva name guard |
|---|---|---|
| Same-person variants recognised | 0 / 30 (0%) | **30 / 30 (100%)** auto-reconciled, 0 sent to review, 0 missed |
| Different people wrongly merged | 0 / 20 | **0 / 20 (0%)**: 13 flagged for human review, 7 kept apart |

**Caveat:** the team wrote this set while developing the rules. It is a development set, not an independent benchmark. A held-out set from real, consented and anonymised documents is planned for Level 2. Speech accuracy has not yet been measured.

## Future scope (Level 2 roadmap)
1. **More services as skill packs:** caste, residence and birth certificates, plus scholarship and pension forms. Each one is a folder with a field map and a knowledge pack.
2. **More languages:** Kannada, Malayalam, Marathi, Bengali and Odia. Each needs a `LANGS` entry, a letter-name table and UI strings. Bhashini/IndicTrans ASR can be evaluated as an option.
3. **Offline / edge mode:** on-device ASR and OCR for low-connectivity secretariats. The audit chain is already local.
4. **Official API integration:** submit through state e-service APIs where they exist, with OTP and eSign kept human-in-the-loop.
5. **Accessibility:** a screen-reader-first flow, a voice-only mode for blind users, and adjustable speech rate.
6. **Operator dashboard:** a queue of citizens, per-application receipts, export of verified chains, and a supervisor audit view.
7. **Held-out evaluation with real consented data:** name guard precision and recall, and per-language speech word and digit error rates.
8. **Security hardening:** persistent consent store, signed chain anchors, and role-based access.

## Team work split
- _[Member 1, team lead]_: architecture, backend agent, consent and audit design.
- _[Member 2]_: name guard rules and evaluation set.
- _[Member 3]_: frontend UI, accessibility, multilingual strings.
- _[Member 4]_: mock portal, sample documents, testing, demo video.

(Edit names and roles before submitting.)

## AI tools disclosure
- Claude Code (Anthropic) helped write code and documentation.
- Google Gemini and Groq APIs run inside the product for vision, transcription, text and speech.
- The team reviewed and tested all code and can explain every part of it.

## Provenance
SAGE Seva is derived from S.A.G.E, the team lead's earlier personal AI assistant. These ideas and parts were carried over and adapted: the risk-tiered permission gate, the audit log design, the Playwright browser tool pattern, multi-provider failover and the Orb UI component.

These parts are new in this project: the name-consistency guard and spell-back, action-bound hash consent, the hash-chained receipts, read-back verification, skill packs, the mock portal, the multilingual UI and the evaluation.

## GitHub
https://github.com/user-is-surya/sage-seva

## Setup steps (summary)
1. `git clone https://github.com/user-is-surya/sage-seva.git && cd sage-seva`
2. `python -m venv .venv`, activate it, then `pip install -r requirements.txt && python -m playwright install chromium`
3. `cp .env.example .env` and add `GEMINI_API_KEY`. `GROQ_API_KEY` is optional.
4. `cd frontend && npm install && npm run build && cd ..`
5. `python backend/app.py`, then open http://127.0.0.1:8000 and click **Use sample documents**.
