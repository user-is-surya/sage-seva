# SAGE Seva
### A trust layer for voice-driven government form filling in Indian languages

| | |
|---|---|
| **Event** | HackWithAditya 2026, Aditya University, Level 1 prototype screening |
| **Track** | AI for Bharat: agents, RAG, Telugu/Hindi voice AI, computer vision |
| **Team** | _[Team name]_: _[Member names]_ |
| **Repository** | https://github.com/user-is-surya/sage-seva |
| **Status** | Working prototype on a mock income-certificate portal with synthetic documents |

---

## 1. Problem

Government services in India have moved online, but many citizens do not apply on their own. They go to an intermediary, such as a Common Service Centre (CSC), a village or ward secretariat or a Mee Seva counter. An operator types the application in English while the citizen describes their details in Telugu, Tamil or Hindi.

This creates three trust gaps:

1. **Names.** Indian names have no single English spelling. The same person can appear as *Venkata* on one document and *Vemkata* on another, as *Subba Rao* or *Subbarao*, or with initials instead of a full surname. Mismatched spellings across documents are a reported reason applications get sent back (news reports; no published rate exists). The citizen often cannot read the English spelling that the operator typed.
2. **What was typed.** The citizen cannot check the English form. They have to trust that the operator or tool entered what they said.
3. **What was agreed.** A spoken "yes" does not say what it agreed to. If the form changes after that "yes", nothing catches it.

## 2. Evidence

All figures below come from primary sources. Rates we could not find measured are labelled as not measured.

| Indicator | Figure | Source |
|---|---|---|
| Persons aged 15+ who can search, email and bank online (India) | 25.0% | MoSPI, CAMS 2022-23 (NSS Report 590), Table 21, pub. Oct 2024 |
| Persons aged 15+ who can use the internet, Andhra Pradesh | 55.8% | MoSPI, CAMS 2022-23, Table 16 |
| Households owning a computer, Andhra Pradesh | 6.7% | MoSPI, CAMS 2022-23, Table 22 |
| Active internet users accessing content in Indic languages | ~98% | IAMAI-Kantar, *Internet in India 2024*, pub. Jan 2025 |
| Functional Common Service Centres | 5.67 lakh (Oct 2025) | MeitY / PIB release, Dec 2025 |
| Village and ward secretariats in Andhra Pradesh | 15,004 | AP Ordinance 2 of 2026 |
| Rejections caused by name mismatch | Reported, **not quantified** | News reports only |

Most people, especially in AP, depend on assisted access to e-services. They prefer their own language, but the forms are in English. The operator network that serves them is large: hundreds of thousands of CSCs, and more than 15,000 secretariats in AP alone. A small gain in trust per application applies across every one of those counters.

## 3. Users

- **Operators** at CSCs, secretariats and Mee Seva centres fill many forms a day. They need speed, and they need to avoid sending applications back for errors.
- **Citizens** are the beneficiaries: first-time or low-literacy applicants who speak Telugu, Tamil or Hindi, often mixed with English. They need to know what is being submitted in their name.
- **Students, farmers and daily-wage workers** most often need income, caste and residence certificates, for scholarships, fee reimbursement and welfare schemes.

## 4. Solution

SAGE Seva is a voice agent that fills an e-service form from document photos and speech. It also shows the citizen, in their own language, exactly what it is about to submit. The flow:

1. **Documents.** The user adds photos of ID documents. Gemini vision extracts the fields, and ID numbers are masked to their last 4 digits.
2. **Name guard.** The guard reconciles the different spellings of the name across documents and picks the one on the primary ID. It shows a word-level diff and spells the English letters back in the user's language, for example "V-E-N-K-A-T-A" read as Telugu letter names.
3. **Conversation.** The user gives occupation, income and purpose by voice or typing in Telugu, Tamil, Hindi, English or code-mixed speech. For example, *"Nenu raitu ni, income oka lakh iravai velu, scholarship kosam"* becomes occupation = Farmer, income = 120000, purpose = Scholarship.
4. **Fill and read back.** Playwright fills the portal in a visible browser and then reads every field back from the page.
5. **Action-bound consent.** The agent explains the submission aloud and shows a 4-digit code derived from the SHA-256 hash of the exact on-page values. The user says or types the code. If anything changed after the code was issued, the code is refused.
6. **Submit and receipt.** The portal returns an application number. Every step is in a hash-chained audit log that anyone can verify.

## 5. Architecture

```
 ┌──────────────────────────── Browser UI (React + Vite + TS) ─────────────────────────────┐
 │  Orb + mic     Chat (te/ta/hi/en)     Application steps     Trust-receipt timeline       │
 └──────┬──────────────┬───────────────────────┬──────────────────────────┬─────────────────┘
        │ audio        │ text / photos         │ fill / consent           │ audit
        ▼              ▼                       ▼                          ▼
 ┌──────────────────────────────────── FastAPI backend ─────────────────────────────────────┐
 │ /api/stt ──► ai.transcribe ── Gemini audio ─(fail)─► Groq Whisper                         │
 │ /api/agent ─► ai.ask_json ─── Gemini (5-model chain, retry) ─(fail)─► Groq                │
 │ /api/extract ► Gemini vision ─► fields ─► audit.mask(ID)          [per-document cache]    │
 │ /api/reconcile ► name_guard.py  (deterministic: phonetic fold, initials, hard negatives,  │
 │                                  native-script spell-back)                                │
 │ /api/ask ──► retrieve(skills/<id>/knowledge.md) ─► grounded answer                        │
 │ /api/fill ─► browser.py ─────────────────────────┐                                        │
 │ /api/consent/challenge ► consent.py: code = f(SHA-256{action, on-page values}, nonce)     │
 │ /api/consent/verify ──► re-read page ─► re-hash ─► compare ─► submit ─► app. number       │
 │ /api/tts ──► Gemini TTS ─(fail)─► edge-tts ─(fail)─► browser speech                       │
 │ audit.py: append-only JSONL, row.prev_hash = SHA-256(previous row) ── verify()            │
 └──────────────────────────────────────────────────┼────────────────────────────────────────┘
                                                    │ Playwright (dedicated thread, Chromium)
                                                    ▼
                                  ┌──────────────────────────────────┐
                                  │ Mock portal /portal/income-      │
                                  │ certificate  (fill ► read back ► │
                                  │ submit ► application number)     │
                                  └──────────────────────────────────┘
 skills/income_certificate/  skill.json (portal URL, field map, voice slots) + knowledge.md
```

## 6. Component details

**Model layer (`backend/ai.py`, `config.py`).** The backend detects which Gemini models the API key can use and ranks them. Calls go through a chain of five Gemini text models with retries. A model that hits a quota error is put on a short cooldown. Groq is the next fallback. JSON output is parsed defensively. Document extraction results are cached per document, so a re-run is instant. Speech output tries Gemini TTS, then edge-tts, then the browser voice.

**Name-consistency guard (`backend/name_guard.py`).** This is a deterministic component with no model call, so its output can be repeated and audited. Each name token is reduced to a phonetic key using Indic transliteration rules:
- anusvara m/n before consonants
- aspirates (th/t, dh/d, bh/b)
- long vowels (aa/a, ee/i, oo/u)
- w/v, doubled consonants, trailing schwa (Ramu/Ram) and x/ks

Tokens are aligned while allowing for word order, joined words (Subba Rao / Subbarao) and initials. A hard-negative check keeps apart names that differ in a meaningful letter (for example, a different first name with the same surname). If it is unsure, the guard sends the pair to human review instead of merging. The chosen spelling is spelled back letter by letter using Telugu, Tamil or Hindi letter names.

**Skill packs (`skills/<service>/`).** `skill.json` describes the portal URL, the submit button, and each field with its source: `guard:` for names, `doc:` for document fields and `voice:` for spoken slots. It also lists the slot descriptions used for speech extraction. `knowledge.md` grounds the Q&A. Adding a service means adding a folder, with no change to the code.

**Browser tool (`backend/browser.py`).** Playwright runs on a dedicated thread so it does not block the async server. It fills each mapped field, reads it back and returns intended vs actual for every field. At consent time it reads the current on-page values again.

**Consent (`backend/consent.py`).** Each action has a risk tier. Filling the form is low risk because nothing is sent. Submitting or deleting is high risk. For a high-risk action:
- the challenge stores `SHA-256({action, payload})` and a 4-digit code derived from that hash and a random nonce
- verification re-hashes the payload read from the page; a different hash means "action changed after consent" and the action is refused
- the spoken or typed answer is parsed for ASCII digits, Telugu, Devanagari and Tamil numerals, and spoken digit words in all four languages
- each challenge expires after 300 seconds and works only once
- every request, rejection and grant is audited

**Audit log (`backend/audit.py`).** Rows are written to append-only JSONL with canonical JSON serialisation. Each row stores the SHA-256 of the previous row. `verify()` walks the chain and reports the first row whose hash does not match. ID-like values are masked before they are written. `scripts/tamper_demo.py` edits a past row to show detection, and `--undo` restores it.

**Frontend (`frontend/src`).** Built with React, Vite and TypeScript, and plain CSS. The UI includes the Orb voice visualiser, chat, application steps, the read-back table, the consent panel and the receipt timeline. It is available in four UI languages and uses the Atkinson Hyperlegible font for low-vision readers. Other accessibility features: large-text mode, touch targets of at least 44 px, visible keyboard focus, and live-region announcements for screen readers.

## 7. Trust model

| Threat | Mitigation |
|---|---|
| Wrong or inconsistent name spelling | Name guard, diff and native-script spell-back; human review when unsure |
| Field typed wrongly or not typed | Read-back from the live page; no field is reported as filled without checking |
| Vague "yes" consent | Code bound to the hash of the exact values; the user must repeat it |
| Form changed after consent (by the operator or a script) | Values are re-read and re-hashed at submit; a mismatch is refused and logged |
| Mis-heard digits | Code can be typed; native numerals and spoken digit words are parsed |
| Replay of an old consent | One use only, 5-minute expiry, random nonce |
| Silent editing of history | SHA-256 hash chain; Verify chain shows the first broken row |
| Leaking ID numbers | Masked to the last 4 digits before storage or logging |
| OTP, password or CAPTCHA abuse | Out of scope by design: these steps always stay with a human |

## 8. Evaluation

**Name guard.** Run `python eval/name_guard_eval.py` on 50 labelled pairs. 30 are same-person spelling variants. 20 are different-person hard negatives that share a surname or first name, or differ by one letter.

| | Exact string match (baseline) | SAGE Seva name guard |
|---|---|---|
| Same-person variants recognised | 0 / 30 (0%) | **30 / 30 (100%)** auto-reconciled, 0 to review, 0 missed |
| Different people wrongly merged | 0 / 20 | **0 / 20 (0%)**: 13 sent to human review, 7 kept apart |

**Caveat.** The team wrote this set while developing the rules. It is a development set, not an independent benchmark. The guard's caution shows in the 13 hard negatives it sent to human review rather than deciding itself.

**End-to-end.** The full flow runs on the mock portal: sample documents → name guard → voice slots → fill → read-back → consent → submit → application number. A wrong code and a change after consent are both refused. Tampering is detected by Verify chain.

**Not yet measured:** per-language speech recognition accuracy (word and digit error rate), and extraction accuracy on real documents.

## 9. Limitations

- Mock portal and synthetic documents only. There is no integration with a real government system.
- CAPTCHA, OTP, login and eSign are deliberately left to a human.
- Telugu and Tamil speech recognition is imperfect for names and numbers. This is why names, dates and IDs come from photos, and why the code can be typed.
- The name guard is rule-based and was evaluated only on a development set.
- The knowledge pack is sample guidance, not an official checklist.
- Free-tier rate limits and model overload can slow extraction to 30 to 55 seconds per document. Failover and caching reduce this.
- Only one service is implemented, and consent state is kept in server memory.

## 10. Future scope (Level 2)

1. **More services as skill packs:** caste, residence, birth, scholarship and pension forms.
2. **More languages:** Kannada, Malayalam, Marathi, Bengali, Odia. Evaluate Bhashini/IndicTrans ASR.
3. **Offline / edge mode** for low-connectivity secretariats, using on-device ASR and OCR.
4. **Official API integration** with state e-service APIs, keeping OTP and eSign with a human.
5. **Accessibility:** a voice-only flow for blind users, adjustable speech rate, and screen-reader-first navigation.
6. **Operator dashboard:** queue, per-application receipts, chain export and a supervisor view.
7. **Held-out evaluation** with real, consented and anonymised data: name guard precision and recall, and per-language WER and digit accuracy.
8. **Hardening:** persistent consent store, signed or anchored chain heads, and role-based access.

## 11. Team

| Member | Role |
|---|---|
| _[Name]_ (lead) | Architecture, backend agent, consent and audit |
| _[Name]_ | Name guard and evaluation |
| _[Name]_ | Frontend, accessibility, i18n |
| _[Name]_ | Mock portal, samples, testing, demo |

**Provenance.** SAGE Seva is derived from S.A.G.E, the lead's earlier personal assistant. The permission gate, the audit-log design, the Playwright tool pattern, provider failover and the Orb UI were carried over and adapted. The name guard, hash-bound consent, hash chain, read-back, skill packs, portal, multilingual UI and evaluation are new.

**AI disclosure.** Claude Code (Anthropic) helped write code and documentation. Gemini and Groq APIs run inside the product. The team reviewed and tested all code and can explain it.

## 12. References

1. MoSPI, *Comprehensive Annual Modular Survey (CAMS) 2022-23*, NSS Report 590, Oct 2024. https://mospi.gov.in/sites/default/files/publication_reports/CAMS%20Report_October_N.pdf
2. IAMAI & Kantar, *Internet in India 2024*, Jan 2025. https://www.iamai.in/sites/default/files/research/Kantar_%20IAMAI%20report_2024_.pdf
3. MeitY / PIB, release on Common Service Centres, Dec 2025. https://pib.gov.in/PressReleasePage.aspx?PRID=2202905
4. Government of Andhra Pradesh, Ordinance 2 of 2026 (village and ward secretariats). https://prsindia.org/files/bills_acts/bills_states/andhra-pradesh/2026/Ord2of2026AP.pdf
5. SAHAY, voice-controlled browser agent write-up. https://dev.to/sherinjosephroy/building-a-voice-controlled-browser-agent-with-three-gemini-models-3j3h
6. Playwright. https://playwright.dev · FastAPI. https://fastapi.tiangolo.com · Google Gemini API. https://ai.google.dev
