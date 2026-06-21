import { JobRecord, TemplateProfile } from "../api/client";
import { card, microLabel, MONO, SERIF } from "../ui";

type Props = {
  jobs: JobRecord[];
  templates: TemplateProfile[];
  activeJobId: string | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onOpenJob: (job: JobRecord) => void;
  onUseTemplate: (template: TemplateProfile) => void;
  onEditTemplate: (template: TemplateProfile) => void;
};

function modeLabel(job: JobRecord): string {
  return String(job.config_json?.generation_mode || "freeform").toUpperCase();
}

function progress(job: JobRecord): string {
  return `${Math.round((job.progress || 0) * 100)}%`;
}

function templateKind(template: TemplateProfile): "brand" | "strict" | "other" {
  return template.type === "brand" || template.type === "strict" ? template.type : "other";
}

const tinyBtn = {
  height: 28,
  padding: "0 9px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--surface)",
  color: "var(--ink-2)",
  font: "inherit",
  fontSize: 11.5,
  fontWeight: 700,
  cursor: "pointer",
};

export default function LibraryRail({
  jobs,
  templates,
  activeJobId,
  loading,
  error,
  onRefresh,
  onOpenJob,
  onUseTemplate,
  onEditTemplate,
}: Props) {
  const recentJobs = jobs.slice(0, 6);
  const savedTemplates = templates
    .filter((template) => templateKind(template) !== "other")
    .slice(0, 8);

  return (
    <aside style={{ ...card, padding: 18, alignSelf: "start", position: "sticky", top: 88 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 600 }}>Library</div>
          <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 2 }}>
            Jobs and saved templates
          </div>
        </div>
        <button style={tinyBtn} onClick={onRefresh} disabled={loading}>
          {loading ? "..." : "Refresh"}
        </button>
      </div>

      {error && <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--bad)" }}>{error}</div>}

      <div style={{ ...microLabel, margin: "22px 0 10px" }}>RECENT JOBS</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {recentJobs.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--ink-3)", lineHeight: 1.4 }}>
            No jobs yet.
          </div>
        ) : (
          recentJobs.map((job) => {
            const active = job.id === activeJobId;
            return (
              <button
                key={job.id}
                onClick={() => onOpenJob(job)}
                style={{
                  textAlign: "left",
                  border: `1px solid ${active ? "var(--accent)" : "var(--line)"}`,
                  background: active ? "var(--accent-soft)" : "var(--surface-2)",
                  color: "var(--ink)",
                  borderRadius: 8,
                  padding: "10px 11px",
                  cursor: "pointer",
                  font: "inherit",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    marginBottom: 5,
                  }}
                >
                  <span style={{ fontSize: 12.5, fontWeight: 700 }}>
                    {job.status === "done" ? "Review deck" : job.status}
                  </span>
                  <span style={{ fontFamily: MONO, fontSize: 9.5, color: "var(--ink-3)" }}>
                    {progress(job)}
                  </span>
                </div>
                <div style={{ fontFamily: MONO, fontSize: 9.5, color: "var(--ink-3)" }}>
                  {modeLabel(job)} · {job.id.slice(0, 8)}
                </div>
              </button>
            );
          })
        )}
      </div>

      <div style={{ ...microLabel, margin: "22px 0 10px" }}>SAVED TEMPLATES</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {savedTemplates.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--ink-3)", lineHeight: 1.4 }}>
            No brand or strict templates yet.
          </div>
        ) : (
          savedTemplates.map((template) => {
            const strict = template.type === "strict";
            return (
              <div
                key={template.id}
                style={{
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  background: "var(--surface-2)",
                  padding: "10px 11px",
                }}
              >
                <div
                  style={{
                    fontSize: 12.5,
                    fontWeight: 700,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={template.name}
                >
                  {template.name}
                </div>
                <div style={{ fontFamily: MONO, fontSize: 9.5, color: "var(--ink-3)", marginTop: 4 }}>
                  {template.type.toUpperCase()} · {template.slides.length} slides
                </div>
                <div style={{ display: "flex", gap: 7, marginTop: 9 }}>
                  <button style={tinyBtn} onClick={() => onUseTemplate(template)}>
                    Use
                  </button>
                  {strict && (
                    <button style={tinyBtn} onClick={() => onEditTemplate(template)}>
                      Edit schema
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
