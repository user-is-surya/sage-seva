import { useCallback, useEffect, useRef, useState } from "react";
import Orb, { type VoiceState } from "./components/Orb";
import { api, Recorder, speak } from "./api";
import { EVENT_LABEL, LANGS, t, type Lang } from "./i18n";

type Msg = { who: "you" | "seva"; text: string; meta?: string };
type Doc = Record<string, any> & { thumb?: string; file?: string };
const SAMPLES = ["1_identity_card.png", "2_ration_card.png", "3_voter_id.png"];
const VERDICT: Record<string, { label: string; cls: string }> = {
  identical: { label: "identical", cls: "ok" },
  initial_vs_full: { label: "initials vs full name", cls: "warn" },
  same_name_different_spelling: { label: "same name, different spelling", cls: "warn" },
  possible_match_check: { label: "check manually", cls: "warn" },
  different: { label: "different name", cls: "bad" },
};

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [big, setBig] = useState(false);
  const [voice, setVoice] = useState<VoiceState>("armed");
  const [level, setLevel] = useState(0);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [typed, setTyped] = useState("");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [reading, setReading] = useState(0);
  const [guard, setGuard] = useState<any>(null);
  const [slots, setSlots] = useState<Record<string, string>>({ occupation: "", annual_income: "", purpose: "", mobile: "" });
  const [answer, setAnswer] = useState<any>(null);
  const [readBack, setReadBack] = useState<any>(null);
  const [consent, setConsent] = useState<any>(null);
  const [consentErr, setConsentErr] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [result, setResult] = useState<any>(null);
  const [audit, setAudit] = useState<any>({ entries: [], verify: { ok: true, count: 0 } });
  const [busy, setBusy] = useState("");
  const [health, setHealth] = useState<any>(null);
  const rec = useRef<Recorder | null>(null);
  const consentRef = useRef<any>(null);
  consentRef.current = consent;
  const L = (k: string) => t(lang, k);

  const refreshAudit = useCallback(() => api.audit().then(setAudit).catch(() => {}), []);
  useEffect(() => { api.health().then(setHealth).catch(() => {}); refreshAudit(); }, [refreshAudit]);

  const say = useCallback(async (text: string, meta?: string) => {
    if (!text) return;
    setMsgs((m) => [...m, { who: "seva", text, meta }]);
    setVoice("speaking");
    await speak(text, lang);
    setVoice("armed");
  }, [lang]);

  const step = result ? 5 : consent ? 5 : readBack ? 4 : slots.annual_income ? 3 : guard ? 2 : docs.length ? 1 : 0;

  // ------------------------------------------------------------ documents
  async function readDocs(files: { blob: Blob; name: string; thumb: string }[]) {
    setReading(files.length);
    const out: Doc[] = [...docs];
    await Promise.all(files.map(async (f) => {
      try {
        const d = await api.extract(f.blob, f.name, lang);
        out.push({ ...d, thumb: f.thumb, file: f.name });
        setDocs([...out]);
      } catch (e: any) {
        setMsgs((m) => [...m, { who: "seva", text: `⚠ ${f.name}: ${e.message}` }]);
      }
      setReading((r) => r - 1);
    }));
    refreshAudit();
    if (out.length) {
      const g = await api.reconcile(out, lang);
      setGuard(g);
      refreshAudit();
      if (g.spoken) say(g.spoken);
    }
  }

  async function useSamples() {
    const files = await Promise.all(SAMPLES.map(async (n) => {
      const blob = await (await fetch(`/samples/${n}`)).blob();
      return { blob, name: n, thumb: `/samples/${n}` };
    }));
    setDocs([]);
    await readDocs(files);
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []).map((f) => ({ blob: f, name: f.name, thumb: URL.createObjectURL(f) }));
    if (files.length) readDocs(files);
    e.target.value = "";
  }

  // ------------------------------------------------------------ form values
  function formValues(): Record<string, string> {
    const primary = docs.find((d) => d.doc_type === "identity_card") || docs[0] || {};
    const pick = (k: string) => primary[k] || docs.find((d) => d[k])?.[k] || "";
    return {
      applicant_name: guard?.name?.canonical || pick("name_latin"),
      father_name: guard?.father?.canonical || pick("father_name_latin"),
      dob: pick("dob"), gender: pick("gender"), address: pick("address"),
      district: pick("district"), state: pick("state"), id_last4: pick("id_last4"),
      occupation: slots.occupation, annual_income: slots.annual_income, purpose: slots.purpose, mobile: slots.mobile,
    };
  }

  async function doFill() {
    setBusy("fill");
    try {
      const r = await api.fill(formValues());
      setReadBack(r);
      refreshAudit();
      const ok = r.all_match && !r.missing_required.length;
      const msg = { te: ok ? "ఫారం నింపాను. ప్రతి ఫీల్డ్‌ను ఫారం నుండి తిరిగి చదివి సరిచూశాను." : "ఫారం నింపాను, కానీ కొన్ని ఫీల్డ్‌లు తనిఖీ చేయాలి.",
        ta: ok ? "படிவத்தை நிரப்பினேன். ஒவ்வொரு புலத்தையும் படிவத்திலிருந்து மீண்டும் படித்து சரிபார்த்தேன்." : "படிவத்தை நிரப்பினேன், சில புலங்களைச் சரிபார்க்க வேண்டும்.",
        hi: ok ? "फ़ॉर्म भर दिया। हर फ़ील्ड को फ़ॉर्म से वापस पढ़कर जाँचा।" : "फ़ॉर्म भर दिया, लेकिन कुछ फ़ील्ड जाँचने होंगे।",
        en: ok ? "Form filled. I read every field back from the page and it matches." : "Form filled, but some fields need checking." }[lang];
      say(msg);
    } catch (e: any) { say(`⚠ ${e.message}`); }
    setBusy("");
  }

  async function startConsent() {
    setBusy("consent");
    setConsentErr(""); setCodeInput("");
    try {
      const c = await api.challenge(lang);
      setConsent(c);
      refreshAudit();
      say(c.spoken);
    } catch (e: any) { say(`⚠ ${e.message}`); }
    setBusy("");
  }

  async function confirmConsent(heard: string, method: string) {
    const c = consentRef.current;
    if (!c) return;
    setBusy("verify");
    try {
      const r = await api.verifyConsent(c.challenge_id, heard, method);
      if (r.ok) {
        setResult(r); setConsent(null);
        const done = { te: `దరఖాస్తు సమర్పించబడింది. మీ దరఖాస్తు సంఖ్య ${r.application_no}.`,
          ta: `விண்ணப்பம் சமர்ப்பிக்கப்பட்டது. உங்கள் விண்ணப்ப எண் ${r.application_no}.`,
          hi: `आवेदन जमा हो गया। आपका आवेदन नंबर ${r.application_no} है।`,
          en: `Application submitted. Your application number is ${r.application_no}.` }[lang];
        say(done);
      } else {
        setConsentErr(r.reason === "action_changed" ? L("changed") : `${L("codeWrong")}${r.heard_digits ? ` (${r.heard_digits})` : ""}`);
      }
      refreshAudit();
    } catch (e: any) { setConsentErr(e.message); }
    setBusy("");
  }

  async function askDocs(q?: string) {
    setBusy("ask");
    try {
      const r = await api.ask(q || "Which documents are required and what is missing?", lang, docs.map((d) => d.label || d.doc_type));
      setAnswer(r); refreshAudit(); say(r.answer);
    } catch (e: any) { say(`⚠ ${e.message}`); }
    setBusy("");
  }

  // ------------------------------------------------------------ voice turn
  async function handleText(text: string, engine?: string) {
    if (!text.trim()) return;
    setMsgs((m) => [...m, { who: "you", text, meta: engine }]);
    if (consentRef.current) { await confirmConsent(text, "voice"); return; }
    setVoice("thinking");
    try {
      const state = { step, documents: docs.map((d) => d.label), name_status: guard?.name?.status, slots, filled: !!readBack };
      const r: any = await api.agent(text, lang, state);
      const s = r.slots || {};
      if (Object.keys(s).length) setSlots((p) => ({ ...p, ...Object.fromEntries(Object.entries(s).filter(([, v]) => v).map(([k, v]) => [k, String(v)])) }));
      refreshAudit();
      setVoice("armed");
      if (r.intent === "ask_question") return askDocs(r.question);
      await say(r.reply, r.engine);
      if (r.intent === "fill_form") doFill();
      if (r.intent === "submit") startConsent();
    } catch (e: any) { setVoice("armed"); say(`⚠ ${e.message}`); }
  }

  async function toggleMic() {
    if (voice === "listening") {
      setVoice("thinking");
      const blob = await rec.current!.stop();
      try {
        const r = await api.stt(blob, lang);
        await handleText(r.text, r.engine);
      } catch (e: any) { say(`⚠ ${e.message}`); }
      setVoice("armed");
      return;
    }
    rec.current = new Recorder();
    rec.current.onLevel = setLevel;
    try { await rec.current.start(); setVoice("listening"); } catch (e: any) { say(`⚠ microphone: ${e.message}`); }
  }

  async function newSession() {
    await api.resetAudit();
    setDocs([]); setGuard(null); setReadBack(null); setConsent(null); setResult(null); setAnswer(null); setMsgs([]);
    setSlots({ occupation: "", annual_income: "", purpose: "", mobile: "" });
    refreshAudit();
  }

  const v = audit.verify || {};
  return (
    <div className={`app ${big ? "big" : ""} lang-${lang}`}>
      <div className="sage-ground" />
      <header className="top">
        <div className="brand">
          <div className="mark">S</div>
          <div>
            <div className="name">SAGE <span>Seva</span></div>
            <div className="tag">{L("tagline")}</div>
          </div>
        </div>
        <div className="controls">
          <div className="langs">
            {LANGS.map((l) => (
              <button key={l.id} className={l.id === lang ? "on" : ""} onClick={() => setLang(l.id)}>{l.label}</button>
            ))}
          </div>
          <button className="ghost" onClick={() => setBig(!big)}>{L("bigText")}</button>
          <span className={`chain ${v.ok ? "ok" : "bad"}`}>{v.ok ? "⛓ " + L("chainOk") : "⚠ " + L("chainBroken")} · {v.count} {L("entries")}</span>
          <button className="ghost" onClick={newSession}>{L("newSession")}</button>
        </div>
      </header>

      <main className="grid">
        {/* ------------------------------------------------ assistant */}
        <section className="panel assistant">
          <h2>{L("assistant")}</h2>
          <div className="orb-wrap" onClick={toggleMic}>
            <Orb state={voice} level={level} />
          </div>
          <button className={`mic ${voice}`} onClick={toggleMic} disabled={voice === "thinking" || voice === "speaking"}>
            {voice === "listening" ? "■ " + L("listening") : voice === "thinking" ? L("thinking") : "🎙 " + L("tapToSpeak")}
          </button>
          <div className="chat">
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.who}`}>
                <div>{m.text}</div>
                {m.meta && <div className="meta">{m.meta}</div>}
              </div>
            ))}
          </div>
          <form className="typer" onSubmit={(e) => { e.preventDefault(); const x = typed; setTyped(""); handleText(x); }}>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={L("typeHere")} />
            <button>{L("send")}</button>
          </form>
        </section>

        {/* ------------------------------------------------ application */}
        <section className="panel app-col">
          <h2>{L("application")} · <span className="svc">{L("service")}</span></h2>
          <ol className="steps">
            {["s1", "s2", "s3", "s4", "s5"].map((k, i) => (
              <li key={k} className={step > i ? "done" : step === i ? "now" : ""}><b>{i + 1}</b>{L(k)}</li>
            ))}
          </ol>

          <div className="card">
            <div className="row">
              <label className="btn">{L("addDocs")}<input type="file" accept="image/*" multiple hidden onChange={onPick} /></label>
              <button className="btn ghost" onClick={useSamples}>{L("useSamples")}</button>
              {reading > 0 && <span className="pulse">{L("reading")} ({reading})</span>}
            </div>
            {docs.length > 0 && (
              <div className="docs">
                {docs.map((d, i) => (
                  <div className="doc" key={i}>
                    {d.thumb && <img src={d.thumb} alt="" />}
                    <div>
                      <div className="dlabel">{d.label || d.doc_type}</div>
                      <div className="dname">{d.name_native}</div>
                      <div className="dlatin">{d.name_latin}</div>
                      <div className="dmeta">{d.dob} {d.id_number && `· ${d.id_number}`}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {guard?.name?.canonical && (
            <div className={`card guard ${guard.name.status}`}>
              <h3>{L("nameCheck")}</h3>
              <div className="canon">
                <span className="k">{L("willType")}</span>
                <span className="v">{guard.name.canonical}</span>
                <span className="src">{L("from")}: {guard.name.canonical_source}</span>
              </div>
              <table className="variants">
                <tbody>
                  {guard.name.variants.map((x: any, i: number) => (
                    <tr key={i}>
                      <td>{x.label}{x.primary && <em> · {L("primary")}</em>}</td>
                      <td className="mono">
                        {x.diff?.length ? x.diff.map((d: any, j: number) => (
                          <span key={j} className={d.same ? "same" : "diff"} title={d.expected ? `expected ${d.expected}` : "extra"}>{d.found ?? `∅(${d.expected})`} </span>
                        )) : x.value}
                      </td>
                      <td><span className={`chip ${VERDICT[x.verdict]?.cls}`}>{VERDICT[x.verdict]?.label}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="spell">
                <span className="k">{L("spellBack")}</span>
                <span className="v">{guard.name.spell_back}</span>
                <button className="btn small" onClick={() => say(guard.spoken)}>▶ {L("play")}</button>
              </div>
              {guard.father?.canonical && <div className="minor">Father: <b>{guard.father.canonical}</b> · <span className={`chip ${guard.father.status === "consistent" ? "ok" : "warn"}`}>{guard.father.status}</span> · DOB {guard.dob?.consistent ? "✓ consistent" : "⚠ differs"}</div>}
            </div>
          )}

          <div className="card">
            <h3>{L("details")}</h3>
            <div className="slots">
              {(["occupation", "annual_income", "purpose", "mobile"] as const).map((k) => (
                <label key={k}><span>{L(k)}</span>
                  <input value={slots[k]} onChange={(e) => setSlots({ ...slots, [k]: e.target.value })} />
                </label>
              ))}
            </div>
            <div className="row">
              <button className="btn ghost" onClick={() => askDocs()} disabled={busy === "ask"}>❓ {L("askDocs")}</button>
              <button className="btn" onClick={doFill} disabled={!docs.length || busy === "fill"}>{busy === "fill" ? "…" : "✎ " + L("fill")}</button>
            </div>
            {answer && (
              <div className="answer">
                <div>{answer.answer}</div>
                {answer.missing?.length > 0 && <div className="minor">{L("missing")}: {answer.missing.join(", ")}</div>}
                {answer.sources?.length > 0 && <div className="minor">{L("sources")}: {answer.sources.join(" · ")} (skill pack: income_certificate/knowledge.md)</div>}
              </div>
            )}
          </div>

          {readBack && (
            <div className="card">
              <h3>{L("readBack")} {readBack.all_match ? <span className="chip ok">✓ all match</span> : <span className="chip warn">check</span>}</h3>
              <table className="rb">
                <thead><tr><th></th><th>{L("intended")}</th><th>{L("onPage")}</th><th></th></tr></thead>
                <tbody>
                  {readBack.rows.filter((r: any) => r.intended || r.on_page || r.required).map((r: any) => (
                    <tr key={r.id} className={r.match ? "" : "mis"}>
                      <td>{r.label}</td><td>{r.intended}</td><td>{r.on_page}</td><td>{r.match ? "✓" : r.required && !r.on_page ? "missing" : "≠"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!result && <button className="btn primary" onClick={startConsent} disabled={busy === "consent"}>🔒 {L("submit")}</button>}
            </div>
          )}

          {result && (
            <div className="card success">
              <h3>✓ {L("submitted")}</h3>
              <div className="appno">{result.application_no}</div>
            </div>
          )}
        </section>

        {/* ------------------------------------------------ receipts */}
        <section className="panel receipts">
          <h2>{L("receipts")}</h2>
          <button className="btn small ghost" onClick={refreshAudit}>↻ {L("verify")}</button>
          <div className={`verify ${v.ok ? "ok" : "bad"}`}>
            {v.ok ? `⛓ ${L("chainOk")} · ${v.count}` : `⚠ ${L("chainBroken")} @ #${v.broken_at}: ${v.reason}`}
            {v.head && <div className="mono small">head {String(v.head).slice(0, 16)}…</div>}
          </div>
          <ol className="timeline">
            {[...(audit.entries || [])].reverse().map((e: any) => (
              <li key={e.seq} className={`ev ${e.event} ${v.broken_at && e.seq >= v.broken_at ? "broken" : ""}`}>
                <div className="evh"><b>#{e.seq}</b> {EVENT_LABEL[e.event] || e.event}<span className="who">{e.actor}</span></div>
                <div className="evd">{summarize(e)}</div>
                <div className="mono small">{e.hash?.slice(0, 12)} ← {e.prev?.slice(0, 8)}</div>
              </li>
            ))}
          </ol>
          {health && (
            <div className="engines mono small">
              text: {health.models?.text}<br />tts: {health.models?.tts || "edge-tts"}<br />
              {Object.entries(health.last_used || {}).map(([k, x]) => <span key={k}>{k}→{String(x)}<br /></span>)}
            </div>
          )}
        </section>
      </main>

      {consent && (
        <div className="modal">
          <div className="sheet">
            <h2>🔒 {L("consentTitle")}</h2>
            <p className="spoken">{consent.spoken}</p>
            <div className="code-label">{L("sayCode")}</div>
            <div className="code">{consent.code}</div>
            <div className="mono small">action hash {String(consent.action_hash).slice(0, 24)}…</div>
            <div className="row center">
              <button className={`mic ${voice}`} onClick={toggleMic}>{voice === "listening" ? "■ " + L("listening") : "🎙 " + L("tapToSpeak")}</button>
            </div>
            <form className="row center" onSubmit={(e) => { e.preventDefault(); confirmConsent(codeInput, "typed"); }}>
              <input className="codein" value={codeInput} onChange={(e) => setCodeInput(e.target.value)} placeholder={L("orType")} inputMode="numeric" maxLength={4} />
              <button className="btn primary" disabled={busy === "verify"}>{L("confirm")}</button>
              <button type="button" className="btn ghost" onClick={() => setConsent(null)}>{L("cancel")}</button>
            </form>
            {consentErr && <div className="err">{consentErr}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function summarize(e: any): string {
  const d = e.detail || {};
  switch (e.event) {
    case "document_read": return `${d.doc_type}: ${d.name_latin ?? ""}`;
    case "name_check": return `name ${d.name_status} → ${d.canonical ?? ""}`;
    case "voice_command": return `${d.intent} ${Object.keys(d.slots || {}).join(", ")}`;
    case "form_filled": return `values ${d.values_hash} · ${d.all_match ? "read-back matches" : "mismatch"}`;
    case "consent_requested": return `${d.action} (${d.risk}) · ${d.action_hash}`;
    case "consent_given": return `${d.method} · ${d.action_hash}`;
    case "consent_rejected": return d.reason;
    case "application_submitted": return `${d.application_no} · ${d.action_hash}`;
    case "question_answered": return (d.sources || []).join(", ");
    default: return "";
  }
}
