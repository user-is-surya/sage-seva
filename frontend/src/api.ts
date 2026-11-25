import type { Lang } from "./i18n";

async function j<T = any>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(friendly((data as any).error, r.status));
  return data as T;
}

export function friendly(msg: unknown, status?: number): string {
  const s = typeof msg === "string" ? msg : "";
  if (s && s.length < 240 && !/Traceback|File "|Exception|\bat \w+\.|Error:/.test(s)) return s;
  if (status && status >= 500) return "Something went wrong on our side. Please try again.";
  return "That didn't work. Please try again.";
}

export const api = {
  health: () => j("/api/health"),
  skill: (id = "income_certificate") => j(`/api/skills/${id}`),
  agent: (text: string, lang: Lang, state: unknown) => j("/api/agent", { text, lang, state }),
  ask: (question: string, lang: Lang, docs_present: string[]) => j("/api/ask", { question, lang, docs_present }),
  reconcile: (docs: unknown[], lang: Lang) => j("/api/reconcile", { docs, lang }),
  fill: (values: Record<string, string>) => j("/api/fill", { values }),
  challenge: (lang: Lang) => j("/api/consent/challenge", { lang }),
  verifyConsent: (challenge_id: string, heard: string, method: string) =>
    j("/api/consent/verify", { challenge_id, heard, method }),
  audit: () => j("/api/audit"),
  resetAudit: () => j("/api/audit/reset", {}),

  async stt(blob: Blob, lang: Lang) {
    const fd = new FormData();
    fd.append("audio", blob, "speech.webm");
    fd.append("lang", lang);
    const r = await fetch("/api/stt", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(friendly(data.error || "I couldn't hear that. Please try again.", r.status));
    return data as { text: string; engine: string };
  },

  async extract(file: Blob, name: string, lang: Lang) {
    const fd = new FormData();
    fd.append("image", file, name);
    fd.append("lang", lang);
    const r = await fetch("/api/extract", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(friendly(data.error || "Could not read this document.", r.status));
    return data;
  },
};

// ---------------------------------------------------------------- voice out
let current: HTMLAudioElement | null = null;
let finishCurrent: (() => void) | null = null;
let speakToken = 0;
const MUTE_KEY = "seva.muted";
export let muted = (() => { try { return localStorage.getItem(MUTE_KEY) === "1"; } catch { return false; } })();
export function setMuted(v: boolean) {
  muted = v;
  try { localStorage.setItem(MUTE_KEY, v ? "1" : "0"); } catch { /* ignore */ }
  if (v) stopSpeaking();
}

/** Stop any voice output immediately (server audio, pending fetch, browser voice). */
export function stopSpeaking() {
  speakToken++;
  try { current?.pause(); } catch { /* ignore */ }
  current = null;
  try { window.speechSynthesis?.cancel(); } catch { /* ignore */ }
  const f = finishCurrent; finishCurrent = null; f?.();
}

/** Speak a short line. Resolves when finished OR stopped. Returns engine name ("" if skipped). */
export async function speak(text: string, lang: Lang): Promise<string> {
  if (!text || muted) return "";
  stopSpeaking();
  const my = ++speakToken;
  try {
    const r = await fetch("/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, lang }),
    });
    if (!r.ok) throw new Error("tts unavailable");
    const engine = r.headers.get("X-TTS-Engine") || "server";
    const blob = await r.blob();
    if (my !== speakToken || muted) return "";
    const url = URL.createObjectURL(blob);
    const a = new Audio(url);
    current = a;
    await new Promise<void>((res) => {
      finishCurrent = res;
      a.onended = () => res(); a.onerror = () => res();
      a.play().catch(() => res());
    });
    finishCurrent = null;
    URL.revokeObjectURL(url);
    return engine;
  } catch {
    if (my !== speakToken || muted || !("speechSynthesis" in window)) return "";
    const u = new SpeechSynthesisUtterance(text);
    u.lang = { te: "te-IN", ta: "ta-IN", hi: "hi-IN", en: "en-IN" }[lang];
    await new Promise<void>((res) => {
      finishCurrent = res;
      u.onend = () => res(); u.onerror = () => res();
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    });
    finishCurrent = null;
    return "browser";
  }
}

// ---------------------------------------------------------------- voice in
export class Recorder {
  private rec?: MediaRecorder;
  private chunks: Blob[] = [];
  private ctx?: AudioContext;
  private raf = 0;
  onLevel?: (v: number) => void;

  async start() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    this.chunks = [];
    this.rec = new MediaRecorder(stream, { mimeType: "audio/webm" });
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.rec.start();
    this.ctx = new AudioContext();
    const an = this.ctx.createAnalyser();
    an.fftSize = 512;
    this.ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let s = 0;
      for (const b of buf) s += ((b - 128) / 128) ** 2;
      this.onLevel?.(Math.min(1, Math.sqrt(s / buf.length) * 4));
      this.raf = requestAnimationFrame(tick);
    };
    tick();
  }

  stop(): Promise<Blob> {
    return new Promise((res) => {
      if (!this.rec) return res(new Blob());
      this.rec.onstop = () => {
        this.rec!.stream.getTracks().forEach((t) => t.stop());
        cancelAnimationFrame(this.raf);
        this.ctx?.close();
        this.onLevel?.(0);
        res(new Blob(this.chunks, { type: "audio/webm" }));
      };
      this.rec.stop();
    });
  }
}
