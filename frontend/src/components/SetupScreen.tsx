import { CSSProperties } from "react";
import { card, eyebrow, ghostBtn, h1, microLabel, primaryBtn, SERIF } from "../ui";
import { TemplateProfile } from "../api/client";
import { Mode } from "../types";

type Props = {
  mode: Exclude<Mode, "freeform">;
  template: TemplateProfile | null;
  analyzing: boolean;
  error: string | null;
  onUpload: (file: File) => void;
  onBack: () => void;
  onContinue: () => void;
};

const MONO = "'IBM Plex Mono', monospace";

function hex(c: string): string {
  if (!c) return "#000000";
  return c.startsWith("#") ? c : `#${c}`;
}

const colHead: CSSProperties = {
  fontFamily: MONO,
  fontSize: 9,
  letterSpacing: ".08em",
  color: "var(--ink-3)",
  padding: "10px 14px",
  background: "var(--surface-2)",
  borderBottom: "1px solid var(--line)",
};

export default function SetupScreen({
  mode,
  template,
  analyzing,
  error,
  onUpload,
  onBack,
  onContinue,
}: Props) {
  const isBrand = mode === "brand";

  const setupTitle = isBrand ? "Match an existing brand" : "Preserve a rigid template";
  const setupSub = isBrand
    ? "SlideForge reads the master deck as a visual reference — its colors, type, and layout rules guide every generated slide."
    : "The uploaded deck is the artifact of record. Structure and formatting stay intact; only mapped fields change.";

  return (
    <div className="sf-rise">
      <div style={eyebrow}>02 — TEMPLATE SETUP</div>
      <h1 style={h1}>{setupTitle}</h1>
      <p
        style={{
          fontSize: 15,
          color: "var(--ink-2)",
          margin: "0 0 32px",
          maxWidth: "60ch",
          lineHeight: 1.55,
        }}
      >
        {setupSub}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 24, alignItems: "start" }}>
        {/* upload column */}
        <div style={{ ...card, padding: 20 }}>
          <div style={{ ...microLabel, marginBottom: 12 }}>TEMPLATE FILE</div>

          {template ? (
            <>
              <div
                style={{
                  border: "1.5px solid var(--line-2)",
                  borderRadius: 9,
                  padding: 18,
                  display: "flex",
                  gap: 13,
                  alignItems: "center",
                  background: "var(--surface-2)",
                }}
              >
                <div
                  style={{
                    flex: "none",
                    width: 38,
                    height: 46,
                    borderRadius: 4,
                    background: "var(--bad-soft)",
                    border: "1px solid var(--line-2)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: MONO,
                    fontSize: 9,
                    fontWeight: 500,
                    color: "var(--bad)",
                  }}
                >
                  PPTX
                </div>
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 13.5,
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {template.name}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 2 }}>
                    {template.slides.length} slides · {template.type}
                  </div>
                </div>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginTop: 14,
                  fontSize: 12,
                  color: "var(--good)",
                }}
              >
                <span
                  style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--good)" }}
                />{" "}
                Analyzed — profile extracted
              </div>
            </>
          ) : (
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                textAlign: "center",
                border: "1.5px dashed var(--line-2)",
                borderRadius: 9,
                padding: "28px 18px",
                background: "var(--surface-2)",
                cursor: analyzing ? "default" : "pointer",
              }}
            >
              <div
                style={{
                  width: 38,
                  height: 46,
                  borderRadius: 4,
                  background: "var(--bad-soft)",
                  border: "1px solid var(--line-2)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: MONO,
                  fontSize: 9,
                  fontWeight: 500,
                  color: "var(--bad)",
                  ...(analyzing ? { animation: "sf-pulse 1.4s ease-in-out infinite" } : {}),
                }}
              >
                PPTX
              </div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {analyzing ? "Analyzing template…" : "Upload a .pptx template"}
              </div>
              <div style={{ fontSize: 11, color: "var(--ink-3)" }}>
                {analyzing ? "Extracting profile" : "Click to choose a master deck"}
              </div>
              <input
                type="file"
                accept=".pptx"
                disabled={analyzing}
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f);
                  e.target.value = "";
                }}
              />
            </label>
          )}

          {error && (
            <div style={{ marginTop: 12, fontSize: 12, color: "var(--bad)" }}>{error}</div>
          )}

          {template && (
            <>
              <div style={{ height: 1, background: "var(--line)", margin: "18px 0" }} />
              <div style={{ ...microLabel, marginBottom: 10 }}>SLIDE INVENTORY</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                {template.slides.map((iv, i) => {
                  const badge = (iv.content_category || iv.mode || "BODY").toUpperCase();
                  const strict = iv.mode?.toLowerCase() === "strict";
                  return (
                    <div
                      key={iv.index ?? i}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "8px 10px",
                        border: "1px solid var(--line)",
                        borderRadius: 7,
                        background: "var(--surface)",
                      }}
                    >
                      <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--ink-3)", width: 14 }}>
                        {i + 1}
                      </span>
                      <span
                        style={{
                          flex: 1,
                          fontSize: 12.5,
                          fontWeight: 500,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {iv.label}
                      </span>
                      <span
                        style={{
                          fontFamily: MONO,
                          fontSize: 9,
                          letterSpacing: ".06em",
                          padding: "3px 7px",
                          borderRadius: 4,
                          background: strict ? "var(--accent-soft)" : "var(--surface-2)",
                          color: strict ? "var(--accent)" : "var(--ink-3)",
                        }}
                      >
                        {badge}
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* profile column */}
        <div>
          {!template ? (
            <div
              style={{
                ...card,
                padding: 24,
                color: "var(--ink-3)",
                fontSize: 13,
                lineHeight: 1.6,
              }}
            >
              {isBrand
                ? "Upload a master deck to extract its brand DNA — theme colors, typefaces, logo placement, and layout rules will appear here."
                : "Upload a rigid template to review its field schema — the fields SlideForge will inject via XML will appear here."}
            </div>
          ) : isBrand ? (
            <BrandProfile template={template} />
          ) : (
            <StrictSchema template={template} />
          )}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 32,
        }}
      >
        <button style={ghostBtn} onClick={onBack}>
          ← Back
        </button>
        <button
          style={{
            ...primaryBtn,
            opacity: template ? 1 : 0.55,
            cursor: template ? "pointer" : "not-allowed",
          }}
          disabled={!template}
          onClick={onContinue}
        >
          Continue to brief <span style={{ fontSize: 15 }}>→</span>
        </button>
      </div>
    </div>
  );
}

function BrandProfile({ template }: { template: TemplateProfile }) {
  const c = template.brand.colors;
  const swatches = [c.primary, c.secondary, c.accent, c.background_light].filter(Boolean);
  const fonts = [
    { name: template.brand.fonts.heading, role: "TITLES" },
    { name: template.brand.fonts.body, role: "BODY" },
  ];
  const notes = (template.brand.design_notes || "")
    .split(/[\n.]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 4);
  const logoPlacement = template.brand.logo?.placement || "top-right";

  return (
    <div style={{ ...card, padding: 24 }}>
      <div style={{ fontFamily: SERIF, fontSize: 20, fontWeight: 600, marginBottom: 4 }}>
        Brand DNA
      </div>
      <div style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 22 }}>
        Extracted from the uploaded master. Generated slides will inherit this identity.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        <div>
          <div style={{ ...microLabel, marginBottom: 11 }}>THEME COLORS</div>
          <div style={{ display: "flex", gap: 8 }}>
            {swatches.map((sw, i) => (
              <div key={i} style={{ flex: 1 }}>
                <div
                  style={{
                    height: 46,
                    borderRadius: 7,
                    background: hex(sw),
                    border: "1px solid var(--line-2)",
                  }}
                />
                <div
                  style={{
                    fontFamily: MONO,
                    fontSize: 9,
                    color: "var(--ink-3)",
                    marginTop: 6,
                    textAlign: "center",
                  }}
                >
                  {hex(sw)}
                </div>
              </div>
            ))}
          </div>
          <div style={{ ...microLabel, margin: "22px 0 11px" }}>TYPEFACES</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {fonts.map((f, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  padding: "9px 12px",
                  border: "1px solid var(--line)",
                  borderRadius: 7,
                }}
              >
                <span style={{ fontSize: 16, fontWeight: 600 }}>{f.name}</span>
                <span style={{ fontFamily: MONO, fontSize: 9, color: "var(--ink-3)" }}>{f.role}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div style={{ ...microLabel, marginBottom: 11 }}>LOGO</div>
          <div
            style={{
              height: 78,
              borderRadius: 7,
              border: "1.5px dashed var(--line-2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background:
                "repeating-linear-gradient(135deg,var(--surface-2),var(--surface-2) 7px,transparent 7px,transparent 14px)",
            }}
          >
            <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--ink-3)" }}>
              logo · {logoPlacement}
            </span>
          </div>
          <div style={{ ...microLabel, margin: "22px 0 11px" }}>LAYOUT NOTES</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {notes.length ? (
              notes.map((n, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 9,
                    fontSize: 12.5,
                    color: "var(--ink-2)",
                    lineHeight: 1.4,
                  }}
                >
                  <span style={{ color: "var(--accent)", flex: "none" }}>—</span>
                  <span>{n}</span>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.4 }}>
                No layout notes extracted from this template.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StrictSchema({ template }: { template: TemplateProfile }) {
  const slide = template.slides.find((s) => (s.schema?.fields?.length ?? 0) > 0);
  const fields = slide?.schema?.fields ?? [];

  return (
    <div style={{ ...card, padding: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 4,
        }}
      >
        <div style={{ fontFamily: SERIF, fontSize: 20, fontWeight: 600 }}>Strict field schema</div>
        <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--ink-3)" }}>
          {slide ? `Slide ${(slide.index ?? 0) + 1} · ${slide.label}` : "No mapped fields"}
        </span>
      </div>
      <div style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 20 }}>
        Review the fields SlideForge will inject via XML. Geometry and formatting stay untouched.
      </div>
      {fields.length > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.4fr .9fr .7fr .7fr",
            border: "1px solid var(--line)",
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          <div style={colHead}>FIELD ID</div>
          <div style={colHead}>TYPE</div>
          <div style={colHead}>REQUIRED</div>
          <div style={colHead}>MAX</div>
          {fields.map((fd) => {
            const req = fd.required ? "YES" : "NO";
            return (
              <div key={fd.id} style={{ display: "contents" }}>
                <div
                  style={{
                    fontFamily: MONO,
                    fontSize: 12,
                    color: "var(--ink)",
                    padding: "12px 14px",
                    borderBottom: "1px solid var(--line)",
                  }}
                >
                  {fd.id}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--ink-2)",
                    padding: "12px 14px",
                    borderBottom: "1px solid var(--line)",
                  }}
                >
                  {fd.type}
                </div>
                <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
                  <span
                    style={{
                      fontFamily: MONO,
                      fontSize: 10,
                      padding: "2px 7px",
                      borderRadius: 4,
                      background: fd.required ? "var(--accent-soft)" : "var(--surface-2)",
                      color: fd.required ? "var(--accent)" : "var(--ink-3)",
                    }}
                  >
                    {req}
                  </span>
                </div>
                <div
                  style={{
                    fontFamily: MONO,
                    fontSize: 12,
                    color: "var(--ink-2)",
                    padding: "12px 14px",
                    borderBottom: "1px solid var(--line)",
                  }}
                >
                  {fd.max_chars ?? "—"}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ fontSize: 13, color: "var(--ink-3)" }}>
          No mapped fields were detected in this template.
        </div>
      )}
      <div
        style={{
          display: "flex",
          gap: 9,
          alignItems: "flex-start",
          marginTop: 16,
          padding: "12px 14px",
          borderRadius: 8,
          background: "var(--warn-soft)",
        }}
      >
        <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--warn)", flex: "none" }}>!</span>
        <span style={{ fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.45 }}>
          Unmapped required fields render{" "}
          <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--warn)" }}>
            [INSERT CONTENT HERE]
          </span>{" "}
          and surface a warning rather than failing the build.
        </span>
      </div>
    </div>
  );
}
