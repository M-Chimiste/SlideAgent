import { useEffect, useState } from "react";
import {
  analyzeTemplate,
  createJob,
  getJobOutline,
  getJobStatus,
  getPlanningArtifact,
  getRenderedSlideAudit,
  JobRecord,
  JobOutlineSlide,
  JobStatus,
  listJobs,
  listTemplates,
  OutlineEdit,
  patchJobOutline,
  PlanningArtifactName,
  RenderedSlideAudit,
  regenerateSlide,
  updateSlide,
  SlideEditPayload,
  renderPlannedJob,
  SlideSpec,
  TemplateProfile,
  updateTemplate,
} from "./api/client";
import { DesignLanguage, Length, Mode, Planner, PresentationStyle, Quality, Screen, Theme } from "./types";
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

const TERMINAL = new Set(["planned", "done", "review_failed", "error"]);
type PlanningArtifacts = { source?: any; story?: any; gate?: any; editing?: any; narrative?: any; refine?: any };

export default function App() {
  // ── presentation ──
  const [theme, setTheme] = useState<Theme>("light");
  const [screen, setScreen] = useState<Screen>("mode");

  // ── deck config ──
  const [mode, setMode] = useState<Mode>("freeform");
  const [planner, setPlanner] = useState<Planner>("fast");
  const [quality, setQuality] = useState<Quality>("balanced");
  const [length, setLength] = useState<Length>("auto");
  const [presentationStyle, setPresentationStyle] = useState<PresentationStyle>("auto");
  const [designLanguage, setDesignLanguage] = useState<DesignLanguage>("auto");
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
  const [renderedAudit, setRenderedAudit] = useState<RenderedSlideAudit | null>(null);
  const [regening, setRegening] = useState(false);
  const [slideSaving, setSlideSaving] = useState(false);
  const [slideSaveError, setSlideSaveError] = useState<string | null>(null);
  const [previewVersion, setPreviewVersion] = useState(0);
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
    let timer: number | undefined;
    const finishTerminalJob = (nextStatus: string) => {
      if (timer !== undefined) window.clearInterval(timer);
      void refreshLibrary();
      if (nextStatus === "planned") {
        setScreen("plan");
      } else if (nextStatus === "done" || nextStatus === "review_failed") {
        setScreen("review");
      }
    };
    const tick = async () => {
      try {
        const s = await getJobStatus(jobId);
        if (!active) return;
        setStatus(s);
        if (TERMINAL.has(s.job.status)) finishTerminalJob(s.job.status);
      } catch {
        /* keep polling */
      }
    };
    timer = window.setInterval(tick, 1500);
    tick();
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [jobId, screen]);

  useEffect(() => {
    if (!jobId || !status || (screen !== "plan" && screen !== "review")) return;
    loadPlanningContext(jobId);
  }, [
    jobId,
    screen,
    status?.job.status,
    status?.job.completed_at,
    status?.rendered_slide_audit?.available,
    status?.rendered_slide_audit?.issue_count,
  ]);

  async function loadPlanningContext(targetJobId: string) {
    setPlanningLoading(true);
    setPlanningError(null);
    try {
      const artifactNames: PlanningArtifactName[] = [
        "source-compression",
        "story-map",
        "spec-gate",
        "editing-contract",
        "narrative-pass",
        "refine-pass",
      ];
      const artifactKeyByName: Record<PlanningArtifactName, keyof PlanningArtifacts> = {
        "source-compression": "source",
        "story-map": "story",
        "spec-gate": "gate",
        "editing-contract": "editing",
        "narrative-pass": "narrative",
        "refine-pass": "refine",
      };
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
        nextArtifacts[artifactKeyByName[artifactNames[index]]] = result.value;
      });
      setPlanningArtifacts(nextArtifacts);
      if (screen === "review" && status?.rendered_slide_audit?.available) {
        try {
          setRenderedAudit(await getRenderedSlideAudit(targetJobId));
        } catch {
          setRenderedAudit(null);
        }
      } else {
        setRenderedAudit(null);
      }
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
    setRenderedAudit(null);
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
    const nextStyle = String(job.config_json?.presentation_style || "auto") as PresentationStyle;
    setPresentationStyle(nextStyle);
    const nextDesign = String(job.config_json?.design_language || "auto") as DesignLanguage;
    setDesignLanguage(nextDesign);
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
          : nextStatus.job.status === "done" || nextStatus.job.status === "review_failed"
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
      form.append("presentation_style", presentationStyle);
      form.append("design_language", designLanguage);
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
      setRenderedAudit(null);
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

  const handleRegen = async (guidance = "", edits?: SlideEditPayload) => {
    if (!jobId || openSlide == null) return;
    setRegening(true);
    setRegenError(null);
    try {
      await regenerateSlide(jobId, openSlide, guidance, edits);
      const s = await getJobStatus(jobId);
      setStatus(s);
      try {
        const o = await getJobOutline(jobId);
        setOutline(o.slides);
      } catch {
        /* outline refresh is best-effort */
      }
      setPreviewVersion((v) => v + 1);
      await refreshLibrary();
    } catch (err: any) {
      setRegenError(err?.message || "Failed to regenerate slide.");
    } finally {
      setRegening(false);
    }
  };

  const handleSaveSlide = async (payload: SlideEditPayload) => {
    if (!jobId || openSlide == null) return;
    setSlideSaving(true);
    setSlideSaveError(null);
    try {
      await updateSlide(jobId, openSlide, payload);
      const s = await getJobStatus(jobId);
      setStatus(s);
      try {
        const o = await getJobOutline(jobId);
        setOutline(o.slides);
      } catch {
        /* outline refresh is best-effort */
      }
      setPreviewVersion((v) => v + 1);
      await refreshLibrary();
    } catch (err: any) {
      setSlideSaveError(err?.message || "Failed to save slide edits.");
    } finally {
      setSlideSaving(false);
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
              presentationStyle={presentationStyle}
              designLanguage={designLanguage}
              visualQa={visualQa}
              onPlanner={setPlanner}
              onQuality={setQuality}
              onLength={setLength}
              onPresentationStyle={setPresentationStyle}
              onDesignLanguage={setDesignLanguage}
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
              artifacts={planningArtifacts}
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
          auditSlide={renderedAudit?.slides?.find((slide) => slide.slide_index === openSlide)}
          regening={regening}
          regenError={regenError}
          saving={slideSaving}
          saveError={slideSaveError}
          previewVersion={previewVersion}
          onClose={() => setOpenSlide(null)}
          onRegen={handleRegen}
          onSaveEdit={handleSaveSlide}
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
