import { MONO } from "../ui";
import { Mode, Screen } from "../types";

type Props = {
  mode: Mode;
  screen: Screen;
  onJump: (screen: Screen) => void;
};

export default function Stepper({ mode, screen, onJump }: Props) {
  const flow: [Screen, string][] =
    mode === "freeform"
      ? [
          ["mode", "New"],
          ["brief", "Brief"],
          ["job", "Generate"],
          ["review", "Review"],
        ]
      : [
          ["mode", "New"],
          ["setup", "Setup"],
          ["brief", "Brief"],
          ["job", "Generate"],
          ["review", "Review"],
        ];

  const order = flow.map((f) => f[0]);
  const cur = order.indexOf(screen);

  return (
    <nav
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "14px 28px",
        borderBottom: "1px solid var(--line)",
        overflowX: "auto",
      }}
    >
      {flow.map(([id, label], i) => {
        const done = i < cur;
        const active = i === cur;
        return (
          <div key={id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div
              onClick={() => {
                if (i < cur) onJump(id);
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 9,
                cursor: i <= cur ? "pointer" : "default",
                padding: "5px 4px",
                whiteSpace: "nowrap",
                opacity: i <= cur ? 1 : 0.5,
              }}
            >
              <span
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 21,
                  height: 21,
                  borderRadius: "50%",
                  fontFamily: MONO,
                  fontSize: 11,
                  fontWeight: 500,
                  border: `1.5px solid ${
                    active ? "var(--accent)" : done ? "var(--ink)" : "var(--line-2)"
                  }`,
                  background: active ? "var(--accent)" : done ? "var(--ink)" : "transparent",
                  color: active ? "var(--accent-ink)" : done ? "var(--paper)" : "var(--ink-3)",
                }}
              >
                {done ? "✓" : String(i + 1)}
              </span>
              <span
                style={{
                  fontSize: 12.5,
                  fontWeight: 600,
                  letterSpacing: ".01em",
                  color: active ? "var(--ink)" : "var(--ink-2)",
                }}
              >
                {label}
              </span>
            </div>
            {i < flow.length - 1 && (
              <span style={{ color: "var(--line-2)", fontSize: 12, margin: "0 2px" }}>·</span>
            )}
          </div>
        );
      })}
    </nav>
  );
}
