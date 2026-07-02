import { CSSProperties } from "react";
import { SERIF } from "../ui";

const MONO = "'IBM Plex Mono', monospace";

const STAGES: { label: string; desc: string }[] = [
  { label: "Ingest sources", desc: "Parse documents, extract metrics and provenance" },
  { label: "Plan ghost deck", desc: "SCR arc, Pyramid structure, action-title storyline" },
  { label: "Consulting QA", desc: "Horizontal flow, MECE, one message per slide" },
  { label: "Generate content", desc: "Source-grounded evidence under each title" },
  { label: "Design specs", desc: "Select archetypes and layout per slide" },
  { label: "Render PPTX", desc: "Deterministic layout engine builds slides" },
  { label: "Visual QA", desc: "Render to images, check overlap and density" },
  { label: "Repair pass", desc: "Fix flagged slides, re-run gates" },
];

// backend status → index of the stage currently running
const STATUS_STAGE: Record<string, number> = {
  queued: 0,
  running: 0,
  analyzing: 0,
  planning: 1,
  generating: 3,
  qa: 6,
  repairing: 7,
  planned: 3,
  done: STAGES.length,
  review_failed: STAGES.length,
  error: -1,
};

type Props = {
  jobId: string | null;
  jobStatus: string;
  progress: number;
  errorMessage: string | null;
  onCancel: () => void;
  onReview: () => void;
};

export default function JobScreen({
  jobId,
  jobStatus,
  progress,
  errorMessage,
  onCancel,
  onReview,
}: Props) {
  const done = jobStatus === "done";
  const planned = jobStatus === "planned";
  const reviewFailed = jobStatus === "review_failed";
  const errored = jobStatus === "error";
  const current = STATUS_STAGE[jobStatus] ?? 0;
  const terminalReview = done || reviewFailed;
  const pct = terminalReview ? 100 : planned ? Math.max(50, Math.round((progress || 0) * 100)) : Math.round((progress || 0) * 100);

  const eyebrowText = errored ? "✕ FAILED" : reviewFailed ? "REVIEW FAILED" : done ? "✓ COMPLETE" : planned ? "✓ PLAN READY" : "GENERATING";
  const title = errored
    ? "Generation failed"
    : reviewFailed
    ? "Deck needs review fixes"
    : done
    ? "Your deck is ready"
    : planned
    ? "Your ghost deck is ready"
    : STAGES[current]
    ? `${STAGES[current].label}…`
    : "Working…";

  return (
    <div className="sf-rise" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 6,
        }}
      >
        <div
          style={{
            fontFamily: MONO,
            fontSize: 11,
            letterSpacing: ".18em",
            color: errored || reviewFailed ? "var(--bad)" : "var(--accent)",
          }}
        >
          {eyebrowText}
        </div>
        <div style={{ fontFamily: MONO, fontSize: 11, color: "var(--ink-3)" }}>
          {jobId ? `job_${jobId.slice(0, 6)}` : ""}
        </div>
      </div>
      <h1
        style={{
          fontFamily: SERIF,
          fontWeight: 500,
          fontSize: 34,
          lineHeight: 1.12,
          letterSpacing: "-.02em",
          margin: "0 0 24px",
        }}
      >
        {title}
      </h1>

      {/* progress bar */}
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: "var(--inset)",
          overflow: "hidden",
          marginBottom: 6,
        }}
      >
        <div
          style={{
            height: "100%",
            background: errored || reviewFailed ? "var(--bad)" : "var(--accent)",
            borderRadius: 3,
            width: `${pct}%`,
            transition: "width .5s cubic-bezier(.3,.7,.3,1)",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: MONO,
          fontSize: 10.5,
          color: "var(--ink-3)",
          marginBottom: 28,
        }}
      >
        <span>{pct}%</span>
        <span>
          {errored
            ? errorMessage || "see logs"
            : reviewFailed
            ? errorMessage || "final QA found unresolved issues"
            : planned
            ? "plan ready for review"
            : done
            ? "all gates cleared"
            : jobStatus === "repairing"
            ? "repairing flagged slides"
            : jobStatus === "qa"
            ? "visual QA and repair check"
            : "planning → render → QA"}
        </span>
      </div>

      {/* stages */}
      <div style={{ display: "flex", flexDirection: "column" }}>
        {STAGES.map((g, i) => {
          const stageDone = terminalReview || (planned && i <= 4) || (!errored && !reviewFailed && i < current);
          const active = !terminalReview && !planned && !errored && i === current;
          const ring: CSSProperties["borderColor"] = active
            ? "var(--accent)"
            : stageDone
            ? "var(--good)"
            : "var(--line-2)";
          const bg = active ? "var(--accent)" : stageDone ? "var(--good-soft)" : "transparent";
          const ink = active ? "var(--accent-ink)" : stageDone ? "var(--good)" : "var(--ink-3)";
          return (
            <div
              key={g.label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                padding: "13px 0",
                borderBottom: "1px solid var(--line)",
              }}
            >
              <span
                style={{
                  flex: "none",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 26,
                  height: 26,
                  borderRadius: "50%",
                  border: `1.5px solid ${ring}`,
                  background: bg,
                  color: ink,
                  fontFamily: MONO,
                  fontSize: 11,
                  animation: active ? "sf-pulse 1.4s ease-in-out infinite" : "none",
                }}
              >
                {stageDone ? "✓" : active ? "" : String(i + 1)}
              </span>
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontSize: 14.5,
                    fontWeight: 600,
                    color: stageDone || active ? "var(--ink)" : "var(--ink-3)",
                  }}
                >
                  {g.label}
                </div>
                <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 1 }}>{g.desc}</div>
              </div>
              <span
                style={{
                  fontFamily: MONO,
                  fontSize: 10,
                  letterSpacing: ".06em",
                  color: stageDone ? "var(--good)" : active ? "var(--accent)" : "var(--ink-3)",
                }}
              >
                {stageDone ? "DONE" : active ? "RUNNING" : "QUEUED"}
              </span>
            </div>
          );
        })}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 28,
        }}
      >
        <button
          onClick={onCancel}
          style={{
            height: 42,
            padding: "0 16px",
            background: "transparent",
            border: "1px solid var(--line)",
            borderRadius: 8,
            color: "var(--ink-3)",
            font: "inherit",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {terminalReview || errored ? "Back" : "Cancel"}
        </button>
        <button
          onClick={onReview}
          disabled={!terminalReview && !planned}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 9,
            height: 48,
            padding: "0 26px",
            background: terminalReview || planned ? "var(--accent)" : "var(--inset)",
            color: terminalReview || planned ? "var(--accent-ink)" : "var(--ink-3)",
            border: "none",
            borderRadius: 9,
            font: "inherit",
            fontSize: 14,
            fontWeight: 700,
            cursor: terminalReview || planned ? "pointer" : "default",
            boxShadow: "var(--shadow)",
            opacity: terminalReview || planned ? 1 : 0.7,
          }}
        >
          {planned ? "Review plan" : terminalReview ? "Review deck" : "Working…"} <span style={{ fontSize: 15 }}>→</span>
        </button>
      </div>
    </div>
  );
}
