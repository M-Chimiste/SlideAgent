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

export type TemplateProfile = {
  id: string;
  name: string;
  type: string;
  slides: SlideSpec[];
};

export type JobRecord = {
  id: string;
  template_id: string;
  status: string;
  progress: number;
  result_file?: string | null;
  preview_dir?: string | null;
  created_at: string;
};

export async function listTemplates(): Promise<TemplateProfile[]> {
  const response = await fetch("/api/templates");
  if (!response.ok) {
    throw new Error("Failed to load templates.");
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
    throw new Error("Template analysis failed.");
  }
  return response.json();
}

export async function getTemplate(templateId: string): Promise<TemplateProfile> {
  const response = await fetch(`/api/templates/${templateId}`);
  if (!response.ok) {
    throw new Error("Template lookup failed.");
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
    throw new Error("Template update failed.");
  }
  return response.json();
}

export async function createJob(formData: FormData): Promise<JobRecord> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw new Error("Job creation failed.");
  }
  return response.json();
}

export async function getJobStatus(jobId: string) {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error("Job lookup failed.");
  }
  return response.json();
}

export async function listJobs(): Promise<JobRecord[]> {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    throw new Error("Failed to load jobs.");
  }
  const payload = await response.json();
  return payload.jobs ?? [];
}

export async function regenerateSlide(jobId: string, slideIndex: number) {
  const response = await fetch(`/api/jobs/${jobId}/regen/${slideIndex}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Slide regeneration failed.");
  }
  return response.json();
}
