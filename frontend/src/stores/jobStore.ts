import { create } from 'zustand'

type Step =
  | 'select'
  | 'manage'          // Template management
  | 'input'           // Mode 1: fill form / Mode 2: brief input
  | 'submitting'
  | 'polling'         // Polling job status
  | 'outline_review'  // Mode 2: reviewing outline
  | 'complete'
  | 'failed'

interface JobState {
  step: Step
  templateId: string | null
  templateMode: string | null
  jobId: string | null
  setStep: (step: Step) => void
  selectTemplate: (templateId: string, mode: string) => void
  startJob: (jobId: string) => void
  reset: () => void
}

export const useJobStore = create<JobState>((set) => ({
  step: 'select',
  templateId: null,
  templateMode: null,
  jobId: null,
  setStep: (step) => set({ step }),
  selectTemplate: (templateId, mode) => set({ templateId, templateMode: mode, step: 'input' }),
  startJob: (jobId) => set({ jobId, step: 'polling' }),
  reset: () => set({ step: 'select', templateId: null, templateMode: null, jobId: null }),
}))
