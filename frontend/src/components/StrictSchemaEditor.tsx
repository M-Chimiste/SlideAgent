import { useEffect, useMemo, useState } from "react";
import { SlideField, SlideSpec, TemplateProfile } from "../api/client";
import { card, ghostBtn, microLabel, MONO, primaryBtn, SERIF } from "../ui";

type Props = {
  template: TemplateProfile;
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (slides: SlideSpec[]) => void;
};

function valuesText(field: SlideField): string {
  return (field.values || []).join(", ");
}

function parseValues(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function StrictSchemaEditor({
  template,
  saving,
  error,
  onClose,
  onSave,
}: Props) {
  const [slides, setSlides] = useState<SlideSpec[]>(template.slides);

  useEffect(() => {
    setSlides(template.slides);
  }, [template]);

  const strictSlides = useMemo(
    () => slides.filter((slide) => slide.mode === "strict"),
    [slides]
  );

  const updateField = (
    slideIndex: number,
    fieldId: string,
    updates: Partial<SlideField>
  ) => {
    setSlides((current) =>
      current.map((slide) => {
        if (slide.index !== slideIndex || !slide.schema) return slide;
        return {
          ...slide,
          schema: {
            ...slide.schema,
            fields: slide.schema.fields.map((field) =>
              field.id === fieldId ? { ...field, ...updates } : field
            ),
          },
        };
      })
    );
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        background: "rgba(20,14,6,.55)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 34,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          ...card,
          width: "min(980px, 100%)",
          maxHeight: "86vh",
          overflow: "auto",
          padding: 24,
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 18,
            marginBottom: 20,
          }}
        >
          <div>
            <div style={microLabel}>STRICT TEMPLATE</div>
            <div style={{ fontFamily: SERIF, fontSize: 24, fontWeight: 600, marginTop: 6 }}>
              {template.name}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--ink-3)", marginTop: 4 }}>
              Edit field constraints used by XML injection.
            </div>
          </div>
          <button style={ghostBtn} onClick={onClose}>
            Close
          </button>
        </div>

        {strictSlides.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--ink-3)" }}>
            This template has no strict slides with editable schema fields.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {strictSlides.map((slide) => (
              <div key={slide.index} style={{ border: "1px solid var(--line)", borderRadius: 9 }}>
                <div
                  style={{
                    padding: "13px 15px",
                    borderBottom: "1px solid var(--line)",
                    background: "var(--surface-2)",
                    borderRadius: "9px 9px 0 0",
                  }}
                >
                  <div style={{ fontSize: 13.5, fontWeight: 700 }}>
                    Slide {slide.index + 1}: {slide.label}
                  </div>
                  {slide.classification_reason && (
                    <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 3 }}>
                      {slide.classification_reason}
                    </div>
                  )}
                </div>

                {(slide.schema?.fields ?? []).length === 0 ? (
                  <div style={{ padding: 15, fontSize: 12.5, color: "var(--ink-3)" }}>
                    No extracted fields.
                  </div>
                ) : (
                  <div style={{ padding: 15, display: "flex", flexDirection: "column", gap: 11 }}>
                    {(slide.schema?.fields ?? []).map((field) => (
                      <div
                        key={field.id}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1.1fr .65fr .55fr .7fr 1.4fr",
                          gap: 10,
                          alignItems: "end",
                        }}
                      >
                        <div>
                          <div style={{ ...microLabel, marginBottom: 6 }}>FIELD ID</div>
                          <div
                            style={{
                              minHeight: 36,
                              display: "flex",
                              alignItems: "center",
                              border: "1px solid var(--line)",
                              borderRadius: 7,
                              padding: "0 10px",
                              fontFamily: MONO,
                              fontSize: 11,
                              color: "var(--ink-2)",
                            }}
                          >
                            {field.id}
                          </div>
                        </div>
                        <div>
                          <div style={{ ...microLabel, marginBottom: 6 }}>TYPE</div>
                          <div
                            style={{
                              minHeight: 36,
                              display: "flex",
                              alignItems: "center",
                              border: "1px solid var(--line)",
                              borderRadius: 7,
                              padding: "0 10px",
                              fontSize: 12,
                              color: "var(--ink-2)",
                            }}
                          >
                            {field.type}
                          </div>
                        </div>
                        <label>
                          <div style={{ ...microLabel, marginBottom: 6 }}>REQUIRED</div>
                          <select
                            value={field.required ? "yes" : "no"}
                            onChange={(e) =>
                              updateField(slide.index, field.id, {
                                required: e.target.value === "yes",
                              })
                            }
                            style={{
                              width: "100%",
                              height: 36,
                              borderRadius: 7,
                              border: "1px solid var(--line)",
                              background: "var(--surface)",
                              color: "var(--ink)",
                              font: "inherit",
                              fontSize: 12,
                            }}
                          >
                            <option value="yes">Yes</option>
                            <option value="no">No</option>
                          </select>
                        </label>
                        <label>
                          <div style={{ ...microLabel, marginBottom: 6 }}>MAX CHARS</div>
                          <input
                            type="number"
                            value={field.max_chars ?? ""}
                            onChange={(e) =>
                              updateField(slide.index, field.id, {
                                max_chars: e.target.value ? Number(e.target.value) : null,
                              })
                            }
                            style={{
                              width: "100%",
                              height: 36,
                              borderRadius: 7,
                              border: "1px solid var(--line)",
                              background: "var(--surface)",
                              color: "var(--ink)",
                              font: "inherit",
                              fontSize: 12,
                              padding: "0 9px",
                            }}
                          />
                        </label>
                        <label>
                          <div style={{ ...microLabel, marginBottom: 6 }}>ALLOWED VALUES</div>
                          <input
                            value={valuesText(field)}
                            onChange={(e) =>
                              updateField(slide.index, field.id, {
                                values: parseValues(e.target.value),
                              })
                            }
                            style={{
                              width: "100%",
                              height: 36,
                              borderRadius: 7,
                              border: "1px solid var(--line)",
                              background: "var(--surface)",
                              color: "var(--ink)",
                              font: "inherit",
                              fontSize: 12,
                              padding: "0 9px",
                            }}
                          />
                        </label>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {error && <div style={{ marginTop: 14, fontSize: 12, color: "var(--bad)" }}>{error}</div>}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            borderTop: "1px solid var(--line)",
            paddingTop: 18,
            marginTop: 22,
          }}
        >
          <button style={ghostBtn} onClick={onClose}>
            Cancel
          </button>
          <button
            style={{ ...primaryBtn, opacity: saving ? 0.7 : 1 }}
            onClick={() => onSave(slides)}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save schema"}
          </button>
        </div>
      </div>
    </div>
  );
}
