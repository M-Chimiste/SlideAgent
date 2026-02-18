import type { TemplateSummary, TemplateDetail, JobStatus, JobCreateResponse, OutlineApprovalRequest, TemplateVersion, TemplateUploadResponse, TemplateStatusResponse } from './types'

const BASE = ''

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${url}`, init)
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${resp.status}: ${body}`)
  }
  return resp.json()
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  return fetchJSON('/templates')
}

export async function getTemplate(templateId: string): Promise<TemplateDetail> {
  return fetchJSON(`/templates/${templateId}`)
}

export async function listTemplateVersions(templateId: string): Promise<TemplateVersion[]> {
  return fetchJSON(`/templates/${templateId}/versions`)
}

export async function uploadTemplate(
  pptxFile: File,
  schema: string,
  templateId: string,
  displayName: string,
  description: string,
  mode: string,
  version: string,
): Promise<TemplateUploadResponse> {
  const formData = new FormData()
  formData.append('pptx_file', pptxFile)
  formData.append('schema', schema)
  formData.append('template_id', templateId)
  formData.append('display_name', displayName)
  formData.append('description', description)
  formData.append('mode', mode)
  formData.append('version', version)

  const resp = await fetch(`${BASE}/templates`, {
    method: 'POST',
    body: formData,
  })
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${resp.status}: ${body}`)
  }
  return resp.json()
}

export async function updateTemplateStatus(
  templateId: string,
  isActive: boolean,
): Promise<TemplateStatusResponse> {
  const formData = new FormData()
  formData.append('is_active', String(isActive))

  const resp = await fetch(`${BASE}/templates/${templateId}`, {
    method: 'PATCH',
    body: formData,
  })
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${resp.status}: ${body}`)
  }
  return resp.json()
}

export async function createJob(
  templateId: string,
  mode: string,
  inputData: Record<string, unknown>,
): Promise<JobCreateResponse> {
  return fetchJSON('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      template_id: templateId,
      mode,
      input_data: inputData,
    }),
  })
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  return fetchJSON(`/jobs/${jobId}`)
}

export async function approveOutline(
  jobId: string,
  request: OutlineApprovalRequest,
): Promise<JobStatus> {
  return fetchJSON(`/jobs/${jobId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function getDownloadUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/download`
}
