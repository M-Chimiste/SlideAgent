import { useRef } from "react";
import { card, eyebrow, microLabel, segActive, segGroup, segIdle, SERIF } from "../ui";
import { DesignLanguage, Length, Mode, Planner, PresentationStyle, Quality, BackgroundStyle } from "../types";

const MONO = "'IBM Plex Mono', monospace";

type Props = {
  mode: Mode;
  brief: string;
  audience: string;
  goal: string;
  onBrief: (v: string) => void;
  onAudience: (v: string) => void;
  onGoal: (v: string) => void;
  docs: File[];
  onAddDocs: (files: File[]) => void;
  onRemoveDoc: (index: number) => void;
  planner: Planner;
  quality: Quality;
  length: Length;
  presentationStyle: PresentationStyle;
  designLanguage: DesignLanguage;
  backgroundStyle: BackgroundStyle;
  visualQa: boolean;
  onPlanner: (v: Planner) => void;
  onQuality: (v: Quality) => void;
  onLength: (v: Length) => void;
  onPresentationStyle: (v: PresentationStyle) => void;
  onDesignLanguage: (v: DesignLanguage) => void;
  onBackgroundStyle: (v: BackgroundStyle) => void;
  onToggleVisualQa: () => void;
  submitting: boolean;
  error: string | null;
  onGenerate: () => void;
  onPreviewPlan: () => void;
};

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { v: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div style={{ ...segGroup, marginBottom: 18 }}>
      {options.map((o) => (
        <button
          key={o.v}
          style={value === o.v ? segActive : segIdle}
          onClick={() => onChange(o.v)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Dropdown<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { v: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      style={{
        ...segGroup,
        width: "100%",
        marginBottom: 18,
        padding: "10px 12px",
        fontSize: 13,
        color: "var(--ink-1)",
        background: "var(--surface-1)",
        cursor: "pointer",
      }}
    >
      {options.map((o) => (
        <option key={o.v} value={o.v}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function ext(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toUpperCase().slice(0, 3) : "DOC";
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function BriefScreen(p: Props) {
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="sf-rise">
      <div style={eyebrow}>{p.mode === "freeform" ? "02" : "03"} — THE BRIEF</div>
      <h1
        style={{
          fontFamily: SERIF,
          fontWeight: 500,
          fontSize: 36,
          lineHeight: 1.12,
          letterSpacing: "-.02em",
          margin: "0 0 10px",
        }}
      >
        Tell SlideForge what to argue
      </h1>
      <p
        style={{
          fontSize: 15,
          color: "var(--ink-2)",
          margin: "0 0 32px",
          maxWidth: "58ch",
          lineHeight: 1.55,
        }}
      >
        The planner builds a ghost deck from your brief and any sources, then writes an action-title
        storyline before a single slide is rendered.
      </p>

      <div
        className="sf-brief-grid"
        style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 24, alignItems: "start" }}
      >
        {/* left: brief */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ ...card, padding: 20 }}>
            <label style={{ ...microLabel, display: "block", marginBottom: 10 }}>BRIEF</label>
            <textarea
              rows={5}
              value={p.brief}
              onChange={(e) => p.onBrief(e.target.value)}
              placeholder="e.g. Make the case to our eng leadership that adding lightweight structure to AI-assisted coding improves shipping speed and quality."
              style={{
                width: "100%",
                background: "transparent",
                border: "none",
                outline: "none",
                resize: "vertical",
                color: "var(--ink)",
                fontFamily: SERIF,
                fontSize: 18,
                lineHeight: 1.5,
              }}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div style={{ ...card, padding: "16px 18px" }}>
              <label style={{ ...microLabel, display: "block", marginBottom: 9 }}>AUDIENCE</label>
              <input
                value={p.audience}
                onChange={(e) => p.onAudience(e.target.value)}
                placeholder="VP Engineering + staff eng"
                style={{
                  width: "100%",
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "var(--ink)",
                  font: "inherit",
                  fontSize: 14,
                  fontWeight: 500,
                }}
              />
            </div>
            <div style={{ ...card, padding: "16px 18px" }}>
              <label style={{ ...microLabel, display: "block", marginBottom: 9 }}>GOAL</label>
              <input
                value={p.goal}
                onChange={(e) => p.onGoal(e.target.value)}
                placeholder="Approve a 6-week rollout"
                style={{
                  width: "100%",
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "var(--ink)",
                  font: "inherit",
                  fontSize: 14,
                  fontWeight: 500,
                }}
              />
            </div>
          </div>

          {/* documents */}
          <div style={{ ...card, padding: 20 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 12,
              }}
            >
              <label style={microLabel}>SOURCE DOCUMENTS</label>
              <span style={{ fontSize: 11, color: "var(--ink-3)" }}>
                {p.docs.length ? `${p.docs.length} attached` : "optional"}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {p.docs.map((d, i) => (
                <div
                  key={`${d.name}-${i}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "11px 13px",
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                    background: "var(--surface-2)",
                  }}
                >
                  <div
                    style={{
                      flex: "none",
                      width: 26,
                      height: 32,
                      borderRadius: 3,
                      background: "var(--surface)",
                      border: "1px solid var(--line-2)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontFamily: MONO,
                      fontSize: 8,
                      color: "var(--ink-3)",
                    }}
                  >
                    {ext(d.name)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 500,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {d.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--ink-3)" }}>{sizeLabel(d.size)}</div>
                  </div>
                  <button
                    onClick={() => p.onRemoveDoc(i)}
                    style={{
                      flex: "none",
                      width: 24,
                      height: 24,
                      borderRadius: 6,
                      border: "1px solid var(--line)",
                      background: "transparent",
                      color: "var(--ink-3)",
                      cursor: "pointer",
                      fontSize: 13,
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <input
              ref={fileRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                if (files.length) p.onAddDocs(files);
                e.target.value = "";
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              style={{
                width: "100%",
                marginTop: 10,
                padding: 12,
                border: "1.5px dashed var(--line-2)",
                borderRadius: 8,
                background: "transparent",
                color: "var(--ink-2)",
                font: "inherit",
                fontSize: 12.5,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              + Add source document
            </button>
          </div>
        </div>

        {/* right: config */}
        <div style={{ ...card, padding: 22, position: "sticky", top: 88 }}>
          <div style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
            Generation settings
          </div>

          <div style={{ ...microLabel, marginBottom: 8 }}>PLANNING</div>
          <Segmented
            value={p.planner}
            onChange={p.onPlanner}
            options={[
              { v: "fast", label: "Fast" },
              { v: "deep", label: "Deep" },
            ]}
          />
          <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 6, marginBottom: 4, lineHeight: 1.4 }}>
            {p.planner === "deep"
              ? "Authors one focused pass per slide — sharper, slower on local models."
              : "Authors slides in batches — quicker; both rewrite the title ladder into a story."}
          </div>

          <div style={{ ...microLabel, marginBottom: 8 }}>QUALITY</div>
          <Segmented
            value={p.quality}
            onChange={p.onQuality}
            options={[
              { v: "fast", label: "Fast" },
              { v: "balanced", label: "Balanced" },
              { v: "showcase", label: "Showcase" },
            ]}
          />

          <div style={{ ...microLabel, marginBottom: 8 }}>LENGTH</div>
          <Segmented
            value={p.length}
            onChange={p.onLength}
            options={[
              { v: "auto", label: "Auto" },
              { v: "concise", label: "Concise" },
              { v: "expanded", label: "Expanded" },
            ]}
          />

          <div style={{ ...microLabel, marginBottom: 8 }}>PRESENTATION STYLE</div>
          <Dropdown
            value={p.presentationStyle}
            onChange={p.onPresentationStyle}
            options={[
              { v: "auto", label: "Auto (infer from brief)" },
              { v: "consulting", label: "Consulting / strategy" },
              { v: "investor_pitch", label: "Investor pitch" },
              { v: "sales", label: "Sales deck" },
              { v: "academic_lecture", label: "Academic lecture" },
              { v: "technical_deep_dive", label: "Technical deep-dive" },
              { v: "keynote_narrative", label: "Keynote / narrative" },
              { v: "status_report_qbr", label: "Status report / QBR" },
            ]}
          />

          <div style={{ ...microLabel, marginBottom: 8 }}>DESIGN LANGUAGE</div>
          <Dropdown
            value={p.designLanguage}
            onChange={p.onDesignLanguage}
            options={[
              { v: "auto", label: "Auto (match topic & style)" },
              { v: "editorial_serif", label: "Editorial serif" },
              { v: "modern_geometric", label: "Modern geometric" },
              { v: "bold_minimal", label: "Bold minimal" },
              { v: "warm_magazine", label: "Warm magazine" },
              { v: "technical_mono", label: "Technical mono" },
              { v: "data_forward", label: "Data forward" },
            ]}
          />

          <div style={{ ...microLabel, marginBottom: 8 }}>SLIDE BACKGROUNDS</div>
          <Dropdown
            value={p.backgroundStyle}
            onChange={p.onBackgroundStyle}
            options={[
              { v: "auto", label: "Auto (dark/light rhythm)" },
              { v: "light", label: "Light — white slides after the cover" },
              { v: "dark", label: "Dark — full-color throughout" },
            ]}
          />

          <div
            onClick={p.onToggleVisualQa}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 14px",
              border: "1px solid var(--line)",
              borderRadius: 8,
              cursor: "pointer",
              marginBottom: 22,
            }}
          >
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Visual QA repair loop</div>
              <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 1 }}>
                Render, inspect, re-fix slides
              </div>
            </div>
            <div
              style={{
                flex: "none",
                width: 38,
                height: 22,
                borderRadius: 11,
                background: p.visualQa ? "var(--accent)" : "var(--line-2)",
                position: "relative",
                transition: "background .2s",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: 2,
                  left: p.visualQa ? 18 : 2,
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: "#fff",
                  boxShadow: "0 1px 2px rgba(0,0,0,.3)",
                  transition: "left .2s",
                }}
              />
            </div>
          </div>

          <button
            onClick={p.onGenerate}
            disabled={p.submitting}
            style={{
              width: "100%",
              height: 48,
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "none",
              borderRadius: 9,
              font: "inherit",
              fontSize: 15,
              fontWeight: 700,
              cursor: p.submitting ? "default" : "pointer",
              boxShadow: "var(--shadow)",
              opacity: p.submitting ? 0.75 : 1,
            }}
          >
            {p.submitting ? "Starting…" : "Generate deck"}
          </button>
          {p.mode !== "strict" && (
            <button
              onClick={p.onPreviewPlan}
              disabled={p.submitting}
              style={{
                width: "100%",
                height: 42,
                marginTop: 10,
                background: "var(--surface)",
                color: "var(--ink)",
                border: "1px solid var(--line-2)",
                borderRadius: 8,
                font: "inherit",
                fontSize: 13,
                fontWeight: 700,
                cursor: p.submitting ? "default" : "pointer",
                opacity: p.submitting ? 0.75 : 1,
              }}
            >
              Preview plan
            </button>
          )}
          {p.error && (
            <div style={{ textAlign: "center", fontSize: 11, color: "var(--bad)", marginTop: 10 }}>
              {p.error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
