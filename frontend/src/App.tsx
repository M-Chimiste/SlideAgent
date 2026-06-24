import { useEffect, useState } from "react";
import {
  analyzeTemplate,
  createJob,
  getJobOutline,
  getJobStatus,
  getPlanningArtifact,
  JobRecord,
  JobOutlineSlide,
  JobStatus,
  listJobs,
  listTemplates,
  OutlineEdit,
  patchJobOutline,
  PlanningArtifactName,
  regenerateSlide,
  renderPlannedJob,
  SlideSpec,
  TemplateProfile,
  updateTemplate,
} from "./api/client";
import { Length, Mode, Planner, Quality, Screen, Theme } from "./types";
import TopBar from "./components/TopBar";
import Stepper from "./components/Stepper";
import ModeScreen from "./components/ModeScreen";
import SetupScreen from "./components/SetupScreen";
import BriefScreen from "./components/BriefScreen";
import JobScreen from "./components/JobScreen";
import PlanReviewScreen from "./components/PlanReviewScreen";
import ReviewScreen from "./components/ReviewScreen";
import SlideLightbox from "./components/SlideLightbox";
import LibraryRail from "./components/LibraryRail";
import StrictSchemaEditor from "./components/StrictSchemaEditor";

const TERMINAL = new Set(["planned", "done", "error"]);
type PlanningArtifacts = { source?: any; story?: any; gate?: any };

export default function App() {
  // ── presentation ──
  const [theme, setTheme] = useState<Theme>("light");
  const [screen, setScreen] = useState<Screen>("mode");

  // ── deck config ──
  const [mode, setMode] = useState<Mode>("freeform");
  const [planner, setPlanner] = useState<Planner>("fast");
  const [quality, setQuality] = useState<Quality>("balanced");
  const [length, setLength] = useState<Length>("auto");
  const [visualQa, setVisualQa] = useState(true);

  // ── brief ──
  const [brief, setBrief] = useState("");
  const [audience, setAudience] = useState("");
  const [goal, setGoal] = useState("");
  const [docs, setDocs] = useState<File[]>([]);

  // ── template (brand / strict) ──
  const [template, setTemplate] = useState<TemplateProfile | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [schemaTemplate, setSchemaTemplate] = useState<TemplateProfile | null>(null);
  const [schemaSaving, setSchemaSaving] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  // ── job ──
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ── plan review ──
  const [outline, setOutline] = useState<JobOutlineSlide[]>([]);
  const [planningArtifacts, setPlanningArtifacts] = useState<PlanningArtifacts>({});
  const [planningLoading, setPlanningLoading] = useState(false);
  const [planningError, setPlanningError] = useState<string | null>(null);
  const [outlineSaving, setOutlineSaving] = useState(false);
  const [renderingPlan, setRenderingPlan] = useState(false);

  // ── review / lightbox ──
  const [openSlide, setOpenSlide] = useState<number | null>(null);
  const [regening, setRegening] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);

  // ── library ──
  const [templates, setTemplates] = useState<TemplateProfile[]>([]);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState<string | null>(null);

  const refreshLibrary = async () => {
    setLibraryLoading(true);
    setLibraryError(null);
    try {
      const [nextTemplates, nextJobs] = await Promise.all([listTemplates(), listJobs()]);
      setTemplates(nextTemplates);
      setJobs(nextJobs);
    } catch (err: any) {
      setLibraryError(err?.message || "Failed to load library.");
    } finally {
      setLibraryLoading(false);
    }
  };

  useEffect(() => {
    refreshLibrary();
  }, []);

  // poll the job while the Generate screen is showing
  useEffect(() => {
    if (!jobId || screen !== "job") return;
    let active = true;
    const tick = async () => {
      try {
        const s = await getJobStatus(jobId);
        if (!active) return;
        setStatus(s);
        if (TERMINAL.has(s.job.status)) window.clearInterval(timer);
      } catch {
        /* keep polling */
      }
    };
    tick();
    const timer = window.setInterval(tick, 1500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [jobId, screen]);

  useEffect(() => {
    if (!jobId || !status || (screen !== "plan" && screen !== "review")) return;
    loadPlanningContext(jobId);
  }, [jobId, screen, status?.job.status]);

  async function loadPlanningContext(targetJobId: string) {
    setPlanningLoading(true);
    setPlanningError(null);
    try {
      const artifactNames: PlanningArtifactName[] = ["source-compression", "story-map", "spec-gate"];
      const [outlineResult, ...artifactResults] = await Promise.allSettled([
        getJobOutline(targetJobId),
        ...artifactNames.map((artifact) => getPlanningArtifact(targetJobId, artifact)),
      ]);
      if (outlineResult.status === "fulfilled") {
        setOutline(outlineResult.value.slides);
      } else {
        setOutline([]);
        setPlanningError(outlineResult.reason?.message || "Failed to load plan outline.");
      }
      const nextArtifacts: PlanningArtifacts = {};
      artifactResults.forEach((result, index) => {
        if (result.status !== "fulfilled") return;
        const key = artifactNames[index] === "source-compression"
          ? "source"
          : artifactNames[index] === "story-map"
            ? "story"
            : "gate";
        nextArtifacts[key] = result.value;
      });
      setPlanningArtifacts(nextArtifacts);
    } finally {
      setPlanningLoading(false);
    }
  }

  const changeMode = (m: Mode) => {
    if (m === mode) return;
    setMode(m);
    setTemplate(null);
    setAnalyzeError(null);
  };

  const goHome = () => {
    setScreen("mode");
    setJobId(null);
    setStatus(null);
    setOutline([]);
    setPlanningArtifacts({});
    setOpenSlide(null);
    setSubmitError(null);
    setPlanningError(null);
    setRegenError(null);
  };

  const applyJobConfig = (job: JobRecord) => {
    const nextMode = String(job.config_json?.generation_mode || "freeform");
    if (nextMode === "freeform" || nextMode === "brand" || nextMode === "strict") setMode(nextMode);
    const nextPlanner = String(job.config_json?.planner_profile || "fast");
    if (nextPlanner === "fast" || nextPlanner === "deep") setPlanner(nextPlanner);
    const nextQuality = String(job.config_json?.quality_profile || "balanced");
    if (nextQuality === "fast" || nextQuality === "balanced" || nextQuality === "showcase") {
      setQuality(nextQuality);
    }
    setBrief((job.instructions || "").split("\n\nAudience:")[0]);
  };

  const openLibraryJob = async (job: JobRecord) => {
    setLibraryError(null);
    setOpenSlide(null);
    setRegenError(null);
    setJobId(job.id);
    applyJobConfig(job);
    try {
      const nextStatus = await getJobStatus(job.id);
      setStatus(nextStatus);
      setScreen(
        nextStatus.job.status === "planned"
          ? "plan"
          : nextStatus.job.status === "done"
            ? "review"
            : "job"
      );
    } catch (err: any) {
      setLibraryError(err?.message || "Failed to open job.");
    }
  };

  const useTemplateFromLibrary = (nextTemplate: TemplateProfile) => {
    const nextMode =
      nextTemplate.type === "brand" ? "brand" : nextTemplate.type === "strict" ? "strict" : null;
    if (!nextMode) return;
    setMode(nextMode);
    setTemplate(nextTemplate);
    setAnalyzeError(null);
    setSubmitError(null);
    setScreen("brief");
  };

  const editTemplateSchema = (nextTemplate: TemplateProfile) => {
    setSchemaTemplate(nextTemplate);
    setSchemaError(null);
  };

  const saveTemplateSchema = async (slides: SlideSpec[]) => {
    if (!schemaTemplate) return;
    setSchemaSaving(true);
    setSchemaError(null);
    try {
      const updated = await updateTemplate(schemaTemplate.id, { slides });
      setTemplates((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      if (template?.id === updated.id) setTemplate(updated);
      setSchemaTemplate(updated);
      setSchemaTemplate(null);
      await refreshLibrary();
    } catch (err: any) {
      setSchemaError(err?.message || "Failed to save schema.");
    } finally {
      setSchemaSaving(false);
    }
  };

  const continueFromMode = () => setScreen(mode === "freeform" ? "brief" : "setup");

  const handleUpload = async (file: File) => {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", file.name.replace(/\.pptx$/i, ""));
      form.append("template_type", mode);
      const profile = await analyzeTemplate(form);
      setTemplate(profile);
      await refreshLibrary();
    } catch (err: any) {
      setAnalyzeError(err?.message || "Template analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  };

  const startJob = async (planOnly = false) => {
    if (!brief.trim() && docs.length === 0) {
      setSubmitError("Add a brief or at least one source document.");
      return;
    }
    if (mode !== "freeform" && !template) {
      setSubmitError("Upload and analyze a template first.");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      let instructions = brief.trim();
      if (audience.trim()) instructions += `\n\nAudience: ${audience.trim()}`;
      if (goal.trim()) instructions += `\n\nGoal: ${goal.trim()}`;

      const form = new FormData();
      form.append("generation_mode", mode);
      form.append("planner_profile", planner);
      form.append("quality_profile", quality);
      form.append("length_strategy", length);
      form.append("run_visual_qa", String(visualQa));
      form.append("plan_only", String(planOnly));
      if (mode !== "freeform" && template) form.append("template_id", template.id);
      form.append("instructions", instructions);
      docs.forEach((doc) => form.append("documents", doc));

      const job = await createJob(form);
      setJobId(job.id);
      setJobs((prev) => [job, ...prev.filter((existing) => existing.id !== job.id)]);
      setStatus(null);
      setOutline([]);
      setPlanningArtifacts({});
      setPlanningError(null);
      setRegenError(null);
      setScreen("job");
      await refreshLibrary();
    } catch (err: any) {
      setSubmitError(err?.message || "Failed to start the job.");
    } finally {
      setSubmitting(false);
    }
  };

  const savePlanEdits = async (edits: OutlineEdit[]) => {
    if (!jobId || edits.length === 0) return;
    setOutlineSaving(true);
    setPlanningError(null);
    try {
      const next = await patchJobOutline(jobId, edits);
      setOutline(next.slides);
    } catch (err: any) {
      setPlanningError(err?.message || "Failed to save outline edits.");
    } finally {
      setOutlineSaving(false);
    }
  };

  const renderPlan = async () => {
    if (!jobId) return;
    setRenderingPlan(true);
    setPlanningError(null);
    try {
      const queuedJob = await renderPlannedJob(jobId);
      setStatus((prev) => (prev ? { ...prev, job: queuedJob, warnings: queuedJob.warnings ?? prev.warnings } : prev));
      setScreen("job");
      await refreshLibrary();
    } catch (err: any) {
      setPlanningError(err?.message || "Failed to render the planned deck.");
    } finally {
      setRenderingPlan(false);
    }
  };

  const handleRegen = async () => {
    if (!jobId || openSlide == null) return;
    setRegening(true);
    setRegenError(null);
    try {
      await regenerateSlide(jobId, openSlide);
      const s = await getJobStatus(jobId);
      setStatus(s);
      await refreshLibrary();
    } catch (err: any) {
      setRegenError(err?.message || "Failed to regenerate slide.");
    } finally {
      setRegening(false);
    }
  };

  const deckTitle =
    (brief.trim().split("\n").find((l) => l.trim())?.trim() || goal.trim() || "Generated deck").slice(
      0,
      80
    );

  return (
    <div
      data-theme={theme}
      style={{
        minHeight: "100vh",
        background: "var(--paper)",
        color: "var(--ink)",
        fontFamily: "'Hanken Grotesk', system-ui, sans-serif",
      }}
    >
      <TopBar theme={theme} onTheme={setTheme} onHome={goHome} />
      <Stepper mode={mode} screen={screen} onJump={setScreen} />

      <main
        style={{
          maxWidth: 1400,
          margin: "0 auto",
          padding: "48px 28px 96px",
          display: "grid",
          gridTemplateColumns: "270px minmax(0, 1120px)",
          gap: 28,
          alignItems: "start",
        }}
        className="sf-app-shell"
      >
        <LibraryRail
          jobs={jobs}
          templates={templates}
          activeJobId={jobId}
          loading={libraryLoading}
          error={libraryError}
          onRefresh={refreshLibrary}
          onOpenJob={openLibraryJob}
          onUseTemplate={useTemplateFromLibrary}
          onEditTemplate={editTemplateSchema}
        />

        <div style={{ minWidth: 0 }}>
          {screen === "mode" && (
            <ModeScreen mode={mode} onMode={changeMode} onContinue={continueFromMode} />
          )}

          {screen === "setup" && mode !== "freeform" && (
            <SetupScreen
              mode={mode}
              template={template}
              analyzing={analyzing}
              error={analyzeError}
              onUpload={handleUpload}
              onBack={() => setScreen("mode")}
              onContinue={() => setScreen("brief")}
            />
          )}

          {screen === "brief" && (
            <BriefScreen
              mode={mode}
              brief={brief}
              audience={audience}
              goal={goal}
              onBrief={setBrief}
              onAudience={setAudience}
              onGoal={setGoal}
              docs={docs}
              onAddDocs={(files) => setDocs((prev) => [...prev, ...files])}
              onRemoveDoc={(i) => setDocs((prev) => prev.filter((_, idx) => idx !== i))}
              planner={planner}
              quality={quality}
              length={length}
              visualQa={visualQa}
              onPlanner={setPlanner}
              onQuality={setQuality}
              onLength={setLength}
              onToggleVisualQa={() => setVisualQa((v) => !v)}
              submitting={submitting}
              error={submitError}
              onGenerate={() => startJob(false)}
              onPreviewPlan={() => startJob(true)}
            />
          )}

          {screen === "job" && (
            <JobScreen
              jobId={jobId}
              jobStatus={status?.job.status ?? "queued"}
              progress={status?.job.progress ?? 0}
              errorMessage={status?.job.error_message ?? null}
              onCancel={() => setScreen("brief")}
              onReview={() => setScreen(status?.job.status === "planned" ? "plan" : "review")}
            />
          )}

          {screen === "plan" && jobId && status && (
            <PlanReviewScreen
              status={status}
              outline={outline}
              artifacts={planningArtifacts}
              loading={planningLoading}
              saving={outlineSaving}
              rendering={renderingPlan}
              error={planningError}
              onSave={savePlanEdits}
              onRender={renderPlan}
              onBack={() => setScreen("brief")}
            />
          )}

          {screen === "review" && jobId && status && (
            <ReviewScreen
              jobId={jobId}
              status={status}
              mode={mode}
              planner={planner}
              quality={quality}
              deckTitle={deckTitle}
              outline={outline}
              onOpenSlide={(i) => {
                setOpenSlide(i);
                setRegenError(null);
              }}
            />
          )}
        </div>
      </main>

      {openSlide != null && jobId && status && (
        <SlideLightbox
          jobId={jobId}
          status={status}
          index={openSlide}
          outlineSlide={outline.find((slide) => slide.slide_index === openSlide)}
          regening={regening}
          regenError={regenError}
          onClose={() => setOpenSlide(null)}
          onRegen={handleRegen}
        />
      )}

      {schemaTemplate && (
        <StrictSchemaEditor
          template={schemaTemplate}
          saving={schemaSaving}
          error={schemaError}
          onClose={() => setSchemaTemplate(null)}
          onSave={saveTemplateSchema}
        />
      )}
    </div>
  );
}
