import { useEffect, useMemo, useRef } from "react";
// Reused from S.A.G.E (components/Orb.tsx) unchanged apart from this import.
export type VoiceState = "off" | "armed" | "listening" | "thinking" | "speaking";

interface Props {
  state: VoiceState;
  level: number; // 0..1 — mic when listening, tts when speaking
  calm?: boolean; // reduce motion / particle count
}

// per-state look: [core RGB], spin speed, turbulence, glow
const LOOK: Record<
  VoiceState,
  { rgb: [number, number, number]; rgb2: [number, number, number]; spin: number; turb: number; glow: number }
> = {
  off: { rgb: [90, 170, 210], rgb2: [40, 90, 130], spin: 0.0016, turb: 0.05, glow: 0.34 },
  armed: { rgb: [120, 210, 240], rgb2: [50, 120, 160], spin: 0.0026, turb: 0.09, glow: 0.5 },
  listening: { rgb: [70, 235, 255], rgb2: [30, 150, 200], spin: 0.005, turb: 0.22, glow: 0.8 },
  thinking: { rgb: [255, 190, 120], rgb2: [150, 90, 220], spin: 0.011, turb: 0.3, glow: 0.85 },
  speaking: { rgb: [90, 225, 245], rgb2: [40, 140, 190], spin: 0.006, turb: 0.16, glow: 0.78 },
};

type P3 = { x: number; y: number; z: number };

function fibSphere(n: number): P3[] {
  const pts: P3[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const th = golden * i;
    pts.push({ x: Math.cos(th) * r, y, z: Math.sin(th) * r });
  }
  return pts;
}

/** k-nearest-neighbour edge list over the sphere points (built once). */
function knnEdges(pts: P3[], k: number): [number, number][] {
  const edges = new Set<string>();
  for (let i = 0; i < pts.length; i++) {
    const d: { j: number; dd: number }[] = [];
    for (let j = 0; j < pts.length; j++) {
      if (j === i) continue;
      const dx = pts[i].x - pts[j].x;
      const dy = pts[i].y - pts[j].y;
      const dz = pts[i].z - pts[j].z;
      d.push({ j, dd: dx * dx + dy * dy + dz * dz });
    }
    d.sort((a, b) => a.dd - b.dd);
    for (let m = 0; m < k; m++) {
      const j = d[m].j;
      edges.add(i < j ? `${i},${j}` : `${j},${i}`);
    }
  }
  return [...edges].map((s) => s.split(",").map(Number) as [number, number]);
}

export default function Orb({ state, level, calm = false }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const N = calm ? 320 : 620;
  const geom = useMemo(() => {
    const pts = fibSphere(N);
    return { pts, edges: knnEdges(pts, calm ? 2 : 3) };
  }, [N, calm]);
  const anim = useRef({ yaw: 0, pitch: 0, t: 0, lvl: 0, glow: 0.3, turb: 0, spin: 0, raf: 0 });
  const stateRef = useRef(state);
  stateRef.current = state;
  const levelRef = useRef(level);
  levelRef.current = level;

  useEffect(() => {
    const cv = ref.current!;
    const ctx = cv.getContext("2d")!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const resize = () => {
      const s = Math.min(cv.clientWidth, cv.clientHeight);
      cv.width = s * dpr;
      cv.height = s * dpr;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(cv);

    const a = anim.current;
    const { pts, edges } = geom;
    const proj = pts.map(() => ({ x: 0, y: 0, z: 0, s: 0 }));

    const draw = () => {
      const w = cv.width;
      const h = cv.height;
      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) * 0.3;
      const st = stateRef.current;
      const L = LOOK[st];
      const lvl = st === "listening" || st === "speaking" ? levelRef.current : 0;

      a.t += 0.016;
      a.lvl += (lvl - a.lvl) * 0.18;
      // Clamp the glow: a loud spell (SAGE's own voice, an echo burst) used to
      // push this past 1, and the white core stop below then blew out to a
      // near-solid white disc for a few frames — the "white flash".
      a.glow += (Math.min(0.95, L.glow + a.lvl * 0.3) - a.glow) * 0.08;
      a.turb += (L.turb - a.turb) * 0.06;
      a.spin += (L.spin - a.spin) * 0.05;
      a.yaw += a.spin * (calm ? 0.5 : 1) * 16;
      a.pitch = Math.sin(a.t * 0.3) * 0.28;

      const cosY = Math.cos(a.yaw);
      const sinY = Math.sin(a.yaw);
      const cosP = Math.cos(a.pitch);
      const sinP = Math.sin(a.pitch);
      const breathe = 1 + 0.03 * Math.sin(a.t * (st === "off" ? 0.7 : 1.6)) + a.lvl * 0.14;

      // project every point
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        // per-point turbulence (radial noise)
        const nz =
          Math.sin(p.x * 4 + a.t * 1.7) * 0.5 +
          Math.sin(p.y * 5 - a.t * 1.3) * 0.3 +
          Math.sin(p.z * 7 + a.yaw) * 0.2;
        const rr = 1 + nz * a.turb * (0.25 + a.lvl * 0.9);
        let x = p.x * rr;
        let y = p.y * rr;
        let z = p.z * rr;
        // yaw then pitch
        let x1 = x * cosY - z * sinY;
        let z1 = x * sinY + z * cosY;
        let y1 = y * cosP - z1 * sinP;
        let z2 = y * sinP + z1 * cosP;
        const persp = 1 / (2.4 - z2); // z2 in [-~1.3, ~1.3]
        proj[i].x = cx + x1 * R * breathe * persp * 2.4;
        proj[i].y = cy + y1 * R * breathe * persp * 2.4;
        proj[i].z = z2;
        proj[i].s = persp * dpr;
      }

      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";

      // outer halo
      const halo = ctx.createRadialGradient(cx, cy, R * 0.3, cx, cy, R * 2.7);
      halo.addColorStop(0, `rgba(${L.rgb[0]},${L.rgb[1]},${L.rgb[2]},${0.16 * a.glow})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, w, h);

      // plexus edges
      ctx.lineWidth = 1 * dpr;
      for (let e = 0; e < edges.length; e++) {
        const [i, j] = edges[e];
        const pi = proj[i];
        const pj = proj[j];
        const zf = (pi.z + pj.z) / 2; // -1.3 .. 1.3
        if (zf < -0.15) continue; // hide far back edges
        const alpha = Math.max(0, (zf + 0.4) / 1.7) * 0.5 * (0.4 + a.glow);
        const [r, g, b] = zf > 0.3 ? L.rgb : L.rgb2;
        ctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.beginPath();
        ctx.moveTo(pi.x, pi.y);
        ctx.lineTo(pj.x, pj.y);
        ctx.stroke();
      }

      // points
      for (let i = 0; i < pts.length; i++) {
        const p = proj[i];
        const front = (p.z + 1.3) / 2.6; // 0..1
        const rad = (0.7 + front * 1.9) * p.s;
        const [r, g, b] = front > 0.55 ? L.rgb : L.rgb2;
        ctx.fillStyle = `rgba(${r},${g},${b},${0.25 + front * 0.7})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, rad, 0, Math.PI * 2);
        ctx.fill();
      }

      // rotating arc segments
      ctx.lineWidth = 2 * dpr;
      for (let k = 0; k < 3; k++) {
        const rr = R * (1.55 + k * 0.16);
        const off = a.yaw * (k % 2 ? -1.4 : 1.1) + k * 2;
        const span = 0.7 + k * 0.25;
        ctx.strokeStyle = `rgba(${L.rgb[0]},${L.rgb[1]},${L.rgb[2]},${(0.5 - k * 0.12) * a.glow})`;
        ctx.beginPath();
        ctx.arc(cx, cy, rr, off, off + span);
        ctx.stroke();
      }

      // core bloom
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.9);
      core.addColorStop(0, `rgba(255,255,255,${0.4 * a.glow})`);
      core.addColorStop(0.35, `rgba(${L.rgb[0]},${L.rgb[1]},${L.rgb[2]},${0.3 * a.glow})`);
      core.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.9, 0, Math.PI * 2);
      ctx.fill();

      ctx.globalCompositeOperation = "source-over";
      a.raf = requestAnimationFrame(draw);
    };
    a.raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(a.raf);
      ro.disconnect();
    };
  }, [geom, calm]);

  return <canvas ref={ref} className="h-full w-full" />;
}
