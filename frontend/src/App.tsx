import { useEffect, useState } from "react";
import {
  listJobs,
  listTemplates,
  TemplateProfile,
  JobRecord,
} from "./api/client";
import TemplateSetupPage from "./pages/TemplateSetupPage";
import TemplateDetailPage from "./pages/TemplateDetailPage";
import GenerateDeckPage from "./pages/GenerateDeckPage";
import ReviewDownloadPage from "./pages/ReviewDownloadPage";

type Tab = "templates" | "generate" | "review";

export default function App() {
  const [templates, setTemplates] = useState<TemplateProfile[]>([]);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>("templates");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  const refreshTemplates = async () => {
    const data = await listTemplates();
    setTemplates(data);
  };

  const refreshJobs = async () => {
    const data = await listJobs();
    setJobs(data);
  };

  useEffect(() => {
    refreshTemplates();
    refreshJobs();
  }, []);

  return (
    <div className="container">
      <h1>SlideForge</h1>
      <div className="tabs">
        <button
          className={`tab ${activeTab === "templates" ? "active" : ""}`}
          onClick={() => setActiveTab("templates")}
        >
          Template Setup
        </button>
        <button
          className={`tab ${activeTab === "generate" ? "active" : ""}`}
          onClick={() => setActiveTab("generate")}
        >
          Generate Deck
        </button>
        <button
          className={`tab ${activeTab === "review" ? "active" : ""}`}
          onClick={() => setActiveTab("review")}
        >
          Review & Download
        </button>
      </div>

      {activeTab === "templates" && (
        <>
          <TemplateSetupPage
            onTemplateCreated={(template) => {
              setTemplates((prev) => [...prev, template]);
              refreshTemplates();
            }}
          />
          <div className="card">
            <h2>Saved Templates</h2>
            {templates.length === 0 ? (
              <p className="status">No templates yet.</p>
            ) : (
              <ul>
                {templates.map((template) => (
                  <li key={template.id}>
                    {template.name} ({template.type}) • {template.slides.length} slides
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setSelectedTemplateId(template.id)}
                    >
                      Edit Schema
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <TemplateDetailPage
            templateId={selectedTemplateId}
            onSaved={() => {
              refreshTemplates();
            }}
          />
        </>
      )}

      {activeTab === "generate" && (
        <>
          <GenerateDeckPage
            templates={templates}
            onJobCreated={(jobId) => {
              setSelectedJobId(jobId);
              refreshJobs();
              setActiveTab("review");
            }}
          />
          <div className="card">
            <h2>Recent Jobs</h2>
            {jobs.length === 0 ? (
              <p className="status">No jobs yet.</p>
            ) : (
              <ul>
                {jobs.map((job) => (
                  <li key={job.id}>
                    {job.id} • {job.status} •{" "}
                    {Math.round(job.progress * 100)}%
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setSelectedJobId(job.id);
                        setActiveTab("review");
                      }}
                    >
                      View
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {activeTab === "review" && (
        <ReviewDownloadPage jobId={selectedJobId} />
      )}
    </div>
  );
}
