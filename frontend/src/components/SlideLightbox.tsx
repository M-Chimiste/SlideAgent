import { CSSProperties } from "react";
import { JobStatus, previewImageUrl } from "../api/client";
import { slideIssues } from "../qa";

const MONO = "'IBM Plex Mono', monospace";

type Props = {
  jobId: string;
  status: JobStatus;
  index: number;
  regening: boolean;
  regenError: string | null;
  onClose: () => void;
  onRegen: () => void;
};

function qaBadge(ok: boolean): { label: string; bg: string; ink: string } {
  return ok
    ? { label: "PASS", bg: "var(--good-soft)", ink: "var(--good)" }
    : { label: "WARNING", bg: "var(--warn-soft)", ink: "var(--warn)" };
}

export default function SlideLightbox({
  jobId,
  status,
  index,
  regening,
  regenError,
  onClose,
  onRegen,
}: Props) {
  const images = status.preview_images ?? [];
  const img = images[index];
  const issues = slideIssues(status, index);
  const consultingOk = !issues.some(
    (issue) => issue.source === "pipeline" && issue.category === "consulting_qa"
  );
  const visualOk = !issues.some((issue) => issue.source === "qa");

  const consulting = qaBadge(consultingOk);
  const visual = qaBadge(visualOk);
  const page = String(index + 1).padStart(2, "0");

  const issue =
    issues.length === 0
      ? "No issues. Action title is a conclusion, exhibit supports it, source line present."
      : issues.map((w) => w.message).join("  ·  ");

  const qaRow: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    padding: "11px 13px",
    border: "1px solid var(--line)",
    borderRadius: 8,
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 40,
        background: "rgba(20,14,6,.55)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 32,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 960,
          background: "var(--surface)",
          border: "1px solid var(--line-2)",
          borderRadius: 14,
          boxShadow: "var(--shadow-lg)",
          overflow: "hidden",
          display: "grid",
          gridTemplateColumns: "1fr 300px",
        }}
      >
        {/* the slide */}
        <div style={{ padding: 30, borderRight: "1px solid var(--line)", background: "var(--paper)" }}>
          <div
            style={{
              position: "relative",
              aspectRatio: "16 / 9",
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              boxShadow: "var(--shadow)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: 4,
                background: "var(--accent)",
                zIndex: 1,
              }}
            />
            {img ? (
              <img
                src={previewImageUrl(jobId, img)}
                alt={`Slide ${index + 1}`}
                style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
              />
            ) : (
              <div
                style={{
                  width: "100%",
                  height: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--ink-3)",
                  fontFamily: MONO,
                  fontSize: 11,
                }}
              >
                no preview
              </div>
            )}
          </div>
        </div>

        {/* QA side */}
        <div style={{ padding: "26px 24px", display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 20,
            }}
          >
            <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)" }}>
              SLIDE {page}
            </span>
            <button
              onClick={onClose}
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                border: "1px solid var(--line)",
                background: "transparent",
                color: "var(--ink-2)",
                cursor: "pointer",
                fontSize: 15,
              }}
            >
              ×
            </button>
          </div>

          <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 12 }}>
            QA STATUS
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 22 }}>
            <div style={qaRow}>
              <span style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>Consulting QA</span>
              <span
                style={{
                  fontFamily: MONO,
                  fontSize: 10,
                  padding: "3px 8px",
                  borderRadius: 5,
                  background: consulting.bg,
                  color: consulting.ink,
                }}
              >
                {consulting.label}
              </span>
            </div>
            <div style={qaRow}>
              <span style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>Visual QA</span>
              <span
                style={{
                  fontFamily: MONO,
                  fontSize: 10,
                  padding: "3px 8px",
                  borderRadius: 5,
                  background: visual.bg,
                  color: visual.ink,
                }}
              >
                {visual.label}
              </span>
            </div>
          </div>

          <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 10 }}>
            ISSUES
          </div>
          <div style={{ flex: 1, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.5 }}>{issue}</div>

          <button
            onClick={onRegen}
            disabled={regening}
            style={{
              width: "100%",
              height: 44,
              marginTop: 18,
              background: "var(--ink)",
              color: "var(--paper)",
              border: "none",
              borderRadius: 8,
              font: "inherit",
              fontSize: 13,
              fontWeight: 700,
              cursor: regening ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              whiteSpace: "nowrap",
              opacity: regening ? 0.75 : 1,
            }}
          >
            {regening ? "Regenerating…" : "Regenerate slide"}
          </button>
          {regenError && (
            <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--bad)", lineHeight: 1.4 }}>
              {regenError}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
