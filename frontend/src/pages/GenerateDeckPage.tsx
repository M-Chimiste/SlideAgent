import { useState } from "react";
import { createJob, TemplateProfile } from "../api/client";

type Props = {
  templates: TemplateProfile[];
  onJobCreated: (jobId: string) => void;
};

export default function GenerateDeckPage({ templates, onJobCreated }: Props) {
  const [generationMode, setGenerationMode] = useState("freeform");
  const [plannerProfile, setPlannerProfile] = useState("fast");
  const [qualityProfile, setQualityProfile] = useState("balanced");
  const [lengthStrategy, setLengthStrategy] = useState("auto");
  const [runVisualQa, setRunVisualQa] = useState(true);
  const [templateId, setTemplateId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [documents, setDocuments] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (generationMode !== "freeform" && !templateId) {
      setError("Select a template for brand or strict generation.");
      return;
    }
    if (!instructions.trim() && documents.length === 0) {
      setError("Add instructions or upload at least one source document.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("generation_mode", generationMode);
      formData.append("planner_profile", plannerProfile);
      formData.append("quality_profile", qualityProfile);
      formData.append("length_strategy", lengthStrategy);
      formData.append("run_visual_qa", String(runVisualQa));
      if (templateId) {
        formData.append("template_id", templateId);
      }
      formData.append("instructions", instructions);
      documents.forEach((doc) => formData.append("documents", doc));
      const job = await createJob(formData);
      onJobCreated(job.id);
      setDocuments([]);
      setInstructions("");
      if (generationMode === "freeform") {
        setTemplateId("");
      }
    } catch (err: any) {
      setError(err.message || "Failed to create job.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <h2>Generate Deck</h2>
      <p className="status">Choose a mode, add a brief or docs, then generate.</p>
      <form onSubmit={handleSubmit} className="row">
        <div className="column">
          <label>Mode</label>
          <select
            value={generationMode}
            onChange={(e) => {
              setGenerationMode(e.target.value);
              if (e.target.value === "freeform") {
                setTemplateId("");
              }
            }}
          >
            <option value="freeform">Freeform</option>
            <option value="brand">Brand / Master Template</option>
            <option value="strict">Strict Template</option>
          </select>
        </div>
        <div className="column">
          <label>Template</label>
          <select
            value={templateId}
            disabled={generationMode === "freeform"}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            <option value="">
              {generationMode === "freeform" ? "Not required" : "Select template"}
            </option>
            {templates
              .filter((template) =>
                generationMode === "freeform" ? true : template.type === generationMode
              )
              .map((template) => (
              <option key={template.id} value={template.id}>
                {template.name} ({template.type})
              </option>
            ))}
          </select>
        </div>
        <div className="column">
          <label>Planning</label>
          <select
            value={plannerProfile}
            onChange={(e) => setPlannerProfile(e.target.value)}
          >
            <option value="fast">Fast</option>
            <option value="deep">Deep</option>
          </select>
        </div>
        <div className="column">
          <label>Quality</label>
          <select
            value={qualityProfile}
            onChange={(e) => setQualityProfile(e.target.value)}
          >
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="showcase">Showcase</option>
          </select>
        </div>
        <div className="column">
          <label>Length</label>
          <select
            value={lengthStrategy}
            onChange={(e) => setLengthStrategy(e.target.value)}
          >
            <option value="auto">Auto</option>
            <option value="concise">Concise</option>
            <option value="expanded">Expanded</option>
          </select>
        </div>
        <div className="column">
          <label>Visual QA</label>
          <label className="status">
            <input
              type="checkbox"
              checked={runVisualQa}
              onChange={(e) => setRunVisualQa(e.target.checked)}
            />{" "}
            Run repair loop
          </label>
        </div>
        <div className="column">
          <label>Instructions</label>
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
