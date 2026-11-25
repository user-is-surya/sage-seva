import { useCallback, useEffect, useRef, useState } from "react";
import Orb, { type VoiceState } from "./components/Orb";
import { api, Recorder, speak, stopSpeaking, setMuted, muted as mutedInit } from "./api";
import { EVENT_LABEL, LANGS, t, type Lang } from "./i18n";
import Icon from "./components/Icon";

type Msg = { id: number; who: "you" | "seva"; text: string; meta?: string; error?: boolean };
type Doc = Record<string, any> & { thumb?: string; file?: string; uid: string };
type Pending = { uid: string; name: string; thumb: string };
type Phase = "waiting" | "listening" | "checking" | "wrong" | "success";
const SAMPLES = ["1_identity_card.png", "2_ration_card.png", "3_voter_id.png"];
const SLOT_KEYS = ["occupation", "annual_income", "purpose", "mobile"] as const;
const SLOT_MATCH: Record<string, RegExp> = { occupation: /occup/i, annual_income: /income/i, purpose: /purpose/i, mobile: /mobile|phone/i };
const VERDICT: Record<string, { label: string; cls: string }> = {
  identical: { label: "identical", cls: "ok" },
  initial_vs_full: { label: "initials vs full name", cls: "warn" },
  same_name_different_spelling: { label: "same name, different spelling", cls: "warn" },
  possible_match_check: { label: "check manually", cls: "warn" },
  different: { label: "different name", cls: "bad" },
};
const SPEAK_MAX = 160; // never auto-speak anything longer than one short sentence
let uidN = 0;
const uid = () => `u${++uidN}`;

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [big, setBig] = useState(false);
  const [muted, setMutedS] = useState(mutedInit);
  const [voice, setVoice] = useState<VoiceState>("armed");
  const [level, setLevel] = useState(0);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [typed, setTyped] = useState("");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [guard, setGuard] = useState<any>(null);
  const [nameAck, setNameAck] = useState(false);
  const [slots, setSlots] = useState<Record<string, string>>({ occupation: "", annual_income: "", purpose: "", mobile: "" });
  const [missingSlots, setMissingSlots] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [answer, setAnswer] = useState<any>(null);
  const [readBack, setReadBack] = useState<any>(null);
  const [consent, setConsent] = useState<any>(null);
  const [phase, setPhase] = useState<Phase>("waiting");
  const [consentErr, setConsentErr] = useState("");
  const [shake, setShake] = useState(0);
  const [codeInput, setCodeInput] = useState("");
  const [result, setResult] = useState<any>(null);
  const [audit, setAudit] = useState<any>({ entries: [], verify: { ok: true, count: 0 } });
  const [busy, setBusy] = useState("");
  const [health, setHealth] = useState<any>(null);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const rec = useRef<Recorder | null>(null);
  const consentRef = useRef<any>(null);
  consentRef.current = consent;
  const voiceRef = useRef<VoiceState>("armed");
  voiceRef.current = voice;
  const docsRef = useRef<Doc[]>([]);
  docsRef.current = docs;
  const codeRef = useRef<HTMLInputElement>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const L = (k: string) => t(lang, k);

  const refreshAudit = useCallback(() => api.audit().then(setAudit).catch(() => {}), []);
  useEffect(() => { api.health().then(setHealth).catch(() => {}); refreshAudit(); }, [refreshAudit]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs]);

  const post = useCallback((m: Omit<Msg, "id">) => setMsgs((x) => [...x.slice(-60), { ...m, id: ++uidN }]), []);

  const shutUp = useCallback(() => {
    stopSpeaking();
    if (voiceRef.current === "speaking") setVoice("armed");
  }, []);

  /** Show a message; speak it only if it is short (and voice isn't muted). */
  const say = useCallback(async (text: string, opts: { meta?: string; voice?: boolean } = {}) => {
    if (!text) return;
    post({ who: "seva", text, meta: opts.meta });
    const wantVoice = opts.voice ?? text.length <= SPEAK_MAX;
    if (!wantVoice) return;
    setVoice("speaking");
    await speak(text, lang);
    if (voiceRef.current === "speaking") setVoice("armed");
  }, [lang, post]);

  const fail = useCallback((e: any) => post({ who: "seva", text: e?.message || "Something went wrong. Please try again.", error: true }), [post]);

  // Escape stops speech; if nothing is speaking, closes the consent dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (voiceRef.current === "speaking") { shutUp(); e.preventDefault(); return; }
      if (consentRef.current) setConsent(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shutUp]);

  function toggleMute() {
    const v = !muted; setMuted(v); setMutedS(v);
    if (v && voiceRef.current === "speaking") setVoice("armed");
  }

  // ------------------------------------------------------------ step logic
  const slotsDone = !!(slots.occupation.trim() && slots.annual_income.trim() && slots.purpose.trim());
  const missingN = readBack?.missing_required?.length || 0;
  const fillOk = !!readBack && !!readBack.all_match && missingN === 0;
  const fillLabel = !readBack ? "" : fillOk ? L("allMatch") : missingN ? `${missingN} ${({ te: "వివరాలు లేవు", ta: "விவரங்கள் இல்லை", hi: "विवरण बाकी", en: missingN === 1 ? "detail missing" : "details missing" } as Record<string, string>)[lang]}` : L("needsCheck");
  const auto = result ? 4 : (readBack && slotsDone) ? 3 : (nameAck || readBack) ? 2 : guard ? 1 : 0;
  useEffect(() => { setOpenStep(null); }, [auto]);
  const current = openStep ?? auto;

  // ------------------------------------------------------------ documents
  async function reconcile(list: Doc[]) {
    if (!list.length) { setGuard(null); setNameAck(false); return; }
    try {
      const g = await api.reconcile(list, lang);
      setGuard(g); setNameAck(false);
      refreshAudit();
      if (g.spoken) say(g.spoken);
    } catch (e) { fail(e); }
  }

  async function readDocs(files: { blob: Blob; name: string; thumb: string }[]) {
    const jobs = files.map((f) => ({ ...f, uid: uid() }));
    setPending((p) => [...p, ...jobs.map(({ uid, name, thumb }) => ({ uid, name, thumb }))]);
    setBusy("docs");
    await Promise.all(jobs.map(async (f) => {
      try {
        const d = await api.extract(f.blob, f.name, lang);
        const doc: Doc = { ...d, thumb: f.thumb, file: f.name, uid: f.uid };
        docsRef.current = [...docsRef.current, doc];
        setDocs(docsRef.current);
      } catch (e: any) {
        post({ who: "seva", text: `${f.name}: ${e.message}`, error: true });
      }
      setPending((p) => p.filter((x) => x.uid !== f.uid));
    }));
    refreshAudit();
    await reconcile(docsRef.current);
    setBusy("");
  }

  async function useSamples() {
    if (busy) return;
    setBusy("docs");
    try {
      const files = await Promise.all(SAMPLES.map(async (n) => {
        const r = await fetch(`/samples/${n}`);
        if (!r.ok) throw new Error("Sample documents are not available.");
        return { blob: await r.blob(), name: n, thumb: `/samples/${n}` };
      }));
      docsRef.current = []; setDocs([]); setGuard(null);
      await readDocs(files);
    } catch (e) { fail(e); setBusy(""); }
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []).map((f) => ({ blob: f, name: f.name, thumb: URL.createObjectURL(f) }));
    e.target.value = "";
    if (files.length && !busy) readDocs(files);
  }

  async function removeDoc(u: string) {
    const next = docs.filter((d) => d.uid !== u);
    docsRef.current = next; setDocs(next); setReadBack(null);
    setBusy("docs");
    await reconcile(next);
    setBusy("");
  }

  // ------------------------------------------------------------ form values
  function formValues(): Record<string, string> {
    const primary = docs.find((d) => d.doc_type === "identity_card") || docs[0] || {};
    const pick = (k: string) => (primary as any)[k] || docs.find((d) => d[k])?.[k] || "";
    return {
      applicant_name: guard?.name?.canonical || pick("name_latin"),
      father_name: guard?.father?.canonical || pick("father_name_latin"),
      dob: pick("dob"), gender: pick("gender"), address: pick("address"),
      district: pick("district"), state: pick("state"), id_last4: pick("id_last4"),
      occupation: slots.occupation, annual_income: slots.annual_income, purpose: slots.purpose, mobile: slots.mobile,
    };
  }

  function flagMissing(labels: string[], message?: string) {
    const keys = SLOT_KEYS.filter((k) => labels.some((l) => SLOT_MATCH[k].test(l)));
    setMissingSlots(keys);
    setNotice(message || `${L("missingFields")} ${labels.join(", ")}`);
    if (keys.length) setOpenStep(2);
  }

  async function doFill() {
    if (busy) return;
    if (!docs.length) { setNotice(L("fillHint")); return; }
    setBusy("fill"); setNotice(""); setMissingSlots([]);
    try {
      const r = await api.fill(formValues());
      setReadBack(r); setNameAck(true);
      refreshAudit();
      const ok = r.all_match && !r.missing_required?.length;
      if (r.missing_required?.length) flagMissing(r.missing_required);
      else setOpenStep(3); // show the read-back table right away
      const msg = {
        te: ok ? "ఫారం నింపి, ప్రతి ఫీల్డ్ సరిచూశాను." : "ఫారం నింపాను, కొన్ని ఫీల్డ్‌లు తనిఖీ చేయాలి.",
        ta: ok ? "படிவம் நிரப்பி, ஒவ்வொரு புலமும் சரிபார்த்தேன்." : "படிவம் நிரப்பினேன், சில புலங்களைச் சரிபார்க்கவும்.",
        hi: ok ? "फ़ॉर्म भरकर हर फ़ील्ड जाँच लिया।" : "फ़ॉर्म भरा, कुछ फ़ील्ड जाँचने होंगे।",
        en: ok ? "Form filled and every field checked." : "Form filled. Some fields need checking.",
      }[lang];
      say(msg);
    } catch (e) { fail(e); }
    setBusy("");
  }

  async function startConsent() {
    if (busy) return;
    setBusy("consent"); setConsentErr(""); setCodeInput(""); setNotice("");
    try {
      const c = await api.challenge(lang);
      refreshAudit();
      if (c.ok === false) {
        flagMissing(c.missing || [], c.message);
        say(c.message || L("missingFields"));
      } else {
        setMissingSlots([]);
        setPhase("waiting");
        setConsent(c);
        say(c.spoken);
      }
    } catch (e) { fail(e); }
    setBusy("");
  }

  useEffect(() => { if (consent) setTimeout(() => codeRef.current?.focus(), 80); }, [consent]);

  async function confirmConsent(heard: string, method: string) {
    const c = consentRef.current;
    if (!c || !heard.trim()) return;
    shutUp();
    setBusy("verify"); setPhase("checking"); setConsentErr("");
    try {
      const r = await api.verifyConsent(c.challenge_id, heard, method);
      if (r.ok) {
        setPhase("success");
        refreshAudit();
        setTimeout(() => {
          setResult(r); setConsent(null);
          const done = {
            te: `సమర్పించబడింది. మీ సంఖ్య ${r.application_no}.`,
            ta: `சமர்ப்பிக்கப்பட்டது. உங்கள் எண் ${r.application_no}.`,
            hi: `जमा हो गया। आपका नंबर ${r.application_no}.`,
            en: `Submitted. Your application number is ${r.application_no}.`,
          }[lang];
          say(done);
        }, 1100);
      } else {
        setPhase("wrong"); setShake((s) => s + 1); setCodeInput("");
        const msg = r.message || (r.reason === "action_changed" ? L("changed") : L("codeWrong"));
        setConsentErr(`${msg}${r.heard_digits ? ` (${r.heard_digits})` : ""}`);
        if (["expired", "action_changed", "no_pending_consent"].includes(r.reason)) {
          setTimeout(() => setConsent(null), 2600);
          post({ who: "seva", text: msg, error: true });
        }
        refreshAudit();
        setTimeout(() => codeRef.current?.focus(), 50);
      }
    } catch (e: any) { setPhase("wrong"); setShake((s) => s + 1); setConsentErr(e.message); }
    setBusy("");
  }

  async function askDocs(q?: string) {
    if (busy) return;
    setBusy("ask");
    try {
      const r = await api.ask(q || "Which documents are required and what is missing?", lang, docs.map((d) => d.label || d.doc_type));
      setAnswer(r); refreshAudit();
      say(r.answer);
    } catch (e) { fail(e); }
    setBusy("");
  }

  // ------------------------------------------------------------ voice turn
  async function handleText(text: string, engine?: string) {
    if (!text.trim()) return;
    post({ who: "you", text, meta: engine });
    if (consentRef.current) { await confirmConsent(text, "voice"); return; }
    setVoice("thinking");
    try {
      const state = { step: auto, documents: docs.map((d) => d.label), name_status: guard?.name?.status, slots, filled: !!readBack };
      const r: any = await api.agent(text, lang, state);
      const s = r.slots || {};
      const clean = Object.fromEntries(Object.entries(s).filter(([k, v]) => v && (SLOT_KEYS as readonly string[]).includes(k)).map(([k, v]) => [k, String(v)]));
      if (Object.keys(clean).length) { setSlots((p) => ({ ...p, ...clean })); setMissingSlots((m) => m.filter((k) => !clean[k])); }
      refreshAudit();
      setVoice("armed");
      if (r.intent === "ask_question") return askDocs(r.question);
      await say(r.reply, { meta: r.engine });
      if (r.intent === "fill_form") doFill();
      if (r.intent === "submit") startConsent();
    } catch (e) { setVoice("armed"); fail(e); }
  }

  async function toggleMic() {
    if (voice === "thinking") return;
    if (voice === "listening") {
      setVoice("thinking");
      if (consentRef.current) setPhase("checking");
      try {
        const blob = await rec.current!.stop();
        const r = await api.stt(blob, lang);
        setVoice("armed");
        await handleText(r.text, r.engine);
      } catch (e) { fail(e); if (consentRef.current) setPhase("waiting"); }
      if (voiceRef.current === "thinking") setVoice("armed");
      return;
    }
    shutUp(); // pressing the mic interrupts speech immediately
    rec.current = new Recorder();
    rec.current.onLevel = setLevel;
    try {
      await rec.current.start(); setVoice("listening");
      if (consentRef.current) setPhase("listening");
    } catch (e: any) { setVoice("armed"); post({ who: "seva", text: `Microphone unavailable: ${e.message}`, error: true }); }
  }

  async function newSession() {
    shutUp();
    try { await api.resetAudit(); } catch (e) { fail(e); }
    docsRef.current = [];
    setDocs([]); setPending([]); setGuard(null); setNameAck(false); setReadBack(null); setConsent(null); setResult(null);
    setAnswer(null); setMsgs([]); setNotice(""); setMissingSlots([]);
    setSlots({ occupation: "", annual_income: "", purpose: "", mobile: "" });
    refreshAudit();
  }

  const v = audit.verify || {};
  const steps = ["s1", "s2", "s3", "s4", "s5"];
  const summary = (i: number): string => {
    if (i === 0) return docs.length ? `${docs.length} ${L("docsCount")} · ${docs.map((d) => d.label || d.doc_type).join(", ")}` : "";
    if (i === 1) return guard?.name?.canonical || "";
    if (i === 2) return [slots.occupation, slots.annual_income && `₹${fmtINR(slots.annual_income)}`, slots.purpose].filter(Boolean).join(" · ");
    if (i === 3) return fillLabel;
    return result?.application_no || "";
  };
  const statusText = voice === "listening" ? L("listening") : voice === "thinking" ? L("thinking") : voice === "speaking" ? L("speaking") : L("tapToSpeak");
  const busyNow = !!busy;

  return (
    <div className={`app ${big ? "big" : ""} lang-${lang}`}>
      <header className="top">
        <div className="brand">
          <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
            {Array.from({ length: 12 }).map((_, i) => (
              <line key={i} x1="16" y1="16" x2={16 + 12 * Math.cos((i * Math.PI) / 6)} y2={16 + 12 * Math.sin((i * Math.PI) / 6)} stroke="currentColor" strokeWidth="1" opacity=".55" />
            ))}
            <circle cx="16" cy="16" r="3.2" fill="var(--saffron)" />
          </svg>
          <div>
            <div className="name">SAGE <em>Seva</em></div>
            <div className="tag">{L("tagline")}</div>
          </div>
        </div>
        <div className="controls">
          <div className="seg" role="group" aria-label="Language">
            {LANGS.map((l) => (
              <button key={l.id} aria-pressed={l.id === lang} className={l.id === lang ? "on" : ""} onClick={() => setLang(l.id)}>{l.label}</button>
            ))}
          </div>
          <button className="tbtn" aria-pressed={muted} onClick={toggleMute} title={muted ? L("unmute") : L("mute")}>
            <Icon name={muted ? "volOff" : "vol"} /> <span>{muted ? L("unmute") : L("mute")}</span>
          </button>
          <button className="tbtn" aria-pressed={big} onClick={() => setBig(!big)}><Icon name="text" /> <span>{L("bigText")}</span></button>
          <span className={`pill ${v.ok ? "ok" : "bad"}`} role="status"><i />{v.ok ? L("chainOk") : L("chainBroken")} · {v.count}</span>
          <button className="tbtn" onClick={newSession}><Icon name="refresh" /> <span>{L("newSession")}</span></button>
        </div>
      </header>

      <main className="grid">
        {/* ------------------------------------------------ assistant */}
        <section className="col assistant" aria-label={L("assistant")}>
          <div className={`stage ${voice}`}>
            <div className="orb-wrap" onClick={toggleMic} aria-hidden="true"><Orb state={voice} level={level} /></div>
            <div className="status" aria-live="polite"><span className="dot" />{statusText}</div>
            <div className="mic-row">
              <button className={`mic ${voice}`} onClick={toggleMic} disabled={voice === "thinking"} aria-label={voice === "listening" ? L("listening") : L("tapToSpeak")}>
                <Icon name={voice === "listening" ? "stop" : "mic"} size={22} />
              </button>
              {voice === "speaking" && (
                <button className="stop-speak" onClick={shutUp}><Icon name="skip" /> {L("stopSpeaking")} <kbd>Esc</kbd></button>
              )}
            </div>
          </div>
          <div className="chat" aria-live="polite">
            {msgs.length === 0 && <p className="chat-empty">{L("emptyChat")}</p>}
            {msgs.map((m) => (
              <div key={m.id} className={`msg ${m.who} ${m.error ? "error" : ""}`}>
                {m.error && <Icon name="alert" size={15} />}
                <div>{m.text}{m.meta && <span className="meta">{m.meta}</span>}</div>
              </div>
            ))}
            <div ref={chatEnd} />
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); const x = typed; setTyped(""); handleText(x); }}>
            <input aria-label={L("typeHere")} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={L("typeHere")} />
            <button aria-label={L("send")} disabled={!typed.trim() || voice === "thinking"}><Icon name="send" /></button>
          </form>
        </section>

        {/* ------------------------------------------------ application */}
        <section className="col flow" aria-label={L("application")}>
          <div className="flow-head">
            <div className="eyebrow">{L("application")}</div>
            <h1>{L("service")}</h1>
            <div className="progress" aria-hidden="true"><span style={{ width: `${(Math.min(auto + (result ? 1 : 0), 5) / 5) * 100}%` }} /></div>
          </div>

          <ol className="rail">
            {steps.map((k, i) => {
              const state = i < auto || (i === 4 && result) ? "done" : i === auto ? "now" : "later";
              const open = current === i;
              return (
                <li key={k} className={`step ${state} ${open ? "open" : ""}`} style={{ ["--i" as any]: i }}>
                  <button className="step-h" aria-expanded={open} onClick={() => setOpenStep(open ? -1 : i)}>
                    <span className="node">{state === "done" ? <Icon name="check" size={14} /> : i + 1}</span>
                    <span className="step-t">{L(k)}</span>
                    {!open && <span className="step-sum">{summary(i)}</span>}
                    {!open && state === "done" && <span className="edit">{L("edit")}</span>}
                  </button>
                  <div className="step-b" hidden={!open}>
                    {open && i === 0 && (
                      <div className="body">
                        <div className="row">
                          <label className={`btn ${busyNow ? "disabled" : ""}`}><Icon name="upload" /> {L("addDocs")}
                            <input type="file" accept="image/*" multiple hidden disabled={busyNow} onChange={onPick} /></label>
                          <button className="btn ghost" onClick={useSamples} disabled={busyNow}><Icon name="doc" /> {L("useSamples")}</button>
                        </div>
                        {docs.length === 0 && pending.length === 0 && (
                          <div className="howto">
                            <div className="eyebrow">{L("howTitle")}</div>
                            <ol>
                              {["how1", "how2", "how3"].map((h, n) => <li key={h} style={{ ["--i" as any]: n }}><b>{String(n + 1).padStart(2, "0")}</b>{L(h)}</li>)}
                            </ol>
                          </div>
                        )}
                        {(docs.length > 0 || pending.length > 0) && (
                          <div className="docs">
                            {docs.map((d) => (
                              <article className="doc" key={d.uid}>
                                {d.thumb && <img src={d.thumb} alt={`Photo of ${d.label || "document"}`} />}
                                <div className="doc-t">
                                  <div className="dlabel">{d.label || d.doc_type}</div>
                                  <div className="dname">{d.name_native}</div>
                                  <div className="dlatin">{d.name_latin}</div>
                                  <div className="dmeta">{d.dob}{d.id_number ? ` · ${d.id_number}` : ""}</div>
                                </div>
                                <button className="x" onClick={() => removeDoc(d.uid)} disabled={busyNow} aria-label={`${L("removeDoc")}: ${d.label || d.file}`}><Icon name="x" size={14} /></button>
                              </article>
                            ))}
                            {pending.map((p) => (
                              <article className="doc skel" key={p.uid} aria-busy="true">
                                <img src={p.thumb} alt="" />
                                <div className="doc-t"><div className="sk w40" /><div className="sk w80" /><div className="sk w60" /><div className="mini">{L("readingN")} {p.name}</div></div>
                              </article>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {open && i === 1 && (
                      <div className="body">
                        {!guard?.name?.canonical ? <p className="muted">{busy === "docs" ? L("reading") : L("fillHint")}</p> : (
                          <div className={`guard ${guard.name.status}`}>
                            <div className="canon">
                              <span className="eyebrow">{L("willType")}</span>
                              <span className="v">{guard.name.canonical}</span>
                              <span className="src">{L("from")} {guard.name.canonical_source}</span>
                            </div>
                            <div className="variants">
                              {guard.name.variants.map((x: any, vi: number) => {
                                const toks = x.diff?.length ? x.diff.filter((d: any) => d.found !== null || !x.diff.some((o: any) =>
                                  o.found && d.expected && o.found.toLowerCase().includes(d.expected.toLowerCase()))) : null;
                                return (
                                  <div className="var" key={vi} style={{ ["--i" as any]: vi }}>
                                    <div className="var-l">{x.label}{x.primary && <em> · {L("primary")}</em>}</div>
                                    <div className="toks">
                                      {toks ? toks.map((d: any, j: number) => (
                                        <span key={j} style={{ ["--j" as any]: vi * 4 + j }} className={`tok ${d.same ? "same" : "diff"}`} title={d.expected ? `expected ${d.expected}` : "extra"}>{d.found ?? `∅ ${d.expected}`}</span>
                                      )) : <span className="tok same">{x.value}</span>}
                                    </div>
                                    <span className={`chip ${VERDICT[x.verdict]?.cls || ""}`}>{VERDICT[x.verdict]?.label || x.verdict}</span>
                                  </div>
                                );
                              })}
                            </div>
                            <div className="spell">
                              <div><span className="eyebrow">{L("spellBack")}</span><span className="v mono">{guard.name.spell_back}</span></div>
                              <button className="btn small ghost" onClick={() => say(guard.spell_spoken || guard.spoken, { voice: true })} disabled={muted}><Icon name="play" size={14} /> {L("play")}</button>
                            </div>
                            {guard.father?.canonical && (
                              <div className="minor">
                                {L("fatherLbl")} <b>{guard.father.canonical}</b>
                                <span className={`chip ${guard.father.status === "consistent" ? "ok" : "warn"}`}>{guard.father.status}</span>
                                <span className={`chip ${guard.dob?.consistent ? "ok" : "warn"}`}>{guard.dob?.consistent ? L("dobOk") : L("dobDiff")}</span>
                              </div>
                            )}
                            <div className="row end"><button className="btn primary" onClick={() => setNameAck(true)}>{L("continueBtn")} <Icon name="arrow" /></button></div>
                          </div>
                        )}
                      </div>
                    )}

                    {open && i === 2 && (
                      <div className="body">
                        <div className="slots">
                          {SLOT_KEYS.map((k) => (
                            <label key={k} className={missingSlots.includes(k) ? "need" : slots[k] ? "has" : ""}><span>{L(k)}</span>
                              <input value={slots[k]} inputMode={k === "annual_income" || k === "mobile" ? "numeric" : undefined}
                                onChange={(e) => { setSlots({ ...slots, [k]: e.target.value }); if (e.target.value) setMissingSlots((m) => m.filter((x) => x !== k)); }} />
                            </label>
                          ))}
                        </div>
                        {notice && <div className="notice" role="alert"><Icon name="alert" size={16} /> {notice}</div>}
                        <div className="row">
                          <button className="btn ghost" onClick={() => askDocs()} disabled={busyNow}>{busy === "ask" ? <span className="spin" /> : <Icon name="help" />} {L("askDocs")}</button>
                        </div>
                        {answer && (
                          <div className="answer">
                            <div>{answer.answer}</div>
                            {answer.missing?.length > 0 && <div className="minor">{L("missing")}: {answer.missing.join(", ")}</div>}
                            {answer.sources?.length > 0 && <div className="minor">{L("sources")}: {answer.sources.join(" · ")}</div>}
                          </div>
                        )}
                      </div>
                    )}

                    {open && i === 3 && (
                      <div className="body">
                        {!readBack ? <p className="muted">{L("fillHint")}</p> : (
                          <>
                            <div className={`rb-head ${fillOk ? "ok" : "warn"}`}><Icon name={fillOk ? "check" : "alert"} size={16} /> {fillLabel}</div>
                            <table className="rb">
                              <thead><tr><th></th><th>{L("intended")}</th><th>{L("onPage")}</th><th></th></tr></thead>
                              <tbody>
                                {readBack.rows.filter((r: any) => r.intended || r.on_page || r.required).map((r: any, n: number) => (
                                  <tr key={r.id} className={r.match ? "" : "mis"} style={{ ["--i" as any]: n }}>
                                    <td>{r.label}</td><td>{r.intended}</td><td>{r.on_page}</td>
                                    <td>{r.match ? <Icon name="check" size={14} /> : r.required && !r.on_page ? <span className="chip bad">missing</span> : <span className="chip warn">differs</span>}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </>
                        )}
                        {notice && <div className="notice" role="alert"><Icon name="alert" size={16} /> {notice}</div>}
                      </div>
                    )}

                    {open && i === 4 && (
                      <div className="body">
                        {result ? (
                          <div className="success">
                            <svg className="tick" viewBox="0 0 52 52" aria-hidden="true"><circle cx="26" cy="26" r="24" /><path d="M15 27l7 7 15-16" /></svg>
                            <div>
                              <div className="eyebrow">{L("appNo")}</div>
                              <div className="appno">{String(result.application_no).split("").map((c, n) => <span key={n} style={{ ["--i" as any]: n }}>{c}</span>)}</div>
                              <div className="muted">{L("submitted")}</div>
                            </div>
                          </div>
                        ) : <p className="muted">{L("waitingCode")}</p>}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>

          {!result && (
            <div className="dock">
              {auto <= 2 && (
                <button className="btn primary lg" onClick={doFill} disabled={busyNow || !docs.length}>
                  {busy === "fill" ? <><span className="spin" /> {L("thinking")}</> : <><Icon name="pen" /> {L("fill")}</>}
                </button>
              )}
              {auto === 3 && (
                <>
                  <button className="btn ghost" onClick={doFill} disabled={busyNow}>{busy === "fill" ? <span className="spin" /> : <Icon name="refresh" />} {L("fill")}</button>
                  <button className="btn primary lg" onClick={startConsent} disabled={busyNow}>
                    {busy === "consent" ? <><span className="spin" /> {L("thinking")}</> : <><Icon name="lock" /> {L("submit")}</>}
                  </button>
                </>
              )}
            </div>
          )}
        </section>

        {/* ------------------------------------------------ receipts */}
        <section className="col receipts" aria-label={L("receipts")}>
          <div className="rc-head">
            <h2>{L("receipts")}</h2>
            <button className="btn small ghost" onClick={refreshAudit}><Icon name="shield" size={14} /> {L("verify")}</button>
          </div>
          <div className={`verify ${v.ok ? "ok" : "bad"}`} role="status" aria-live="polite">
            <div className="vrow"><Icon name={v.ok ? "chain" : "alert"} size={16} /> {v.ok ? `${L("chainOk")} · ${v.count} ${L("entries")}` : `${L("chainBroken")} @ #${v.broken_at}`}</div>
            {!v.ok && v.reason && <div className="small">{v.reason}</div>}
            {v.head && <div className="mono small">head {String(v.head).slice(0, 20)}…</div>}
          </div>
          <p className="note">{L("trustNote")}</p>
          <ol className="timeline">
            {[...(audit.entries || [])].reverse().map((e: any, n: number) => (
              <li key={e.seq} className={`ev ev-${e.event} ${v.broken_at && e.seq >= v.broken_at ? "broken" : ""}`} style={{ ["--i" as any]: Math.min(n, 8) }}>
                <div className="evh"><span className="seq">#{e.seq}</span> {EVENT_LABEL[e.event] || e.event}<span className="who">{e.actor}</span></div>
                {summarize(e) && <div className="evd">{summarize(e)}</div>}
                <div className="mono small">{e.hash?.slice(0, 12)} ← {e.prev?.slice(0, 8)}</div>
              </li>
            ))}
          </ol>
          {health && (
            <div className="engines mono small">
              text {health.models?.text} · tts {health.models?.tts || "edge-tts"}
            </div>
          )}
        </section>
      </main>

      {consent && (
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="consent-title" onClick={(e) => { if (e.target === e.currentTarget && phase !== "checking") setConsent(null); }}>
          <div className={`sheet ${phase}`} key={`s${shake}`}>
            <div className="sheet-h">
              <Icon name="shield" size={20} />
              <h2 id="consent-title">{L("consentTitle")}</h2>
            </div>
            <p className="spoken">{consent.spoken}</p>
            <div className="eyebrow center">{L("sayCode")}</div>
            <div className="code" aria-label={String(consent.code).split("").join(" ")}>
              {String(consent.code).split("").map((c, n) => <span key={n} style={{ ["--i" as any]: n }}>{c}</span>)}
            </div>
            <div className="phase" aria-live="assertive">
              {phase === "waiting" && <>{L("waitingCode")}</>}
              {phase === "listening" && <><span className="dot live" /> {L("listening")}</>}
              {phase === "checking" && <><span className="spin" /> {L("checking")}</>}
              {phase === "success" && <><Icon name="check" size={16} /> {L("success")}</>}
              {phase === "wrong" && <span className="err"><Icon name="alert" size={16} /> {consentErr}</span>}
            </div>
            <div className="sheet-actions">
              <button className={`mic sm ${voice}`} onClick={toggleMic} disabled={phase === "checking" || phase === "success"} aria-label={voice === "listening" ? L("listening") : L("tapToSpeak")}>
                <Icon name={voice === "listening" ? "stop" : "mic"} size={20} />
              </button>
              <form onSubmit={(e) => { e.preventDefault(); confirmConsent(codeInput, "typed"); }}>
                <input ref={codeRef} className="codein" value={codeInput} onChange={(e) => setCodeInput(e.target.value.replace(/\D/g, "").slice(0, 4))}
                  aria-label={L("orType")} placeholder="····" inputMode="numeric" autoComplete="one-time-code" maxLength={4} disabled={phase === "success"} />
                <button className="btn primary" disabled={busyNow || codeInput.length !== 4 || phase === "success"}>{L("confirm")}</button>
              </form>
              <button type="button" className="btn ghost" onClick={() => { shutUp(); setConsent(null); }} disabled={phase === "checking"}>{L("cancel")}</button>
            </div>
            <div className="mono small hash">action {String(consent.action_hash).slice(0, 28)}…</div>
          </div>
        </div>
      )}
    </div>
  );
}

function fmtINR(v: string): string {
  const n = Number(String(v).replace(/[,\s₹]/g, ""));
  return Number.isFinite(n) && String(v).trim() !== "" ? n.toLocaleString("en-IN") : v;
}

function summarize(e: any): string {
  const d = e.detail || {};
  switch (e.event) {
    case "document_read": return `${d.doc_type}: ${d.name_latin ?? ""}`;
    case "name_check": return `name ${d.name_status} → ${d.canonical ?? ""}`;
    case "voice_command": return `${d.intent ?? ""} ${Object.keys(d.slots || {}).join(", ")}`.trim();
    case "form_filled": return `values ${d.values_hash} · ${d.all_match ? "read-back matches" : "mismatch"}`;
    case "consent_requested": return `${d.action} (${d.risk}) · ${d.action_hash}`;
    case "consent_given": return `${d.method} · ${d.action_hash}`;
    case "consent_rejected": return d.reason || "";
    case "consent_refused": return (d.missing || []).join(", ");
    case "submit_failed": return (d.missing || []).join(", ") || d.error || "";
    case "application_submitted": return `${d.application_no} · ${d.action_hash}`;
    case "question_answered": return (d.sources || []).join(", ");
    default: return "";
  }
}
