# SAGE Seva — demo video script (4:30)

**Before recording:**
- Start `python backend/app.py` and open http://127.0.0.1:8000.
- Click **Use sample documents** once so that extraction is cached. On camera it will then load instantly.
- Reset the receipts.
- Arrange the screen with the app on the left and the Chromium portal window on the right.
- Have a terminal open in `sage-seva/`.
- Use the headset mic. Narration is in English. The user's spoken lines are in Telugu.

| Time | On screen (exact action) | Narration |
|---|---|---|
| **0:00–0:25** | Title card: "SAGE Seva — Say it in your language. See exactly what gets submitted." Then the app home screen with the Orb and the three-step "how it works". | "Only 25% of Indians over 15 can search, email and bank online, and in Andhra Pradesh only 6.7% of households own a computer. So millions apply for certificates through CSCs and village secretariats. The citizen speaks Telugu, the form is in English, and the citizen can't check what was typed. SAGE Seva closes that gap." |
| **0:25–0:40** | Click the **Telugu** language button at the top. The UI switches to Telugu. | "It works in Telugu, Tamil, Hindi and English, including mixed speech like Tenglish. We'll apply for an income certificate in Telugu." |
| **0:40–1:15** | Click **Use sample documents**. Three cards appear. Point at the three name spellings, then the name-guard panel with the diff and the Telugu letter spell-back. Let the voice play. | "These are three synthetic documents for the same person, and the name is spelled three different ways. Exact matching sees three different people. Our name-consistency guard knows Indic transliteration: m and n, aspirates, long vowels, initials. It picks the spelling on the primary ID, shows the difference word by word, and then spells the English letters back in Telugu. Someone who can't read English can still confirm the spelling." |
| **1:15–1:45** | Press **Tap to speak** and say: *"Nenu raitu ni, income oka lakh iravai velu, scholarship kosam."* Show the transcript and the filled slots: Farmer / 120000 / Scholarship. | "Occupation, income and purpose come by voice. 'Oka lakh iravai velu' becomes one lakh twenty thousand. Names, dates and ID numbers come from the photos, not speech, because speech recognition is weakest on exactly those." |
| **1:45–2:20** | Click **Fill the form**. The Chromium window on the right fills field by field. Then the **intended vs actual** read-back table appears, all green. | "Now a real browser fills the portal. This is a mock portal; we never touch a real government system. After filling, the agent reads every field back from the page and compares it with what it intended. It never says 'done' without checking." |
| **2:20–2:55** | Click **Submit application**. The consent panel shows the 4-digit code and the Telugu explanation plays. First type a wrong code, which is refused. Then say the correct code in Telugu digits. | "Submitting is high risk, so a simple 'yes' isn't enough. The agent explains in Telugu what will be sent and gives a 4-digit code. The code comes from a SHA-256 hash of the exact values on the page. A wrong code is refused. The right one can be spoken, in Telugu digits here, or typed." |
| **2:55–3:10** | An application number appears. Open the **receipts** timeline and scroll through the steps. | "The application is submitted, and here is the number. Every step was written to a receipt log." |
| **3:10–3:40** | **Change-after-consent demo:** start a new submit and get a code. In the Chromium window, edit the income field, for example to 20000. Then enter the code. It is refused with "action changed after consent". Show the `consent_rejected` row in the receipts. | "What if someone changes the form after the citizen agreed? Here I edit the income after the code was issued. The code no longer matches the hash of the page, so the submission is refused and the attempt is logged. Consent is tied to the exact values, not to a moment." |
| **3:40–4:10** | **Tamper demo:** in the terminal, run `python scripts/tamper_demo.py` and show its output. Back in the app, press **Verify chain**. The broken row is highlighted. Run `python scripts/tamper_demo.py --undo`, press **Verify chain** again, and it shows intact. | "The receipts are a hash chain. Each row carries the hash of the one before it. This script quietly edits a past application number. Verify chain catches it at that exact row. Undo the edit, and the chain checks out again." |
| **4:10–4:30** | Terminal: `python eval/name_guard_eval.py` shows 30/30 and 0/20. End card: GitHub link and "AI for Bharat — HackWithAditya 2026". | "On our 50-pair development set, exact matching recognises 0 of 30 same-person spellings. The guard reconciles all 30 and wrongly merges none of the 20 different people. That's a set we wrote ourselves, so a held-out evaluation with real data is our next step, along with more services and languages. SAGE Seva: say it in your language, and see exactly what gets submitted." |

**Fallbacks while recording:**
- If Gemini is slow, the cached documents still load instantly.
- If a spoken digit is mis-heard, type the code. Mention it: "speech mis-hears digits, so typing is always allowed."
- If Gemini TTS is unavailable, the voice falls back to edge-tts. No narration change is needed.
