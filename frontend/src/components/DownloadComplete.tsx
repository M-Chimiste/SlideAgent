import { useQuery } from '@tanstack/react-query'
import { getJobStatus, getDownloadUrl } from '../api/client'
import { useJobStore } from '../stores/jobStore'
import { CheckCircle, Download, AlertTriangle, RotateCcw } from 'lucide-react'

export default function DownloadComplete() {
  const jobId = useJobStore((s) => s.jobId)!
  const reset = useJobStore((s) => s.reset)

  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJobStatus(jobId),
  })

  if (!job) return null

  return (
    <div className="max-w-md mx-auto py-12 text-center">
      <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
      <h2 className="text-2xl font-semibold mb-2">Deck Generated!</h2>
      <p className="text-gray-500 mb-6">Your PowerPoint presentation is ready to download.</p>

      {job.warnings.length > 0 && (
        <div className="mb-6 p-4 bg-amber-50 rounded-lg text-left">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <span className="text-sm font-medium text-amber-800">Warnings</span>
          </div>
          <ul className="text-sm text-amber-700 space-y-1">
            {job.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-3 justify-center">
        <a
          href={getDownloadUrl(jobId)}
          className="flex items-center gap-2 bg-blue-600 text-white px-5 py-2.5 rounded-lg hover:bg-blue-700"
        >
          <Download className="w-4 h-4" />
          Download PPTX
        </a>
        <button
          onClick={reset}
          className="flex items-center gap-2 border border-gray-300 px-5 py-2.5 rounded-lg hover:bg-gray-50 text-gray-700"
        >
          <RotateCcw className="w-4 h-4" />
          New Deck
        </button>
      </div>
    </div>
  )
}
