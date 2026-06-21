import { card, SERIF } from "../ui";
import { downloadUrl, JobStatus, previewImageUrl } from "../api/client";
import { Mode, Planner, Quality } from "../types";
import { allIssues, issueCounts, slidesWithIssues } from "../qa";

const MONO = "'IBM Plex Mono', monospace";

type Props = {
  jobId: string;
  status: JobStatus;
  mode: Mode;
  planner: Planner;
  quality: Quality;
  deckTitle: string;
  onOpenSlide: (index: number) => void;
};

export default function ReviewScreen({
  jobId,
  status,
  mode,
  planner,
  quality,
  deckTitle,
  onOpenSlide,
}: Props) {
  const images = status.preview_images ?? [];
  const issues = allIssues(status);
  const issueSlides = slidesWithIssues(status);
  const slideCount = images.length;
  const passCount = images.filter((_, i) => !issueSlides.has(i)).length;
  const counts = issueCounts(status);
  const issueCount = counts.critical + counts.warning;
  const issueColor = counts.critical > 0 ? "var(--bad)" : counts.warning > 0 ? "var(--warn)" : "var(--good)";

  const qaStats = [
    { value: String(slideCount), unit: "slides", label: "Generated & rendered", color: "var(--ink)" },
    { value: String(passCount), unit: "pass", label: "Cleared both QA gates", color: "var(--good)" },
    { value: String(issueCount), unit: "issues", label: "Critical + warning findings", color: issueColor },
    {
      value: String(status.job.qa_rounds ?? 0),
      unit: "rounds",
      label: "QA repair passes",
      color: "var(--ink)",
    },
  ];

  const deckMeta = `${mode.toUpperCase()} · ${planner.toUpperCase()} PLANNER · ${quality.toUpperCase()} · ${slideCount} SLIDES`;
  const hasResult = !!status.job.result_file;

  return (
    <div className="sf-rise">
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 20,
          marginBottom: 8,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: ".18em",
              color: "var(--good)",
              marginBottom: 12,
            }}
          >
            ✓ DECK READY
          </div>
          <h1
            style={{
              fontFamily: SERIF,
              fontWeight: 500,
              fontSize: 38,
              lineHeight: 1.08,
              letterSpacing: "-.02em",
              margin: "0 0 8px",
            }}
          >
            {deckTitle}
          </h1>
          <div style={{ fontFamily: MONO, fontSize: 11, color: "var(--ink-3)" }}>{deckMeta}</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <a href={hasResult ? downloadUrl(jobId, "pptx") : undefined} style={{ textDecoration: "none" }}>
            <button
              disabled={!hasResult}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                height: 46,
                padding: "0 22px",
                background: "var(--accent)",
                color: "var(--accent-ink)",
                border: "none",
                borderRadius: 8,
                font: "inherit",
                fontSize: 14,
                fontWeight: 700,
                cursor: hasResult ? "pointer" : "not-allowed",
                boxShadow: "var(--shadow)",
                whiteSpace: "nowrap",
                opacity: hasResult ? 1 : 0.6,
              }}
            >
              ↓ Download PPTX
            </button>
          </a>
          <a href={hasResult ? downloadUrl(jobId, "pdf") : undefined} style={{ textDecoration: "none" }}>
            <button
              disabled={!hasResult}
              style={{
                height: 46,
                padding: "0 18px",
                background: "var(--surface)",
                color: "var(--ink)",
                border: "1px solid var(--line-2)",
                borderRadius: 8,
                font: "inherit",
                fontSize: 14,
                fontWeight: 600,
                cursor: hasResult ? "pointer" : "not-allowed",
                opacity: hasResult ? 1 : 0.6,
              }}
            >
              PDF
            </button>
          </a>
        </div>
      </div>

      {/* QA summary */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4,1fr)",
          gap: 12,
          margin: "28px 0 14px",
        }}
      >
        {qaStats.map((q, i) => (
          <div key={i} style={{ ...card, padding: "16px 18px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontFamily: SERIF, fontSize: 30, fontWeight: 600, color: q.color }}>
                {q.value}
              </span>
              <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{q.unit}</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-2)", marginTop: 4 }}>{q.label}</div>
          </div>
        ))}
      </div>

      {/* horizontal-flow note */}
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "flex-start",
          padding: "13px 16px",
          borderRadius: 9,
          background: "var(--accent-soft)",
          marginBottom: 30,
        }}
      >
        <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--accent)", flex: "none", marginTop: 1 }}>
          ↳
        </span>
        <span style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.5 }}>
          {counts.count === 0
            ? "No QA or pipeline issues were reported for this deck."
            : `${counts.count} QA or pipeline issue${counts.count === 1 ? "" : "s"} remain for review before sharing.`}
        </span>
      </div>

      {/* slide grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18 }}>
        {images.map((img, i) => {
          const warn = issueSlides.has(i);
          const qc = warn ? "var(--warn)" : "var(--good)";
          return (
            <div key={img} onClick={() => onOpenSlide(i)} style={{ cursor: "pointer" }}>
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
                    height: 3,
                    background: i === 0 ? "var(--accent)" : "var(--line)",
                    zIndex: 1,
                  }}
                />
                <img
                  src={previewImageUrl(jobId, img)}
                  alt={`Slide ${i + 1}`}
                  style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                />
                <span
                  style={{
                    position: "absolute",
                    top: 9,
                    right: 9,
                    width: 9,
                    height: 9,
                    borderRadius: "50%",
                    background: qc,
                    boxShadow: "0 0 0 2px var(--surface)",
                  }}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 9 }}>
                <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--ink-3)" }}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 9,
                    letterSpacing: ".05em",
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: warn ? "var(--warn-soft)" : "var(--good-soft)",
                    color: warn ? "var(--warn)" : "var(--good)",
                  }}
                >
                  {warn ? "WARNING" : "QA PASS"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* warnings */}
      <div style={{ marginTop: 36 }}>
        <div
          style={{
            fontFamily: MONO,
            fontSize: 10,
            letterSpacing: ".1em",
            color: "var(--ink-3)",
            marginBottom: 12,
          }}
        >
          QA ISSUES · {issues.length === 0 ? "none" : issues.length}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {issues.map((issue, i) => {
            const hasSlide = issue.slide_index != null;
            return (
            <div
              key={i}
              onClick={() => {
                if (hasSlide) onOpenSlide(Number(issue.slide_index));
              }}
              style={{
                display: "flex",
                gap: 14,
                alignItems: "center",
                padding: "14px 16px",
                background: "var(--surface)",
                border: "1px solid var(--line)",
                borderLeft: "3px solid var(--warn)",
                borderRadius: 8,
                cursor: hasSlide ? "pointer" : "default",
                boxShadow: "var(--shadow)",
              }}
            >
              <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--warn)", flex: "none", width: 54 }}>
                {hasSlide ? `SLIDE ${Number(issue.slide_index) + 1}` : "DECK"}
              </span>
              <span style={{ flex: 1, fontSize: 13, color: "var(--ink)", lineHeight: 1.4 }}>
                {issue.message}
              </span>
              <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--ink-3)" }}>
                {issue.category || issue.source} {hasSlide ? "→" : ""}
              </span>
            </div>
          );
          })}
        </div>
      </div>
    </div>
  );
}
