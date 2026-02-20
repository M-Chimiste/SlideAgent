import { useState } from "react";
import { createJob, TemplateProfile } from "../api/client";

type Props = {
  templates: TemplateProfile[];
  onJobCreated: (jobId: string) => void;
};

export default function GenerateDeckPage({ templates, onJobCreated }: Props) {
  const [templateId, setTemplateId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [documents, setDocuments] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!templateId || documents.length === 0) {
      setError("Select a template and upload at least one document.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("template_id", templateId);
      formData.append("instructions", instructions);
      documents.forEach((doc) => formData.append("documents", doc));
      const job = await createJob(formData);
      onJobCreated(job.id);
      setDocuments([]);
      setInstructions("");
    } catch (err: any) {
      setError(err.message || "Failed to create job.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <h2>Generate Deck</h2>
      <p className="status">Choose a template, upload docs, then generate.</p>
      <form onSubmit={handleSubmit} className="row">
        <div className="column">
          <label>Template</label>
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            <option value="">Select template</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name} ({template.type})
              </option>
            ))}
          </select>
        </div>
        <div className="column">
          <label>Instructions (optional)</label>
          <textarea
            rows={3}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </div>
        <div className="column">
          <label>Source Documents</label>
          <input
            type="file"
            multiple
            onChange={(e) => setDocuments(Array.from(e.target.files || []))}
          />
        </div>
        <div className="column">
          <label>&nbsp;</label>
          <button type="submit" disabled={loading}>
            {loading ? "Generating..." : "Generate Deck"}
          </button>
        </div>
      </form>
      {error && <p className="status">{error}</p>}
    </div>
  );
}
