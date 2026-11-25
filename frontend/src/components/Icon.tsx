// Small inline SVG icon set (stroke icons, 24px grid). Decorative by default.
const P: Record<string, string> = {
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
  stop: "M7 7h10v10H7z",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
  check: "M5 12l5 5L20 7",
  alert: "M12 9v4M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  play: "M8 5v14l11-7z",
  refresh: "M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 4v4.5h4.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M20 20v-4.5h-4.5",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01",
  pen: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  chain: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  text: "M4 7V5h10v2M9 5v14M7 19h4M14 12v-1h6v1M17 11v8M15.5 19h3",
  plus: "M12 5v14M5 12h14",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  vol: "M4 9v6h4l5 4V5L8 9zM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12",
  volOff: "M4 9v6h4l5 4V5L8 9zM17 9l5 6M22 9l-5 6",
  skip: "M6 5l9 7-9 7zM18 5v14",
  x: "M6 6l12 12M18 6L6 18",
  send: "M4 12h15M13 6l6 6-6 6",
  arrow: "M5 12h14M13 6l6 6-6 6",
};

export default function Icon({ name, size = 18, label }: { name: keyof typeof P | string; size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={label ? undefined : true} role={label ? "img" : undefined}
      aria-label={label} style={{ flex: "none", verticalAlign: "-0.2em" }}>
      <path d={P[name] || ""} />
    </svg>
  );
}
