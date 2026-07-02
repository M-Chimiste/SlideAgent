import { CSSProperties } from "react";
import { MONO, SERIF } from "../ui";
import { Theme } from "../types";

type Props = {
  theme: Theme;
  onTheme: (t: Theme) => void;
  onHome: () => void;
};

function seg(active: boolean): CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: 30,
    height: 26,
    borderRadius: 6,
    border: "none",
    cursor: "pointer",
    fontSize: 14,
    lineHeight: 1,
    background: active ? "var(--surface)" : "transparent",
    color: active ? "var(--accent)" : "var(--ink-3)",
    boxShadow: active ? "0 1px 2px rgba(0,0,0,.18)" : "none",
  };
}

export default function TopBar({ theme, onTheme, onHome }: Props) {
  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 20,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 28px",
        height: 60,
        background: "color-mix(in srgb, var(--paper) 86%, transparent)",
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          onClick={onHome}
          style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}
        >
          <div
            style={{
              width: 22,
              height: 22,
              border: "1.5px solid var(--ink)",
              borderRadius: 3,
              position: "relative",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div style={{ width: 10, height: 2, background: "var(--accent)" }} />
            <div
              style={{
                position: "absolute",
                bottom: 4,
                left: 4,
                width: 6,
                height: 2,
                background: "var(--ink-3)",
              }}
            />
          </div>
          <span
            style={{ fontFamily: SERIF, fontSize: 20, fontWeight: 600, letterSpacing: "-.01em" }}
          >
            SlideForge
          </span>
        </div>
        <span
          style={{
            fontFamily: MONO,
            fontSize: 10,
            letterSpacing: ".12em",
            color: "var(--ink-3)",
            border: "1px solid var(--line)",
            borderRadius: 4,
            padding: "3px 7px",
            marginLeft: 4,
          }}
        >
          LOCAL
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 3,
          height: 34,
          padding: 3,
          background: "var(--surface-2)",
          border: "1px solid var(--line)",
          borderRadius: 8,
        }}
      >
        <button title="Light" style={seg(theme === "light")} onClick={() => onTheme("light")}>
          ☀
        </button>
        <button title="Dark" style={seg(theme === "dark")} onClick={() => onTheme("dark")}>
          ☾
        </button>
      </div>
    </header>
  );
}
