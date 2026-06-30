export type SlideField = {
  id: string;
  type: string;
  location: string;
  required?: boolean;
  max_chars?: number | null;
  values?: string[] | null;
  format?: string | null;
  render?: string | null;
  color_map?: Record<string, string> | null;
  max_items?: number | null;
  max_chars_per_item?: number | null;
};

export type SlideSchema = {
  fields: SlideField[];
};

export type SlideSpec = {
  index: number;
  mode: string;
  label: string;
  layout_name?: string | null;
  schema?: SlideSchema | null;
  intent?: string | null;
  content_category?: string | null;
  visual_guidance?: string | null;
  classification_reason?: string | null;
};

export type BrandColors = {
  primary: string;
  secondary: string;
  accent: string;
  background_dark: string;
  background_light: string;
  text_dark: string;
  text_light: string;
};

export type BrandFonts = {
  heading: string;
  body: string;
};

export type BrandLogo = {
  path: string;
  placement: string;
  w?: number;
  h?: number;
} | null;

export type BrandDNA = {
  colors: BrandColors;
  fonts: BrandFonts;
  logo: BrandLogo;
  design_notes?: string | null;
  layout_profile?: Record<string, any>;
};

export type TemplateProfile = {
  id: string;
  name: string;
  type: string;
  brand: BrandDNA;
  slides: SlideSpec[];
  source_file?: string;
  created_at?: string;
  updated_at?: string;
};

export type JobWarning = {
  slide_index: number;
  field: string;
  message: string;
  severity?: string;
};

export type QaIssue = {
  severity: "CRITICAL" | "WARNING" | "INFO";
  message: string;
  slide_index?: number | null;
  category?: string | null;
};

export type JobRecord = {
  id: string;
  template_id: string;
  instructions?: string | null;
  config_json?: Record<string, any> | null;
  status: string;
  progress: number;
  qa_rounds?: number;
  warnings?: JobWarning[];
  result_file?: string | null;
  preview_dir?: string | null;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
};

export type QaSummary = {
  critical: number;
  warning: number;
  info: number;
  count: number;
};

export type PlanningSummary = {
  available: boolean;
  artifacts: string[];
  story_map_status?: string | null;
  story_map_fallback_reason?: string | null;
  source_coverage?: {
    section_count: number;
    included_section_count: number;
    omitted_section_count: number;
    estimated_tokens: number;
  };
  spec_gate?: {
    status?: string | null;
    issue_count: number;
    repaired_count: number;
    unresolved_count: number;
  };
  editing_contract?: {
    standard?: string | null;
    source?: string | null;
    status?: string | null;
    phase?: string | null;
    issue_count: number;
    requirement_count?: number;
    passed_requirement_count?: number;
    warning_requirement_count?: number;
    slide_count: number;
    unique_layout_count: number;
    unique_composition_family_count?: number;
    bullet_card_ratio: number;
    composition_card_ratio?: number;
    diagram_count: number;
    template_mapped_count: number;
    slot_risk_count?: number;
    structural_operation_count?: number;
    structural_warning_count?: number;
    formatting_fix_count?: number;
    formatting_warning_count?: number;
    requirements?: EditingContractRequirement[];
    warnings?: string[];
  };
};

export type EditingContractRequirement = {
  id: string;
  label: string;
  status: string;
  message: string;
};

export type QaHistoryEntry = {
  round: number;
  passed: boolean;
  summary: QaSummary;
  actionable_issue_count?: number;
  repair_applied?: boolean;
  stop_reason?: string | null;
};

export type JobStatus = {
  job: JobRecord;
  warnings: JobWarning[];
  preview_images?: string[] | null;
  qa_summary?: QaSummary | null;
  qa_issues?: QaIssue[] | null;
  qa_history?: QaHistoryEntry[] | null;
  planning_summary?: PlanningSummary | null;
  final_qa_passed?: boolean | null;
  final_review_passed?: boolean | null;
  unresolved_critical_count?: number;
  unresolved_actionable_issue_count?: number;
  unresolved_editing_contract_count?: number;
  rendered_slide_audit?: {
    available: boolean;
    artifact: string;
    path?: string;
    passed?: boolean;
    issue_count?: number;
    critical_count?: number;
    warning_count?: number;
    slide_count?: number;
    rhythm_slide_count?: number;
    unique_family_count?: number;
    card_like_ratio?: number;
    most_repeated_family?: {
      family: string;
      count: number;
    } | null;
    top_issues?: RenderedAuditIssueSample[];
    error?: string;
  } | null;
  visual_review?: {
    status: "pass" | "warning" | "pending";
    preview_count: number;
    expected_slide_count: number;
    preview_coverage: boolean;
    audit_available: boolean;
    audit_slide_count: number;
    audit_preview_match: boolean;
    audit_passed?: boolean | null;
    audit_issue_count: number;
    audit_critical_count: number;
    message?: string;
  } | null;
  template_clone_edit?: {
    available: boolean;
    artifact: string;
    status?: string | null;
    slide_count?: number;
    mapping_count?: number;
    blocked_mapping_count?: number;
    weak_mapping_count?: number;
    unfilled_placeholder_count?: number;
    closest_candidate_count?: number;
    closest_candidate_samples?: Array<{
      output_slide?: number | null;
      source_slide?: number | null;
      label?: string | null;
      match_score?: number | null;
      match_reason?: string | null;
    }>;
    edit_target_count?: number;
    rewritten_target_count?: number;
    deleted_target_count?: number;
    rewritten_table_cell_count?: number;
    rewritten_chart_count?: number;
    rewritten_chart_point_count?: number;
    bolded_text_run_count?: number;
    deleted_table_row_count?: number;
    deleted_media_placeholder_count?: number;
    planned_excess_slot_count?: number;
    actual_deleted_slot_count?: number;
    unsatisfied_slot_cleanup_count?: number;
    package_cleanup_deleted_part_count?: number;
    package_cleanup_deleted_media_part_count?: number;
    package_cleanup_removed_override_count?: number;
    warning_count?: number;
    error?: string;
  } | null;
  template_frame_map?: {
    available: boolean;
    artifact: string;
    status?: string | null;
    output_slide_count?: number;
    source_slide_count?: number;
    omitted_source_slide_count?: number;
    blocked_output_slide_count?: number;
    samples?: Array<{
      output_slide?: number | null;
      source_slide?: number | null;
      reuse_mode?: string | null;
      match_confidence?: string | null;
      match_score?: number | null;
    }>;
    error?: string;
  } | null;
  template_deviation_log?: {
    available: boolean;
    artifact: string;
    status?: string | null;
    deviation_count?: number;
    samples?: Array<{
      type?: string | null;
      severity?: string | null;
      output_slide?: number | null;
      source_slide?: number | null;
      reason?: string | null;
    }>;
    error?: string;
  } | null;
};

export type RenderedAuditIssueSample = {
  severity: string;
  category: string;
  message: string;
  slide_index?: number | null;
};

export type RenderedSlideLayoutDiagnostics = {
  text_box_count?: number;
  opaque_shape_count?: number;
  overflow_risk_count?: number;
  small_text_risk_count?: number;
  overlap_pair_count?: number;
  occlusion_pair_count?: number;
  overflow_risks?: Array<{
    shape_index?: number;
    text?: string;
    bounds?: { x?: number; y?: number; w?: number; h?: number };
    font_size?: number;
    estimated_lines?: number;
    capacity_lines?: number;
  }>;
  small_text_risks?: Array<{
    shape_index?: number;
    text?: string;
    bounds?: { x?: number; y?: number; w?: number; h?: number };
    font_size?: number;
    estimated_lines?: number;
    capacity_lines?: number;
  }>;
  overlap_pairs?: Array<{
    shape_indexes?: number[];
    overlap_ratio?: number;
    texts?: string[];
  }>;
  occlusion_pairs?: Array<{
    shape_indexes?: number[];
    overlap_ratio?: number;
    text?: string;
  }>;
};

export type RenderedSlideAuditSlide = {
  slide_index: number;
  text?: string[];
  paragraph_text?: string[];
  layout_diagnostics?: RenderedSlideLayoutDiagnostics;
  diagram_labels?: string[];
  composition_signature?: string | null;
  template_frame?: TemplateFrameReference | null;
  visual_degradation?: Record<string, any> | null;
  source_refs?: string[];
  issues?: QaIssue[];
};

export type RenderedSlideAudit = {
  passed: boolean;
  issue_count: number;
  critical_count: number;
  warning_count: number;
  issues?: QaIssue[];
  visual_rhythm?: Record<string, any>;
  slides: RenderedSlideAuditSlide[];
};

export type JobOutlineSlide = {
  slide_index: number;
  mode: string;
  label: string;
  action_title: string;
  subheading: string;
  narrative_role?: string | null;
  layout?: string | null;
  archetype?: string | null;
  composition_family?: string | null;
  composition_signature?: string | null;
  template_frame?: TemplateFrameReference | null;
  visual_intent?: Record<string, any> | null;
  visual_degradation?: Record<string, any> | null;
  exhibit_type?: string | null;
  sources: string[];
  source_refs: string[];
  speaker_notes?: string | null;
  qa_status?: string | null;
  qa_issues?: Record<string, any>[];
};

export type TemplateFrameReference = {
  index?: number;
  source_slide?: number;
  label?: string | null;
  layout_name?: string | null;
  mode?: string | null;
  method?: string | null;
  match_score?: number | null;
  match_confidence?: string | null;
  match_reason?: string | null;
  intent?: string | null;
  content_category?: string | null;
  visual_guidance?: string | null;
  schema_field_count?: number | null;
  item_slot_count?: number | null;
  reuse_mode?: string | null;
  chrome_shape_count?: number | null;
  chrome_applied?: boolean | null;
  clone_edit_applied?: boolean | null;
  edit_target_count?: number | null;
  rewritten_text_shape_count?: number | null;
  rewritten_table_cell_count?: number | null;
  closest_candidates?: TemplateFrameCandidate[];
};

export type TemplateFrameCandidate = {
  index?: number;
  source_slide?: number;
  label?: string | null;
  layout_name?: string | null;
  method?: string | null;
  match_score?: number | null;
  match_confidence?: string | null;
  match_reason?: string | null;
  content_category?: string | null;
  visual_guidance?: string | null;
  item_slot_count?: number | null;
};

export type JobOutlineResponse = {
  slides: JobOutlineSlide[];
};

export type OutlineEdit = {
  slide_index: number;
  action_title?: string;
  subheading?: string;
};

export type PlanningArtifactName =
  | "source-compression"
  | "story-map"
  | "spec-gate"
  | "editing-contract"
  | "narrative-pass"
  | "refine-pass";

export type TemplateAssets = {
  template_id: string;
  thumbnails: string[];
  logo_available: boolean;
  frame_map?: {
    available: boolean;
    artifact?: string;
    standard?: string | null;
    slide_count: number;
    schema_bearing_slide_count: number;
    slot_count: number;
    slides: Array<{
      slide_index?: number;
      label?: string | null;
      layout_name?: string | null;
      mode?: string | null;
      content_category?: string | null;
      visual_guidance?: string | null;
      slot_count?: number;
      text_slot_count?: number;
      media_slot_count?: number;
      schema_field_count?: number;
      text_inventory?: string;
    }>;
    error?: string;
  } | null;
};

async function apiError(response: Response, fallback: string): Promise<Error> {
  try {
    const payload = await response.json();
    const detail = payload?.detail;
    if (typeof detail === "string" && detail.trim()) return new Error(detail);
    if (Array.isArray(detail) && detail.length) return new Error(detail[0]?.msg || fallback);
  } catch {
    /* fall through to fallback */
  }
  return new Error(fallback);
}

export async function listTemplates(): Promise<TemplateProfile[]> {
  const response = await fetch("/api/templates");
  if (!response.ok) {
    throw await apiError(response, "Failed to load templates.");
  }
  const payload = await response.json();
  return payload.templates ?? [];
}

export async function analyzeTemplate(formData: FormData): Promise<TemplateProfile> {
  const response = await fetch("/api/templates/analyze", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw await apiError(response, "Template analysis failed.");
  }
  return response.json();
}

export async function getTemplate(templateId: string): Promise<TemplateProfile> {
  const response = await fetch(`/api/templates/${templateId}`);
  if (!response.ok) {
    throw await apiError(response, "Template lookup failed.");
  }
  return response.json();
}

export async function updateTemplate(
  templateId: string,
  payload: { name?: string; slides?: SlideSpec[] }
): Promise<TemplateProfile> {
  const response = await fetch(`/api/templates/${templateId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await apiError(response, "Template update failed.");
  }
  return response.json();
}

export async function createJob(formData: FormData): Promise<JobRecord> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw await apiError(response, "Job creation failed.");
  }
  return response.json();
}

export async function renderPlannedJob(jobId: string): Promise<JobRecord> {
  const response = await fetch(`/api/jobs/${jobId}/render`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await apiError(response, "Plan rendering failed.");
  }
  return response.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw await apiError(response, "Job lookup failed.");
  }
  return response.json();
}

export async function getJobOutline(jobId: string): Promise<JobOutlineResponse> {
  const response = await fetch(`/api/jobs/${jobId}/outline`);
  if (!response.ok) {
    throw await apiError(response, "Job outline lookup failed.");
  }
  return response.json();
}

export async function patchJobOutline(jobId: string, slides: OutlineEdit[]): Promise<JobOutlineResponse> {
  const response = await fetch(`/api/jobs/${jobId}/outline`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slides }),
  });
  if (!response.ok) {
    throw await apiError(response, "Job outline update failed.");
  }
  return response.json();
}

export async function getPlanningArtifact(jobId: string, artifact: PlanningArtifactName): Promise<any> {
  const response = await fetch(`/api/jobs/${jobId}/planning/${artifact}`);
  if (!response.ok) {
    throw await apiError(response, "Planning artifact lookup failed.");
  }
  return response.json();
}

export async function getRenderedSlideAudit(jobId: string): Promise<RenderedSlideAudit> {
  const response = await fetch(`/api/jobs/${jobId}/qa/rendered-slide-audit`);
  if (!response.ok) {
    throw await apiError(response, "Rendered slide audit lookup failed.");
  }
  return response.json();
}

export function previewImageUrl(jobId: string, image: string): string {
  return `/api/jobs/${jobId}/preview/${image}`;
}

export function downloadUrl(jobId: string, format: "pptx" | "pdf" = "pptx"): string {
  return format === "pdf"
    ? `/api/jobs/${jobId}/download?format=pdf`
    : `/api/jobs/${jobId}/download`;
}

export async function listJobs(): Promise<JobRecord[]> {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    throw await apiError(response, "Failed to load jobs.");
  }
  const payload = await response.json();
  return payload.jobs ?? [];
}

export async function getTemplateAssets(templateId: string): Promise<TemplateAssets> {
  const response = await fetch(`/api/templates/${templateId}/assets`);
  if (!response.ok) {
    throw await apiError(response, "Template assets lookup failed.");
  }
  return response.json();
}

export function templateThumbnailUrl(templateId: string, image: string): string {
  return `/api/templates/${templateId}/thumbnail/${image}`;
}

export function templateLogoUrl(templateId: string): string {
  return `/api/templates/${templateId}/logo`;
}

export async function regenerateSlide(jobId: string, slideIndex: number) {
  const response = await fetch(`/api/jobs/${jobId}/regen/${slideIndex}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await apiError(response, "Slide regeneration failed.");
  }
  return response.json();
}
