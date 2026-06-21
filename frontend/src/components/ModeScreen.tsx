import { eyebrow, primaryBtn, SERIF } from "../ui";
import { Mode } from "../types";

type Props = {
  mode: Mode;
  onMode: (m: Mode) => void;
  onContinue: () => void;
};

const MODE_DEFS: { id: Mode; name: string; glyph: string; desc: string; tag: string }[] = [
  {
    id: "freeform",
    name: "Freeform",
    glyph: "✦",
    desc: "Start from a brief. No template — the deck is built end to end from your prompt and sources.",
    tag: "FASTEST TO FIRST DECK",
  },
  {
    id: "brand",
    name: "Brand",
    glyph: "◑",
    desc: "Upload a master deck. SlideForge extracts its identity and generates native-feeling new slides.",
    tag: "INHERITS BRAND DNA",
  },
  {
    id: "strict",
    name: "Strict",
    glyph: "▦",
    desc: "Preserve a rigid template. Only designated fields are filled, via formatting-safe XML edits.",
    tag: "GEOMETRY PRESERVED",
  },
];

const MODE_HINTS: Record<Mode, string> = {
  freeform: "No setup required — you go straight to the brief.",
  brand: "Next you’ll review the brand profile extracted from your master deck.",
  strict: "Next you’ll review the strict field schema before generating.",
};

export default function ModeScreen({ mode, onMode, onContinue }: Props) {
  return (
    <div className="sf-rise">
      <div style={eyebrow}>01 — NEW DECK</div>
      <h1
        style={{
          fontFamily: SERIF,
          fontWeight: 500,
          fontSize: 40,
          lineHeight: 1.1,
          letterSpacing: "-.02em",
          margin: "0 0 12px",
          maxWidth: "18ch",
        }}
      >
        How should SlideForge build this deck?
      </h1>
      <p
        style={{
          fontSize: 15,
          color: "var(--ink-2)",
          margin: "0 0 36px",
          maxWidth: "56ch",
          lineHeight: 1.55,
        }}
      >
        Every mode runs the same consulting pipeline — ghost deck, action titles, QA gates. They
        differ only in how much of an existing template is preserved.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}>
        {MODE_DEFS.map((m) => {
          const sel = mode === m.id;
          return (
            <div
              key={m.id}
              onClick={() => onMode(m.id)}
              style={{
                position: "relative",
                display: "flex",
                flexDirection: "column",
                padding: "22px 20px 20px",
                background: "var(--surface)",
                border: `1.5px solid ${sel ? "var(--accent)" : "var(--line)"}`,
                borderRadius: 10,
                cursor: "pointer",
                boxShadow: sel ? "var(--shadow)" : "none",
                transition: "border-color .15s, transform .15s",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 16,
                }}
              >
                <div
                  style={{
                    width: 34,
                    height: 34,
                    border: "1.5px solid var(--line-2)",
                    borderRadius: 7,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--ink-2)",
                  }}
                >
                  {m.glyph}
                </div>
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: "50%",
                    border: `1.5px solid ${sel ? "var(--accent)" : "var(--line-2)"}`,
                    background: sel ? "var(--accent)" : "transparent",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--accent-ink)",
                    fontSize: 11,
                  }}
                >
                  {sel ? "✓" : ""}
                </span>
              </div>
              <div style={{ fontFamily: SERIF, fontSize: 21, fontWeight: 600, marginBottom: 6 }}>
                {m.name}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: "var(--ink-2)",
                  lineHeight: 1.5,
                  marginBottom: 16,
                  flex: 1,
                }}
              >
                {m.desc}
              </div>
              <div
                style={{
                  fontFamily: "'IBM Plex Mono', monospace",
                  fontSize: 10,
                  letterSpacing: ".08em",
                  color: "var(--ink-3)",
                  borderTop: "1px solid var(--line)",
                  paddingTop: 12,
                }}
              >
                {m.tag}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 32,
          paddingTop: 24,
          borderTop: "1px solid var(--line)",
        }}
      >
        <div style={{ fontSize: 13, color: "var(--ink-2)", maxWidth: "42ch", lineHeight: 1.5 }}>
          {MODE_HINTS[mode]}
        </div>
        <button style={primaryBtn} onClick={onContinue}>
          {mode === "freeform" ? "Start brief" : "Set up template"}{" "}
          <span style={{ fontSize: 15 }}>→</span>
        </button>
      </div>
    </div>
  );
}
