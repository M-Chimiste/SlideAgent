import { useEffect, useMemo, useState } from "react";
import {
  getTemplate,
  SlideField,
  TemplateProfile,
  updateTemplate,
} from "../api/client";

type Props = {
  templateId: string | null;
  onSaved: (template: TemplateProfile) => void;
};

export default function TemplateDetailPage({ templateId, onSaved }: Props) {
  const [template, setTemplate] = useState<TemplateProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!templateId) {
      setTemplate(null);
      return;
    }
    const load = async () => {
      try {
        const result = await getTemplate(templateId);
        setTemplate(result);
      } catch (err: any) {
        setError(err.message || "Failed to load template details.");
      }
    };
    load();
  }, [templateId]);

  const strictSlides = useMemo(() => {
    if (!template) return [];
    return template.slides.filter((slide) => slide.mode === "strict");
  }, [template]);

  const updateField = (
    slideIndex: number,
    fieldId: string,
    updates: Partial<SlideField>
  ) => {
    if (!template) return;
    const nextSlides = template.slides.map((slide) => {
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
    });
    setTemplate({ ...template, slides: nextSlides });
  };

  const saveTemplate = async () => {
    if (!template) return;
    setSaving(true);
    setError("");
    try {
      const updated = await updateTemplate(template.id, { slides: template.slides });
      setTemplate(updated);
      onSaved(updated);
    } catch (err: any) {
      setError(err.message || "Failed to save template.");
    } finally {
      setSaving(false);
    }
  };

  if (!templateId) {
    return (
      <div className="card">
        <h2>Template Schema Editor</h2>
        <p className="status">Select a template to edit strict-slide schema fields.</p>
      </div>
    );
  }

  if (!template) {
    return (
      <div className="card">
        <h2>Template Schema Editor</h2>
        <p className="status">Loading template...</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Template Schema Editor</h2>
      <p className="status">
        Editing: {template.name}. Strict slides: {strictSlides.length}.
      </p>
      {strictSlides.map((slide) => (
        <div key={slide.index} className="card">
          <h3>
            Slide {slide.index + 1}: {slide.label}
          </h3>
          <p className="status">{slide.classification_reason || "No reason provided."}</p>
          {!slide.schema?.fields?.length && (
            <p className="status">No extracted fields. Add overrides later if needed.</p>
          )}
          {slide.schema?.fields?.map((field) => (
            <div key={field.id} className="row">
              <div className="column">
                <label>Field ID</label>
                <input value={field.id} disabled />
              </div>
              <div className="column">
                <label>Type</label>
                <input value={field.type} disabled />
              </div>
              <div className="column">
                <label>Required</label>
                <select
                  value={field.required ? "yes" : "no"}
                  onChange={(e) =>
                    updateField(slide.index, field.id, {
                      required: e.target.value === "yes",
                    })
                  }
                >
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </div>
              <div className="column">
                <label>Max Chars</label>
                <input
                  type="number"
                  value={field.max_chars ?? ""}
                  onChange={(e) =>
                    updateField(slide.index, field.id, {
                      max_chars: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                />
              </div>
              <div className="column">
                <label>Allowed Values (comma-separated)</label>
                <input
                  value={(field.values || []).join(", ")}
                  onChange={(e) =>
                    updateField(slide.index, field.id, {
                      values: e.target.value
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </div>
            </div>
          ))}
        </div>
      ))}
      <div className="row">
        <div className="column">
          <button type="button" disabled={saving} onClick={saveTemplate}>
            {saving ? "Saving..." : "Save Schema Overrides"}
          </button>
        </div>
      </div>
      {error && <p className="status">{error}</p>}
    </div>
  );
}
