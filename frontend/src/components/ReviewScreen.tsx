import { card, SERIF } from "../ui";
import { downloadUrl, JobOutlineSlide, JobStatus, previewImageUrl } from "../api/client";
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
  outline: JobOutlineSlide[];
  artifacts?: { editing?: any };
  onOpenSlide: (index: number) => void;
};

export default function ReviewScreen({
  jobId,
  status,
  mode,
  planner,
  quality,
  deckTitle,
  outline,
  artifacts,
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
  const reviewFailed = status.job.status === "review_failed" || status.final_qa_passed === false;

  const qaStats = [
    { value: String(slideCount), unit: "slides", label: "Generated & rendered", color: "var(--ink)" },
    { value: String(passCount), unit: "pass", label: "Cleared both QA gates", color: "var(--good)" },
    { value: String(issueCount), unit: "issues", label: "Critical + warning findings", color: issueColor },
    {
      value: String(status.job.qa_rounds ?? 0),
      unit: "rounds",
      label: "Visual repair passes",
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
              color: reviewFailed ? "var(--bad)" : "var(--good)",
              marginBottom: 12,
            }}
          >
            {reviewFailed ? "REVIEW REQUIRED" : "✓ DECK READY"}
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
        className="sf-review-stats"
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
            : reviewFailed
            ? `${counts.count} QA or pipeline issue${counts.count === 1 ? "" : "s"} require review before this deck is ready to share.`
            : `${counts.count} QA or pipeline issue${counts.count === 1 ? "" : "s"} remain for review before sharing.`}
        </span>
      </div>

      <DeckIntelligence status={status} outline={outline} editingArtifact={artifacts?.editing} />

      {/* slide grid */}
      <div className="sf-review-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18 }}>
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

function DeckIntelligence({
  status,
  outline,
  editingArtifact,
}: {
  status: JobStatus;
  outline: JobOutlineSlide[];
  editingArtifact?: any;
}) {
  const coverage = status.planning_summary?.source_coverage;
  const gate = status.planning_summary?.spec_gate;
  const editing = status.planning_summary?.editing_contract;
  const editingSlides = Array.isArray(editingArtifact?.slides) ? editingArtifact.slides : [];
  const audit = status.rendered_slide_audit;
  const history = status.qa_history ?? [];
  const repairCount = history.filter((entry) => entry.repair_applied).length;
  const latestStop = [...history].reverse().find((entry) => entry.stop_reason)?.stop_reason;
  const consultingFindings = (status.warnings ?? []).filter((warning) =>
    ["consulting_qa", "horizontal_flow"].includes(warning.field)
  ).length;
  const qaHistoryValue = history.length
    ? `${history.length} scans / ${repairCount} repairs${latestStop ? ` / ${formatStopReason(latestStop)}` : ""}`
    : "-";
  const consultingValue = consultingFindings
    ? `${consultingFindings} pre-render finding${consultingFindings === 1 ? "" : "s"}`
    : "none";
  const finalReviewValue =
    status.final_review_passed == null && status.final_qa_passed == null
      ? "-"
      : status.final_review_passed ?? status.final_qa_passed
        ? "passed"
        : (status.unresolved_editing_contract_count ?? 0) > 0 &&
            (status.unresolved_critical_count ?? 0) === 0 &&
            (status.unresolved_actionable_issue_count ?? 0) === 0
          ? `${status.unresolved_editing_contract_count ?? 0} editing contract`
          : `${status.unresolved_critical_count ?? 0} critical / ${
              status.unresolved_actionable_issue_count ?? 0
            } actionable${
              status.unresolved_editing_contract_count
                ? ` / ${status.unresolved_editing_contract_count} editing`
                : ""
            }`;
  const auditValue = audit?.available
    ? `${audit.issue_count ?? 0} issues / ${audit.critical_count ?? 0} critical`
    : "-";
  const rhythmValue = audit?.available
    ? `${audit.unique_family_count ?? 0} families${
        audit.most_repeated_family
          ? ` / ${audit.most_repeated_family.family} x${audit.most_repeated_family.count}`
          : ""
      } / ${Math.round((audit.card_like_ratio ?? 0) * 100)}% cards`
    : "-";
  const editingValue = editing
    ? `${editing.status || "ready"} / ${
        editing.unique_composition_family_count || editing.unique_layout_count || 0
      } families / ${Math.round(((editing.composition_card_ratio ?? editing.bullet_card_ratio) || 0) * 100)}% cards`
    : "-";
  const editingRequirements = [...(editing?.requirements ?? [])].sort((left, right) => {
    const score = (status: string) => (status === "warning" ? 0 : status === "pass" ? 1 : 2);
    return score(left.status) - score(right.status);
  });
  const auditIssues = audit?.top_issues ?? [];
  const slotRiskCount = editing?.slot_risk_count ?? 0;
  const structuralWarningCount = editing?.structural_warning_count ?? 0;
  const structuralValue = editing
    ? `${editing.structural_operation_count || 0} ops / ${structuralWarningCount} warnings`
    : "-";
  const formattingWarningCount = editing?.formatting_warning_count ?? 0;
  const formattingValue = editing
    ? `${editing.formatting_fix_count || 0} fixes / ${formattingWarningCount} warnings`
    : "-";
  const visualReview = status.visual_review;
  const cloneEdit = status.template_clone_edit;
  const frameMap = status.template_frame_map;
  const deviationLog = status.template_deviation_log;
  const expectedPreviewCount = visualReview?.expected_slide_count || visualReview?.preview_count || 0;
  const auditText =
    visualReview && visualReview.audit_available
      ? visualReview.audit_preview_match
        ? visualReview.audit_passed
          ? "audit pass"
          : `${visualReview.audit_issue_count} audit issues`
        : `audit ${visualReview.audit_slide_count} slides`
      : "audit pending";
  const fullResolutionValue = visualReview
    ? `${visualReview.preview_count}/${expectedPreviewCount} previews / ${auditText}`
    : "-";
  const cloneEditValue = cloneEdit?.available
    ? `${cloneEdit.mapping_count ?? cloneEdit.slide_count ?? 0} mapped / ${
        cloneEdit.edit_target_count ?? 0
      } targets${
        cloneEdit.blocked_mapping_count ? ` / ${cloneEdit.blocked_mapping_count} blocked` : ""
      }${
        cloneEdit.weak_mapping_count ? ` / ${cloneEdit.weak_mapping_count} weak` : ""
      }${
        cloneEdit.unfilled_placeholder_count ? ` / ${cloneEdit.unfilled_placeholder_count} empty placeholders` : ""
      }${
        cloneEdit.closest_candidate_count ? ` / ${cloneEdit.closest_candidate_count} alternatives` : ""
      }${
        cloneEdit.rewritten_table_cell_count
          ? ` / ${cloneEdit.rewritten_table_cell_count} table cells`
          : ""
      }${
        cloneEdit.rewritten_chart_count
          ? ` / ${cloneEdit.rewritten_chart_count} charts (${cloneEdit.rewritten_chart_point_count ?? 0} points)`
          : ""
      }${
        cloneEdit.bolded_text_run_count
          ? ` / ${cloneEdit.bolded_text_run_count} bold header runs`
          : ""
      }${
        cloneEdit.deleted_media_placeholder_count
          ? ` / ${cloneEdit.deleted_media_placeholder_count} media placeholders removed`
          : ""
      }${
        cloneEdit.planned_excess_slot_count
          ? ` / slot cleanup ${cloneEdit.actual_deleted_slot_count ?? 0}/${cloneEdit.planned_excess_slot_count}`
          : ""
      }${
        cloneEdit.unsatisfied_slot_cleanup_count
          ? ` / ${cloneEdit.unsatisfied_slot_cleanup_count} cleanup gaps`
          : ""
      }${
        cloneEdit.package_cleanup_deleted_part_count
          ? ` / ${cloneEdit.package_cleanup_deleted_part_count} package parts cleaned`
          : ""
      }${
        cloneEdit.package_cleanup_deleted_media_part_count
          ? ` (${cloneEdit.package_cleanup_deleted_media_part_count} media)`
          : ""
      }`
    : "-";
  const deviationValue = deviationLog?.available
    ? `${deviationLog.status || "ready"} / ${deviationLog.deviation_count ?? 0} deviation${
        (deviationLog.deviation_count ?? 0) === 1 ? "" : "s"
      }`
    : "-";
  const frameMapValue = frameMap?.available
    ? `${frameMap.output_slide_count ?? 0} mapped / ${frameMap.source_slide_count ?? 0} source / ${
        frameMap.omitted_source_slide_count ?? 0
      } omitted${frameMap.blocked_output_slide_count ? ` / ${frameMap.blocked_output_slide_count} blocked` : ""}`
    : "-";
  return (
    <div
      className="sf-intel-grid"
      style={{ display: "grid", gridTemplateColumns: "1.15fr .85fr", gap: 12, marginBottom: 28 }}
    >
      <div style={{ ...card, padding: 16 }}>
        <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 10 }}>
          TITLE LADDER
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {outline.slice(0, 7).map((slide) => (
            <div key={slide.slide_index} style={{ display: "flex", gap: 9, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.35 }}>
              <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--accent)", flex: "none", width: 22 }}>
                {String(slide.slide_index + 1).padStart(2, "0")}
              </span>
              <span>
                {slide.action_title}
                {slide.composition_family && (
                  <span style={{ color: "var(--ink-3)" }}> · {slide.composition_family}</span>
                )}
                {slide.template_frame && (
                  <span style={{ color: "var(--ink-3)" }}>
                    {" "}· frame {slide.template_frame.source_slide ?? Number(slide.template_frame.index ?? 0) + 1}
                  </span>
                )}
              </span>
            </div>
          ))}
          {outline.length === 0 && <div style={{ fontSize: 12.5, color: "var(--ink-3)" }}>No outline metadata available.</div>}
        </div>
        {editingSlides.length > 0 && (
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 9 }}>
              LAYOUT MAP
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {editingSlides.slice(0, 5).map((slide: any) => (
                <div key={slide.slide_index} style={{ display: "flex", gap: 9, fontSize: 12, color: "var(--ink-2)" }}>
                  <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--accent)", flex: "none", width: 22 }}>
                    {String(Number(slide.slide_index) + 1).padStart(2, "0")}
                  </span>
                  <span>
                    {slide.composition_family || slide.layout || "composition"} · {slide.content_type || "content"}
                    {slide.structural_operation?.operation && (
                      <span style={{ color: "var(--ink-3)" }}>
                        {" "}· structure {slide.structural_operation.operation}
                      </span>
                    )}
                    {slide.formatting_plan?.status && slide.formatting_plan.status !== "pass" && (
                      <span style={{ color: slide.formatting_plan.status === "fixed" ? "var(--good)" : "var(--warn)" }}>
                        {" "}· format {slide.formatting_plan.action || slide.formatting_plan.status}
                      </span>
                    )}
                    {slide.slot_plan?.status && slide.slot_plan.status !== "native" && (
                      <span style={{ color: slide.slot_plan.status === "fit" ? "var(--good)" : "var(--warn)" }}>
                        {" "}· slot {slide.slot_plan.action || slide.slot_plan.status}
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <div style={{ ...card, padding: 16 }}>
        <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 10 }}>
          DECK INTELLIGENCE
        </div>
        <InfoRow label="Story map" value={status.planning_summary?.story_map_status || "-"} />
        <InfoRow label="Presentation style" value={String(status.job.config_json?.presentation_style || "-")} />
        <InfoRow label="Design language" value={String(status.job.config_json?.design_language || "-")} />
        <InfoRow
          label="Source coverage"
          value={coverage ? `${coverage.included_section_count}/${coverage.section_count} sections` : "-"}
        />
        <InfoRow label="Spec gate" value={gate ? `${gate.repaired_count} repaired / ${gate.unresolved_count} unresolved` : "-"} />
        <InfoRow label="Editing contract" value={editingValue} tone={editing?.status === "warning" ? "bad" : "normal"} />
        <InfoRow label="Structural plan" value={structuralValue} tone={structuralWarningCount ? "bad" : "normal"} />
        <InfoRow label="Formatting fixes" value={formattingValue} tone={formattingWarningCount ? "bad" : "normal"} />
        <InfoRow
          label="Full-res QA"
          value={fullResolutionValue}
          tone={visualReview?.status === "warning" ? "bad" : "normal"}
        />
        <InfoRow label="Template mapping" value={editing ? `${editing.template_mapped_count || 0} slides` : "-"} />
        <InfoRow
          label="Frame map"
          value={frameMapValue}
          tone={(frameMap?.blocked_output_slide_count ?? 0) > 0 ? "bad" : "normal"}
        />
        <InfoRow
          label="Clone/edit"
          value={cloneEditValue}
          tone={
            (cloneEdit?.warning_count ?? 0) > 0 || (cloneEdit?.blocked_mapping_count ?? 0) > 0
              || (cloneEdit?.unfilled_placeholder_count ?? 0) > 0
              ? "bad"
              : "normal"
          }
        />
        <InfoRow
          label="Deviation log"
          value={deviationValue}
          tone={(deviationLog?.deviation_count ?? 0) > 0 ? "bad" : "normal"}
        />
        {cloneEdit?.closest_candidate_samples?.length ? (
          <InfoRow
            label="Frame options"
            value={cloneEdit.closest_candidate_samples
              .slice(0, 2)
              .map((candidate) =>
                `S${candidate.output_slide ?? "?"}->${candidate.source_slide ?? "?"} ${
                  candidate.label || "frame"
                }${candidate.match_score != null ? `:${candidate.match_score}` : ""}`
              )
              .join(" / ")}
            tone="bad"
          />
        ) : null}
        {deviationLog?.samples?.length ? (
          <InfoRow
            label="Deviation sample"
            value={deviationLog.samples
              .slice(0, 1)
              .map((sample) => {
                const slide = sample.output_slide != null ? `S${sample.output_slide}` : "deck";
                return `${slide} ${sample.type || "deviation"}: ${sample.reason || "review needed"}`;
              })
              .join(" / ")}
            tone="bad"
          />
        ) : null}
        <InfoRow label="Slot fit risks" value={editing ? `${slotRiskCount}` : "-"} tone={slotRiskCount ? "bad" : "normal"} />
        <InfoRow label="Diagrams" value={editing ? `${editing.diagram_count || 0}` : "-"} />
        <InfoRow label="Consulting repairs" value={consultingValue} />
        <InfoRow label="Visual QA history" value={qaHistoryValue} />
        <InfoRow label="Final review" value={finalReviewValue} tone={status.final_qa_passed === false ? "bad" : "normal"} />
        <InfoRow label="Rendered audit" value={auditValue} tone={audit?.critical_count ? "bad" : "normal"} />
        <InfoRow label="Composition rhythm" value={rhythmValue} tone={audit?.passed === false ? "bad" : "normal"} />
        {editingRequirements.length > 0 && (
          <div style={{ marginTop: 14, paddingTop: 13, borderTop: "1px solid var(--line)" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 9 }}>
              EDITING CHECKLIST
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {editingRequirements.slice(0, 6).map((requirement) => (
                <ChecklistItem
                  key={requirement.id || requirement.label}
                  label={requirement.label}
                  message={requirement.message}
                  status={requirement.status}
                />
              ))}
            </div>
          </div>
        )}
        {auditIssues.length > 0 && (
          <div style={{ marginTop: 14, paddingTop: 13, borderTop: "1px solid var(--line)" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)", marginBottom: 9 }}>
              AUDIT FINDINGS
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {auditIssues.map((issue, index) => (
                <AuditFinding
                  key={`${issue.category}-${issue.slide_index ?? "deck"}-${index}`}
                  category={issue.category}
                  message={issue.message}
                  severity={issue.severity}
                  slideIndex={issue.slide_index}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatStopReason(reason: string) {
  const labels: Record<string, string> = {
    max_rounds: "max rounds",
    no_actionable_issues: "no actionable",
    repeated_actionable_signature: "repeat stop",
    repair_applied: "repair applied",
    repair_loop_disabled: "loop off",
  };
  return labels[reason] || reason.split("_").join(" ");
}

function InfoRow({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "bad" }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
      <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: tone === "bad" ? "var(--bad)" : "var(--ink)" }}>{value}</span>
    </div>
  );
}

function ChecklistItem({
  label,
  message,
  status,
}: {
  label: string;
  message: string;
  status: string;
}) {
  const isWarning = status === "warning";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "58px 1fr", gap: 9, alignItems: "start" }}>
      <span
        style={{
          fontFamily: MONO,
          fontSize: 9,
          letterSpacing: ".04em",
          color: isWarning ? "var(--warn)" : "var(--good)",
          paddingTop: 2,
        }}
      >
        {isWarning ? "WARN" : "PASS"}
      </span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: "block", fontSize: 12, color: "var(--ink)", lineHeight: 1.3 }}>{label}</span>
        {message && (
          <span style={{ display: "block", fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.35, marginTop: 2 }}>
            {message}
          </span>
        )}
      </span>
    </div>
  );
}

function AuditFinding({
  category,
  message,
  severity,
  slideIndex,
}: {
  category: string;
  message: string;
  severity: string;
  slideIndex?: number | null;
}) {
  const isCritical = severity === "CRITICAL";
  const slideLabel = slideIndex == null ? "DECK" : `SLIDE ${Number(slideIndex) + 1}`;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "58px 1fr", gap: 9, alignItems: "start" }}>
      <span
        style={{
          fontFamily: MONO,
          fontSize: 9,
          letterSpacing: ".04em",
          color: isCritical ? "var(--bad)" : "var(--warn)",
          paddingTop: 2,
        }}
      >
        {slideLabel}
      </span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: "block", fontSize: 12, color: "var(--ink)", lineHeight: 1.3 }}>{message}</span>
        <span style={{ display: "block", fontSize: 10.5, color: "var(--ink-3)", lineHeight: 1.35, marginTop: 2 }}>
          {category}
        </span>
      </span>
    </div>
  );
}
