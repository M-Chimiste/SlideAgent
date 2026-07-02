import { CSSProperties, useEffect, useState } from "react";
import {
  EDITABLE_SLIDE_LAYOUTS,
  JobOutlineSlide,
  JobStatus,
  previewImageUrl,
  RenderedSlideAuditSlide,
  SlideEditPayload,
  SlidePoint,
} from "../api/client";
import { slideIssues } from "../qa";

const MONO = "'IBM Plex Mono', monospace";

const fieldStyle: CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  border: "1px solid var(--line)",
  borderRadius: 8,
  background: "var(--surface)",
  color: "var(--ink)",
  font: "inherit",
  fontSize: 12.5,
};

const primaryBtnStyle: CSSProperties = {
  height: 44,
  background: "var(--ink)",
  color: "var(--paper)",
  border: "none",
  borderRadius: 8,
  font: "inherit",
  fontSize: 13,
  fontWeight: 700,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const smallBtnStyle: CSSProperties = {
  border: "1px solid var(--line)",
  background: "transparent",
  color: "var(--ink-2)",
  borderRadius: 8,
  font: "inherit",
  fontSize: 12,
  cursor: "pointer",
  padding: "6px 10px",
};

type Props = {
  jobId: string;
  status: JobStatus;
  index: number;
  outlineSlide?: JobOutlineSlide;
  auditSlide?: RenderedSlideAuditSlide;
  regening: boolean;
  regenError: string | null;
  saving: boolean;
  saveError: string | null;
  previewVersion?: number;
  onClose: () => void;
  onRegen: (guidance: string, edits?: SlideEditPayload) => void;
  onSaveEdit: (payload: SlideEditPayload) => void;
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
  outlineSlide,
  auditSlide,
  regening,
  regenError,
  saving,
  saveError,
  previewVersion,
  onClose,
  onRegen,
  onSaveEdit,
}: Props) {
  const [guidance, setGuidance] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editSubheading, setEditSubheading] = useState("");
  const [editLayout, setEditLayout] = useState("");
  const [editPoints, setEditPoints] = useState<SlidePoint[]>([]);

  useEffect(() => {
    setEditTitle(outlineSlide?.action_title || "");
    setEditSubheading(outlineSlide?.subheading || "");
    setEditLayout(outlineSlide?.layout || "");
    setEditPoints((outlineSlide?.points || []).map((p) => ({ ...p })));
    setEditing(false);
    setGuidance("");
  }, [outlineSlide, index]);

  const editable =
    !!outlineSlide &&
    outlineSlide.mode === "flexible" &&
    ["done", "review_failed", "planned"].includes(status.job.status);

  const editPayload = (): SlideEditPayload => {
    const payload: SlideEditPayload = {
      action_title: editTitle,
      subheading: editSubheading,
      points: editPoints.filter((p) => p.title.trim() || p.body.trim()),
    };
    if (editLayout && editLayout !== (outlineSlide?.layout || "")) {
      payload.layout = editLayout;
    }
    return payload;
  };

  const submitEdit = () => onSaveEdit(editPayload());
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
  const diagnostics = auditSlide?.layout_diagnostics;
  const auditIssues = auditSlide?.issues ?? [];
  const templateFrame = outlineSlide?.template_frame ?? auditSlide?.template_frame ?? null;
  const overflowCount = diagnostics?.overflow_risk_count ?? 0;
  const smallTextCount = diagnostics?.small_text_risk_count ?? 0;
  const overlapCount = diagnostics?.overlap_pair_count ?? 0;
  const occlusionCount = diagnostics?.occlusion_pair_count ?? 0;
  const hasDiagnostics = !!auditSlide && (
    overflowCount > 0 ||
    smallTextCount > 0 ||
    overlapCount > 0 ||
    occlusionCount > 0 ||
    auditIssues.length > 0
  );

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
        className="sf-lightbox-shell"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: editing ? 1240 : 1120,
          maxHeight: "calc(100vh - 56px)",
          background: "var(--surface)",
          border: "1px solid var(--line-2)",
          borderRadius: 14,
          boxShadow: "var(--shadow-lg)",
          overflow: "hidden",
          display: "grid",
          gridTemplateColumns: editing ? "1fr 520px" : "1fr 300px",
        }}
      >
        {/* the slide */}
        <div
          style={{
            padding: 30,
            borderRight: "1px solid var(--line)",
            background: "var(--paper)",
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
          }}
        >
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
                src={previewImageUrl(jobId, img, previewVersion)}
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
        <div style={{ padding: "26px 24px", display: "flex", flexDirection: "column", overflowY: "auto", minHeight: 0 }}>
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

          {!editing && (
          <>
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

          {hasDiagnostics && (
            <>
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 10,
                  letterSpacing: ".1em",
                  color: "var(--ink-3)",
                  marginBottom: 10,
                }}
              >
                RENDERED AUDIT
              </div>
              <div style={{ marginBottom: 20, display: "flex", flexDirection: "column", gap: 8 }}>
                <MetaRow label="Text boxes" value={String(diagnostics?.text_box_count ?? "-")} />
                <MetaRow label="Cut-off risk" value={String(overflowCount)} tone={overflowCount > 0 ? "bad" : "normal"} />
                <MetaRow label="Small text" value={String(smallTextCount)} tone={smallTextCount > 0 ? "bad" : "normal"} />
                <MetaRow label="Overlap pairs" value={String(overlapCount)} tone={overlapCount > 0 ? "bad" : "normal"} />
                <MetaRow label="Covered text" value={String(occlusionCount)} tone={occlusionCount > 0 ? "bad" : "normal"} />
                {auditIssues.slice(0, 3).map((issue, i) => (
                  <AuditNote key={`issue-${i}`} label={issue.category || issue.severity} value={issue.message} />
                ))}
                {(diagnostics?.overflow_risks ?? []).slice(0, 2).map((risk, i) => (
                  <AuditNote key={`overflow-${i}`} label="Cut-off" value={risk.text || "Text region may overflow."} />
                ))}
                {(diagnostics?.small_text_risks ?? []).slice(0, 2).map((risk, i) => (
                  <AuditNote
                    key={`small-text-${i}`}
                    label={`Small ${risk.font_size ?? "?"}pt`}
                    value={risk.text || "Text is below the readable size floor."}
                  />
                ))}
                {(diagnostics?.overlap_pairs ?? []).slice(0, 2).map((pair, i) => (
                  <AuditNote
                    key={`overlap-${i}`}
                    label={`Overlap ${Math.round((pair.overlap_ratio ?? 0) * 100)}%`}
                    value={(pair.texts || []).join(" / ") || "Text regions overlap."}
                  />
                ))}
                {(diagnostics?.occlusion_pairs ?? []).slice(0, 2).map((pair, i) => (
                  <AuditNote
                    key={`occlusion-${i}`}
                    label={`Covered ${Math.round((pair.overlap_ratio ?? 0) * 100)}%`}
                    value={pair.text || "Text is partially covered by another shape."}
                  />
                ))}
              </div>
            </>
          )}

          {outlineSlide && (
            <>
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 10,
                  letterSpacing: ".1em",
                  color: "var(--ink-3)",
                  marginBottom: 10,
                }}
              >
                OUTLINE
              </div>
              <div style={{ marginBottom: 20, display: "flex", flexDirection: "column", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--ink)", lineHeight: 1.3 }}>
                    {outlineSlide.action_title || outlineSlide.label}
                  </div>
                  {outlineSlide.subheading && (
                    <div style={{ marginTop: 5, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.35 }}>
                      {outlineSlide.subheading}
                    </div>
                  )}
                </div>
                <MetaRow label="Role" value={outlineSlide.narrative_role || "-"} />
                <MetaRow label="Layout" value={outlineSlide.layout || outlineSlide.archetype || "-"} />
                <MetaRow label="Composition" value={outlineSlide.composition_family || "-"} />
                {templateFrame && (
                  <>
                    <MetaRow
                      label="Source frame"
                      value={`${templateFrame.source_slide ?? Number(templateFrame.index ?? 0) + 1}: ${
                        templateFrame.label || templateFrame.layout_name || "template slide"
                      }`}
                    />
                    <MetaRow
                      label="Frame type"
                      value={
                        [
                          templateFrame.content_category || templateFrame.method || "-",
                          templateFrame.match_confidence
                            ? `${templateFrame.match_confidence}${
                                templateFrame.match_score != null ? `:${templateFrame.match_score}` : ""
                              }`
                            : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")
                      }
                    />
                    {templateFrame.match_reason && (
                      <MetaRow label="Frame match" value={templateFrame.match_reason} />
                    )}
                    {templateFrame.closest_candidates?.length ? (
                      <MetaRow
                        label="Alternatives"
                        value={templateFrame.closest_candidates
                          .slice(0, 3)
                          .map((candidate) => {
                            const frameNo = candidate.source_slide ?? Number(candidate.index ?? 0) + 1;
                            return `${frameNo} ${candidate.label || candidate.layout_name || "frame"}${
                              candidate.match_score != null ? `:${candidate.match_score}` : ""
                            }`;
                          })
                          .join(" / ")}
                      />
                    ) : null}
                    <MetaRow label="Reuse" value={templateFrame.reuse_mode || "-"} />
                  </>
                )}
                <MetaRow label="Exhibit" value={outlineSlide.exhibit_type || "-"} />
                {outlineSlide.visual_degradation?.reason && (
                  <MetaRow label="Degraded" value={String(outlineSlide.visual_degradation.reason)} />
                )}
                <div style={{ fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.4 }}>
                  {(outlineSlide.source_refs || []).slice(0, 4).join(", ") ||
                    (outlineSlide.sources || []).slice(0, 2).join("; ") ||
                    "No source refs"}
                </div>
                {outlineSlide.speaker_notes && (
                  <div
                    style={{
                      fontSize: 11.5,
                      color: "var(--ink-2)",
                      lineHeight: 1.45,
                      padding: 10,
                      border: "1px solid var(--line)",
                      borderRadius: 8,
                      background: "var(--surface-2)",
                    }}
                  >
                    {outlineSlide.speaker_notes}
                  </div>
                )}
              </div>
            </>
          )}

          <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 10 }}>
            ISSUES
          </div>
          <div style={{ flex: 1, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.5 }}>{issue}</div>
          </>
          )}

          {editing && editable && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)" }}>
                EDIT SLIDE
              </div>
              <input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                placeholder="Action title"
                style={fieldStyle}
              />
              <textarea
                value={editSubheading}
                onChange={(e) => setEditSubheading(e.target.value)}
                placeholder="Positioning subheading"
                rows={2}
                style={{ ...fieldStyle, resize: "vertical" }}
              />
              <select value={editLayout} onChange={(e) => setEditLayout(e.target.value)} style={fieldStyle}>
                <option value="">Layout: {outlineSlide?.layout || "keep current"}</option>
                {EDITABLE_SLIDE_LAYOUTS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
              {editPoints.map((p, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                    padding: 8,
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                  }}
                >
                  <div style={{ display: "flex", gap: 6 }}>
                    <input
                      value={p.title}
                      onChange={(e) =>
                        setEditPoints(editPoints.map((q, j) => (j === i ? { ...q, title: e.target.value } : q)))
                      }
                      placeholder={`Point ${i + 1} lead`}
                      style={{ ...fieldStyle, flex: 1 }}
                    />
                    <button
                      onClick={() => setEditPoints(editPoints.filter((_, j) => j !== i))}
                      title="Remove point"
                      style={{ ...smallBtnStyle, width: 30 }}
                    >
                      ×
                    </button>
                  </div>
                  <textarea
                    value={p.body}
                    onChange={(e) =>
                      setEditPoints(editPoints.map((q, j) => (j === i ? { ...q, body: e.target.value } : q)))
                    }
                    placeholder="One complete supporting sentence"
                    rows={2}
                    style={{ ...fieldStyle, resize: "vertical" }}
                  />
                </div>
              ))}
              {editPoints.length < 6 && (
                <button
                  onClick={() => setEditPoints([...editPoints, { title: "", body: "", icon: "" }])}
                  style={smallBtnStyle}
                >
                  + Add point
                </button>
              )}
              <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginTop: 8 }}>
                MODEL GUIDANCE
              </div>
              <textarea
                value={guidance}
                onChange={(e) => setGuidance(e.target.value)}
                placeholder="Optional context for the model — e.g. 'Reframe around cost risk for the CFO; keep my second point verbatim; more quantitative.'"
                rows={3}
                style={{ ...fieldStyle, resize: "vertical" }}
              />
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  position: "sticky",
                  bottom: -26,
                  marginBottom: -26,
                  padding: "10px 0 26px",
                  background: "var(--surface)",
                }}
              >
                <button
                  onClick={submitEdit}
                  disabled={saving || regening}
                  style={{ ...primaryBtnStyle, flex: 1, opacity: saving ? 0.75 : 1 }}
                >
                  {saving ? "Saving & rebuilding…" : "Save changes"}
                </button>
                <button
                  onClick={() => onRegen(guidance.trim(), editPayload())}
                  disabled={saving || regening}
                  title="Apply your edits, then let the model rework the slide with your guidance"
                  style={{ ...primaryBtnStyle, flex: 1, background: "var(--accent)", opacity: regening ? 0.75 : 1 }}
                >
                  {regening ? "Regenerating…" : "Save & regenerate"}
                </button>
                <button onClick={() => setEditing(false)} disabled={saving || regening} style={{ ...smallBtnStyle, height: 44 }}>
                  Cancel
                </button>
              </div>
              {regenError && (
                <div style={{ fontSize: 11.5, color: "var(--bad)", lineHeight: 1.4 }}>{regenError}</div>
              )}
              {saveError && <div style={{ fontSize: 11.5, color: "var(--bad)", lineHeight: 1.4 }}>{saveError}</div>}
            </div>
          )}

          {!editing && (
            <>
              <textarea
                value={guidance}
                onChange={(e) => setGuidance(e.target.value)}
                placeholder="Guidance for regeneration (optional) — e.g. 'Reframe around cost risk, make it a comparison, more quantitative.'"
                rows={2}
                style={{ ...fieldStyle, marginTop: 16, resize: "vertical" }}
              />
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button
                  onClick={() => onRegen(guidance.trim())}
                  disabled={regening || saving}
                  style={{ ...primaryBtnStyle, flex: 1, opacity: regening ? 0.75 : 1 }}
                >
                  {regening ? "Regenerating…" : guidance.trim() ? "Regenerate with guidance" : "Regenerate slide"}
                </button>
                {editable && (
                  <button
                    onClick={() => setEditing(true)}
                    disabled={regening || saving}
                    style={{ ...smallBtnStyle, height: 44, padding: "0 14px" }}
                  >
                    Edit
                  </button>
                )}
              </div>
              {regenError && (
                <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--bad)", lineHeight: 1.4 }}>
                  {regenError}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MetaRow({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "bad" }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        borderBottom: "1px solid var(--line)",
        paddingBottom: 7,
      }}
    >
      <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 10.5, color: tone === "bad" ? "var(--bad)" : "var(--ink)" }}>{value}</span>
    </div>
  );
}

function AuditNote({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: "9px 10px",
        border: "1px solid var(--line)",
        borderRadius: 8,
        background: "var(--surface-2)",
      }}
    >
      <div style={{ fontFamily: MONO, fontSize: 9.5, color: "var(--bad)", marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-2)", lineHeight: 1.35 }}>
        {value}
      </div>
    </div>
  );
}
