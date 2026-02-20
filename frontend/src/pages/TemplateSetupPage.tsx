import { useState } from "react";
import { analyzeTemplate, TemplateProfile } from "../api/client";

type Props = {
  onTemplateCreated: (template: TemplateProfile) => void;
};

export default function TemplateSetupPage({ onTemplateCreated }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState("brand");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file || !name) {
      setError("Template name and file are required.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("name", name);
      formData.append("template_type", type);
      const template = await analyzeTemplate(formData);
      onTemplateCreated(template);
      setName("");
      setFile(null);
    } catch (err: any) {
      setError(err.message || "Failed to analyze template.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <h2>Template Setup</h2>
      <p className="status">
        Upload a PPTX template and classify it as brand or strict.
      </p>
      <form onSubmit={handleSubmit} className="row">
        <div className="column">
          <label>Template Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="column">
          <label>Template Type</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="brand">Brand</option>
            <option value="strict">Strict</option>
          </select>
        </div>
        <div className="column">
          <label>Template File (.pptx)</label>
          <input
            type="file"
            accept=".pptx"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </div>
        <div className="column">
          <label>&nbsp;</label>
          <button type="submit" disabled={loading}>
            {loading ? "Analyzing..." : "Analyze Template"}
          </button>
        </div>
      </form>
      {error && <p className="status">{error}</p>}
    </div>
  );
}
