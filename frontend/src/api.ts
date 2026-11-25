import type { Lang } from "./i18n";

async function j<T = any>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as any).error || `HTTP ${r.status}`);
  return data as T;
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
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "speech-to-text failed");
    return data as { text: string; engine: string };
  },

  async extract(file: Blob, name: string, lang: Lang) {
    const fd = new FormData();
    fd.append("image", file, name);
    fd.append("lang", lang);
    const r = await fetch("/api/extract", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "could not read document");
    return data;
  },
};

// ---------------------------------------------------------------- voice out
let current: HTMLAudioElement | null = null;
export async function speak(text: string, lang: Lang): Promise<string> {
  if (!text) return "";
  current?.pause();
  try {
    const r = await fetch("/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, lang }),
    });
    if (!r.ok) throw new Error("tts unavailable");
    const engine = r.headers.get("X-TTS-Engine") || "server";
    const url = URL.createObjectURL(await r.blob());
    current = new Audio(url);
    await new Promise<void>((res) => { current!.onended = () => res(); current!.onerror = () => res(); current!.play().catch(() => res()); });
    return engine;
  } catch {
    // last resort: the browser's own voice
    const u = new SpeechSynthesisUtterance(text);
    u.lang = { te: "te-IN", ta: "ta-IN", hi: "hi-IN", en: "en-IN" }[lang];
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
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
