import { useEffect, useMemo, useState } from "react";
import { JobOutlineSlide, JobStatus, OutlineEdit } from "../api/client";
import { card, ghostBtn, microLabel, primaryBtn, SERIF } from "../ui";

const MONO = "'IBM Plex Mono', monospace";

type PlanningArtifacts = {
  source?: any;
  story?: any;
  gate?: any;
  editing?: any;
};

type Props = {
  status: JobStatus;
  outline: JobOutlineSlide[];
  artifacts: PlanningArtifacts;
  loading: boolean;
  saving: boolean;
  rendering: boolean;
  error: string | null;
  onSave: (edits: OutlineEdit[]) => void;
  onRender: () => void;
  onBack: () => void;
};

export default function PlanReviewScreen({
  status,
  outline,
  artifacts,
  loading,
  saving,
  rendering,
  error,
  onSave,
  onRender,
  onBack,
}: Props) {
  const [edits, setEdits] = useState<Record<number, { action_title: string; subheading: string }>>({});

  useEffect(() => {
    const next: Record<number, { action_title: string; subheading: string }> = {};
    outline.forEach((slide) => {
      next[slide.slide_index] = {
        action_title: slide.action_title || slide.label,
        subheading: slide.subheading || "",
      };
    });
    setEdits(next);
  }, [outline]);

  const changed = useMemo(() => {
    return outline
      .map((slide) => {
        const edit = edits[slide.slide_index];
        if (!edit) return null;
        if (edit.action_title === slide.action_title && edit.subheading === slide.subheading) return null;
        return {
          slide_index: slide.slide_index,
          action_title: edit.action_title,
          subheading: edit.subheading,
        };
      })
      .filter(Boolean) as OutlineEdit[];
  }, [edits, outline]);

  const coverage = status.planning_summary?.source_coverage;
  const gate = status.planning_summary?.spec_gate;
  const editing = status.planning_summary?.editing_contract;
  const editingSlides = Array.isArray(artifacts.editing?.slides) ? artifacts.editing.slides : [];
  const beats = Array.isArray(artifacts.story?.beats) ? artifacts.story.beats : [];
  const visualReview = status.visual_review;

  const updateEdit = (slideIndex: number, field: "action_title" | "subheading", value: string) => {
    setEdits((current) => ({
      ...current,
      [slideIndex]: {
        action_title: current[slideIndex]?.action_title || "",
        subheading: current[slideIndex]?.subheading || "",
        [field]: value,
      },
    }));
  };

  return (
    <div className="sf-rise">
      <div style={microLabel}>GHOST DECK READY</div>
      <div
        className="sf-plan-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 20,
          alignItems: "flex-start",
          flexWrap: "wrap",
          marginTop: 8,
          marginBottom: 26,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h1
            style={{
              fontFamily: SERIF,
              fontWeight: 500,
              fontSize: 38,
              lineHeight: 1.08,
              margin: 0,
            }}
          >
            Review the storyline before rendering
          </h1>
          <div style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 9 }}>
            Tune the action-title ladder, then render the editable PPTX.
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button style={ghostBtn} onClick={onBack}>
            Back
          </button>
          <button
            style={{ ...primaryBtn, opacity: rendering ? 0.7 : 1 }}
            disabled={rendering}
            onClick={onRender}
          >
            {rendering ? "Rendering..." : "Render deck"}
          </button>
        </div>
      </div>

      <div className="sf-plan-grid" style={{ display: "grid", gridTemplateColumns: "1fr 330px", gap: 18 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {loading ? (
            <div style={{ ...card, padding: 20, color: "var(--ink-3)", fontSize: 13 }}>Loading plan...</div>
          ) : (
            outline.map((slide) => {
              const edit = edits[slide.slide_index] || { action_title: "", subheading: "" };
              return (
                <div key={slide.slide_index} style={{ ...card, padding: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
                    <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--ink-3)" }}>
                      SLIDE {String(slide.slide_index + 1).padStart(2, "0")}
                    </span>
                    <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--accent)" }}>
                      {(slide.exhibit_type || slide.layout || "slide").toUpperCase()}
                    </span>
                  </div>
                  <input
                    value={edit.action_title}
                    onChange={(e) => updateEdit(slide.slide_index, "action_title", e.target.value)}
                    style={{
                      width: "100%",
                      border: "1px solid var(--line)",
                      borderRadius: 8,
                      background: "var(--surface-2)",
                      color: "var(--ink)",
                      font: "inherit",
                      fontSize: 15,
                      fontWeight: 700,
                      padding: "10px 12px",
                    }}
                  />
                  <input
                    value={edit.subheading}
                    onChange={(e) => updateEdit(slide.slide_index, "subheading", e.target.value)}
                    placeholder="Subheading"
                    style={{
                      width: "100%",
                      marginTop: 8,
                      border: "1px solid var(--line)",
                      borderRadius: 8,
                      background: "transparent",
                      color: "var(--ink-2)",
                      font: "inherit",
                      fontSize: 12.5,
                      padding: "8px 12px",
                    }}
                  />
                  <div style={{ marginTop: 9, fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.4 }}>
                    {(slide.sources || []).slice(0, 2).join("; ") || "No source label"}
                  </div>
                  {(slide.composition_family || slide.visual_degradation?.reason) && (
                    <div style={{ marginTop: 6, fontSize: 11, color: "var(--ink-3)", lineHeight: 1.4 }}>
                      {slide.composition_family || "composition pending"}
                      {slide.visual_degradation?.reason ? ` · ${slide.visual_degradation.reason}` : ""}
                    </div>
                  )}
                  {slide.template_frame && (
                    <div style={{ marginTop: 6, fontSize: 11, color: "var(--ink-3)", lineHeight: 1.4 }}>
                      source frame {slide.template_frame.source_slide ?? Number(slide.template_frame.index ?? 0) + 1}:{" "}
                      {slide.template_frame.label || slide.template_frame.layout_name || "template slide"}
                      {slide.template_frame.method ? ` · ${slide.template_frame.method}` : ""}
                      {slide.template_frame.match_confidence
                        ? ` · ${slide.template_frame.match_confidence}${
                            slide.template_frame.match_score != null ? `:${slide.template_frame.match_score}` : ""
                          }`
                        : ""}
                      {slide.template_frame.closest_candidates?.length ? (
                        <div style={{ marginTop: 3 }}>
                          alternatives:{" "}
                          {slide.template_frame.closest_candidates
                            .slice(0, 2)
                            .map((candidate) => {
                              const frameNo = candidate.source_slide ?? Number(candidate.index ?? 0) + 1;
                              return `${frameNo} ${candidate.label || candidate.layout_name || "frame"}${
                                candidate.match_score != null ? `:${candidate.match_score}` : ""
                              }`;
                            })
                            .join(" / ")}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              );
            })
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <button
              style={{ ...ghostBtn, opacity: changed.length && !saving ? 1 : 0.55 }}
              disabled={!changed.length || saving}
              onClick={() => onSave(changed)}
            >
              {saving ? "Saving..." : "Save title edits"}
            </button>
          </div>
          {error && <div style={{ color: "var(--bad)", fontSize: 12 }}>{error}</div>}
        </div>

        <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ ...card, padding: 16 }}>
            <div style={{ ...microLabel, marginBottom: 10 }}>PLANNING HEALTH</div>
            <Metric label="Story map" value={status.planning_summary?.story_map_status || "ready"} />
            <Metric label="Style" value={String(status.job.config_json?.presentation_style || "auto")} />
            <Metric label="Design language" value={String(status.job.config_json?.design_language || "auto")} />
            <Metric label="Sections used" value={coverage ? `${coverage.included_section_count}/${coverage.section_count}` : "-"} />
            <Metric label="Spec gate" value={gate ? `${gate.repaired_count} repaired` : "-"} />
            <Metric
              label="Editing contract"
              value={
                editing
                  ? `${editing.status || "ready"} / ${
                      editing.unique_composition_family_count || editing.unique_layout_count
                    } families`
                  : "-"
              }
            />
            <Metric
              label="Card composition"
              value={
                editing
                  ? `${Math.round(((editing.composition_card_ratio ?? editing.bullet_card_ratio) || 0) * 100)}%`
                  : "-"
              }
            />
            <Metric label="Diagrams" value={editing ? String(editing.diagram_count || 0) : "-"} />
            <Metric label="Slot fit risks" value={editing ? String(editing.slot_risk_count || 0) : "-"} />
            <Metric
              label="Structural ops"
              value={editing ? `${editing.structural_operation_count || 0} / ${editing.structural_warning_count || 0} warnings` : "-"}
            />
            <Metric
              label="Formatting fixes"
              value={editing ? `${editing.formatting_fix_count || 0} / ${editing.formatting_warning_count || 0} warnings` : "-"}
            />
            <Metric
              label="Full-res QA"
              value={visualReview ? visualReview.status : "after render"}
            />
          </div>
          <div style={{ ...card, padding: 16 }}>
            <div style={{ ...microLabel, marginBottom: 10 }}>CLAUDE-STYLE LAYOUT MAP</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {editingSlides.slice(0, 7).map((slide: any) => (
                <div key={slide.slide_index} style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.35 }}>
                  <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--accent)" }}>
                    {String(Number(slide.slide_index) + 1).padStart(2, "0")}
                  </span>{" "}
                  {slide.layout || "layout"} · {slide.content_type || "content"}
                  {slide.structural_operation?.operation && (
                    <div style={{ marginLeft: 28, marginTop: 2, color: "var(--ink-3)" }}>
                      structure: {slide.structural_operation.operation}
                    </div>
                  )}
                  {slide.formatting_plan?.status && slide.formatting_plan.status !== "pass" && (
                    <div style={{ marginLeft: 28, marginTop: 2, color: slide.formatting_plan.status === "fixed" ? "var(--good)" : "var(--warn)" }}>
                      format: {slide.formatting_plan.action || slide.formatting_plan.status}
                    </div>
                  )}
                  {slide.slot_plan?.status && slide.slot_plan.status !== "native" && (
                    <div style={{ marginLeft: 28, marginTop: 2, color: slide.slot_plan.status === "fit" ? "var(--good)" : "var(--warn)" }}>
                      slot: {slide.slot_plan.action || slide.slot_plan.status}
                    </div>
                  )}
                </div>
              ))}
              {editingSlides.length === 0 && (
                <div style={{ fontSize: 12, color: "var(--ink-3)" }}>No editing-contract artifact found yet.</div>
              )}
            </div>
          </div>
          <div style={{ ...card, padding: 16 }}>
            <div style={{ ...microLabel, marginBottom: 10 }}>STORY BEATS</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {beats.slice(0, 8).map((beat: any, idx: number) => (
                <div key={idx} style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.35 }}>
                  <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--accent)" }}>
                    {String(idx + 1).padStart(2, "0")}
                  </span>{" "}
                  {beat.role || "beat"} · {beat.preferred_exhibit || "exhibit"}
                </div>
              ))}
              {beats.length === 0 && <div style={{ fontSize: 12, color: "var(--ink-3)" }}>No story-map beats found.</div>}
            </div>
          </div>
          <div style={{ ...card, padding: 16 }}>
            <div style={{ ...microLabel, marginBottom: 10 }}>SOURCE COVERAGE</div>
            <div style={{ fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.45 }}>
              {coverage
                ? `${coverage.included_section_count} sections included, ${coverage.omitted_section_count} omitted, ~${coverage.estimated_tokens} tokens.`
                : "No source coverage artifact is available."}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
      <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--ink)" }}>{value}</span>
    </div>
  );
}
