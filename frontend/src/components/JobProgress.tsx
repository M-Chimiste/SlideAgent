import { useQuery } from '@tanstack/react-query'
import { getJobStatus } from '../api/client'
import { useJobStore } from '../stores/jobStore'
import { CheckCircle, Loader2, XCircle } from 'lucide-react'

const MODE1_STAGES = ['queued', 'parsing', 'validating', 'packaging', 'complete']
const MODE2_STAGES = ['queued', 'planning', 'awaiting_approval', 'generating', 'packaging', 'complete']

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued',
  parsing: 'Parsing input',
  validating: 'Validating fields',
  planning: 'Planning deck outline',
  awaiting_approval: 'Outline approved',
  generating: 'Generating content',
  packaging: 'Generating PPTX',
  complete: 'Complete',
}

export default function JobProgress() {
  const jobId = useJobStore((s) => s.jobId)!
  const templateMode = useJobStore((s) => s.templateMode)
  const setStep = useJobStore((s) => s.setStep)

  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJobStatus(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'complete' || status === 'failed') return false
      if (status === 'awaiting_approval') return false
      return 1000
    },
  })

  // Transition store step when job finishes
  if (job?.status === 'complete') {
    setTimeout(() => setStep('complete'), 0)
  }
  if (job?.status === 'failed') {
    setTimeout(() => setStep('failed'), 0)
  }
  // Mode 2: transition to outline review
  if (job?.status === 'awaiting_approval') {
    setTimeout(() => setStep('outline_review'), 0)
  }

  if (!job) {
    return <div className="text-center py-12 text-gray-500">Loading job status...</div>
  }

  const stages = templateMode === 'mode2' ? MODE2_STAGES : MODE1_STAGES
  const currentStageIdx = stages.indexOf(job.current_stage || 'queued')

  return (
    <div className="max-w-md mx-auto py-12">
      <h2 className="text-xl font-semibold mb-6 text-center">Generating Your Deck</h2>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-2.5 mb-8">
        <div
          className={`h-2.5 rounded-full transition-all duration-500 ${
            templateMode === 'mode2' ? 'bg-purple-600' : 'bg-blue-600'
          }`}
          style={{ width: `${job.progress}%` }}
        />
      </div>

      {/* Stage checklist */}
      <div className="space-y-3">
        {stages.map((stage, idx) => {
          const isComplete = idx < currentStageIdx || job.status === 'complete'
          const isCurrent = idx === currentStageIdx && job.status !== 'complete' && job.status !== 'failed'

          return (
            <div key={stage} className="flex items-center gap-3">
              {isComplete ? (
                <CheckCircle className="w-5 h-5 text-green-500" />
              ) : isCurrent ? (
                <Loader2 className={`w-5 h-5 animate-spin ${
                  templateMode === 'mode2' ? 'text-purple-500' : 'text-blue-500'
                }`} />
              ) : (
                <div className="w-5 h-5 rounded-full border-2 border-gray-300" />
              )}
              <span className={`text-sm ${
                isCurrent
                  ? `font-medium ${templateMode === 'mode2' ? 'text-purple-700' : 'text-blue-700'}`
                  : isComplete
                  ? 'text-gray-500'
                  : 'text-gray-400'
              }`}>
                {STAGE_LABELS[stage] || stage}
              </span>
            </div>
          )
        })}
      </div>

      {job.status === 'failed' && job.error && (
        <div className="mt-6 p-4 bg-red-50 rounded-lg flex items-start gap-3">
          <XCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-800">Job failed at {job.error.stage}</p>
            <p className="text-sm text-red-600 mt-1">{job.error.message}</p>
          </div>
        </div>
      )}
    </div>
  )
}
