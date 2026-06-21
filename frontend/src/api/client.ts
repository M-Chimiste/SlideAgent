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

export type JobStatus = {
  job: JobRecord;
  warnings: JobWarning[];
  preview_images?: string[] | null;
  qa_summary?: QaSummary | null;
  qa_issues?: QaIssue[] | null;
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

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw await apiError(response, "Job lookup failed.");
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

export async function regenerateSlide(jobId: string, slideIndex: number) {
  const response = await fetch(`/api/jobs/${jobId}/regen/${slideIndex}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await apiError(response, "Slide regeneration failed.");
  }
  return response.json();
}
