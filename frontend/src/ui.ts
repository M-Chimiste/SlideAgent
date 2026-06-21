import { CSSProperties } from "react";

// ── type families ─────────────────────────────────────────────
export const SERIF = "'Newsreader', serif";
export const SANS = "'Hanken Grotesk', system-ui, sans-serif";
export const MONO = "'IBM Plex Mono', monospace";

// ── reusable fragments ────────────────────────────────────────
export const microLabel: CSSProperties = {
  fontFamily: MONO,
  fontSize: 10,
  letterSpacing: ".1em",
  color: "var(--ink-3)",
};

export const eyebrow: CSSProperties = {
  fontFamily: MONO,
  fontSize: 11,
  letterSpacing: ".18em",
  color: "var(--accent)",
  marginBottom: 14,
};

export const card: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--line)",
  borderRadius: 10,
  boxShadow: "var(--shadow)",
};

export const h1: CSSProperties = {
  fontFamily: SERIF,
  fontWeight: 500,
  fontSize: 36,
  lineHeight: 1.12,
  letterSpacing: "-.02em",
  margin: "0 0 10px",
};

export const primaryBtn: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 9,
  height: 46,
  padding: "0 26px",
  background: "var(--accent)",
  color: "var(--accent-ink)",
  border: "none",
  borderRadius: 8,
  font: "inherit",
  fontSize: 14,
  fontWeight: 700,
  cursor: "pointer",
  boxShadow: "var(--shadow)",
  whiteSpace: "nowrap",
};

export const ghostBtn: CSSProperties = {
  height: 44,
  padding: "0 18px",
  background: "transparent",
  border: "1px solid var(--line)",
  borderRadius: 8,
  color: "var(--ink-2)",
  font: "inherit",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

// segmented control button styles (active / idle)
export const segActive: CSSProperties = {
  flex: 1,
  padding: "8px 6px",
  borderRadius: 6,
  background: "var(--surface)",
  color: "var(--ink)",
  border: "1px solid var(--line-2)",
  font: "inherit",
  fontFamily: SANS,
  fontSize: 12.5,
  fontWeight: 700,
  cursor: "pointer",
  boxShadow: "0 1px 2px rgba(0,0,0,.06)",
};

export const segIdle: CSSProperties = {
  flex: 1,
  padding: "8px 6px",
  borderRadius: 6,
  background: "transparent",
  color: "var(--ink-3)",
  border: "1px solid transparent",
  font: "inherit",
  fontFamily: SANS,
  fontSize: 12.5,
  fontWeight: 600,
  cursor: "pointer",
};

export const segGroup: CSSProperties = {
  display: "flex",
  gap: 3,
  background: "var(--surface-2)",
  padding: 3,
  borderRadius: 8,
  border: "1px solid var(--line)",
};
