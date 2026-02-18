export interface TemplateSummary {
  template_id: string
  version: string
  display_name: string
  description: string | null
  mode: string
  is_active?: boolean
}

export interface TemplateVersion {
  template_id: string
  version: string
  display_name: string
  mode: string
  is_active: boolean
  created_at: string
}

export interface TemplateUploadResponse {
  template_id: string
  version: string
  display_name: string
  description: string
  mode: string
  warnings: string[]
}

export interface TemplateStatusResponse {
  template_id: string
  version: string
  is_active: boolean
}

export interface FieldSchema {
  shape_id: number
  type: 'text' | 'enum' | 'date' | 'number'
  required?: boolean
  max_chars?: number | null
  allowed_values?: string[]
  date_format?: string | null
  description?: string | null
}

export interface SlideSchema {
  slide_index: number
  description: string | null
  fields: Record<string, FieldSchema>
}

export interface LayoutDefinition {
  layout_name: string
  slide_layout_index: number
  suitable_for: string[]
  fields: Record<string, FieldSchema>
  notes: string | null
}

export interface TemplateDetail extends TemplateSummary {
  schema: Record<string, SlideSchema> | null
  layouts: Record<string, LayoutDefinition> | null
}

export interface JobError {
  stage: string
  message: string
  detail: string | null
  retryable: boolean
}

export interface SlideOutlineEntry {
  slide_number: number
  layout_name: string
  title: string
  content_summary: string
  content_type: string
}

export interface DeckOutline {
  deck_title: string
  audience: string
  narrative_arc: string
  slides: SlideOutlineEntry[]
  total_slides: number
}

export interface JobStatus {
  job_id: string
  status: 'queued' | 'parsing' | 'planning' | 'awaiting_approval' | 'generating' | 'packaging' | 'complete' | 'failed'
  progress: number
  current_stage: string | null
  outline: DeckOutline | null
  warnings: string[]
  error: JobError | null
  output_url: string | null
  created_at: string
  updated_at: string
}

export interface JobCreateResponse {
  job_id: string
  status: string
}

export interface OutlineApprovalRequest {
  approved: boolean
  revised_outline?: DeckOutline | null
  revision_instructions?: string | null
}
