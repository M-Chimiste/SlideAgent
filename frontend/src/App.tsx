import { useJobStore } from './stores/jobStore'
import TemplateSelector from './components/TemplateSelector'
import TemplateManager from './components/TemplateManager'
import InputForm from './components/InputForm'
import JobProgress from './components/JobProgress'
import OutlineEditor from './components/OutlineEditor'
import DownloadComplete from './components/DownloadComplete'
import { RotateCcw, Settings } from 'lucide-react'

export default function App() {
  const step = useJobStore((s) => s.step)
  const setStep = useJobStore((s) => s.setStep)
  const reset = useJobStore((s) => s.reset)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <h1 className="text-lg font-semibold text-gray-900">SlideAgent</h1>
          <div className="flex items-center gap-3">
            {step === 'select' && (
              <button
                onClick={() => setStep('manage')}
                className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
              >
                <Settings className="w-3.5 h-3.5" />
                Manage Templates
              </button>
            )}
            {step !== 'select' && step !== 'manage' && (
              <button
                onClick={reset}
                className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Start Over
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {step === 'select' && <TemplateSelector />}
        {step === 'manage' && <TemplateManager onBack={reset} />}
        {(step === 'input' || step === 'submitting') && <InputForm />}
        {step === 'polling' && <JobProgress />}
        {step === 'outline_review' && <OutlineEditor />}
        {step === 'complete' && <DownloadComplete />}
        {step === 'failed' && <JobProgress />}
      </main>
    </div>
  )
}
