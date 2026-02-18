import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { getJobStatus, approveOutline } from '../api/client'
import { useJobStore } from '../stores/jobStore'
import type { DeckOutline, SlideOutlineEntry } from '../api/types'
import {
  CheckCircle,
  Edit3,
  Loader2,
  MessageSquare,
  Plus,
  Trash2,
  X,
} from 'lucide-react'

export default function OutlineEditor() {
  const jobId = useJobStore((s) => s.jobId)!
  const setStep = useJobStore((s) => s.setStep)

  const [editedOutline, setEditedOutline] = useState<DeckOutline | null>(null)
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [revisionInstructions, setRevisionInstructions] = useState('')

  const { data: job, isLoading } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJobStatus(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'awaiting_approval') return false
      if (status === 'complete' || status === 'failed') return false
      return 1000
    },
  })

  // Transition to polling when job leaves awaiting_approval
  if (job?.status === 'generating' || job?.status === 'packaging') {
    setTimeout(() => setStep('polling'), 0)
  }
  if (job?.status === 'complete') {
    setTimeout(() => setStep('complete'), 0)
  }
  if (job?.status === 'failed') {
    setTimeout(() => setStep('failed'), 0)
  }

  const approveMutation = useMutation({
    mutationFn: () =>
      approveOutline(jobId, {
        approved: true,
        revised_outline: editedOutline || undefined,
      }),
    onSuccess: () => {
      setStep('polling')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: () =>
      approveOutline(jobId, {
        approved: false,
        revision_instructions: revisionInstructions,
      }),
    onSuccess: () => {
      setShowRejectForm(false)
      setRevisionInstructions('')
      setEditedOutline(null)
      // Job goes back to planning, then back to awaiting_approval
      // Stay on this screen — polling will handle it
    },
  })

  if (isLoading || !job) {
    return <div className="text-center py-12 text-gray-500">Loading outline...</div>
  }

  // If still planning, show progress
  if (job.status === 'planning' || job.status === 'queued' || job.status === 'parsing') {
    return (
      <div className="max-w-md mx-auto py-12 text-center">
        <Loader2 className="w-10 h-10 text-purple-500 animate-spin mx-auto mb-4" />
        <h2 className="text-xl font-semibold mb-2">Planning Your Deck</h2>
        <p className="text-gray-500">The AI is creating a deck outline for your review...</p>
      </div>
    )
  }

  if (!job.outline) {
    return <div className="text-red-500">No outline available.</div>
  }

  const outline = editedOutline || job.outline

  function updateSlideTitle(index: number, title: string) {
    const updated = { ...outline, slides: [...outline.slides] }
    updated.slides[index] = { ...updated.slides[index], title }
    setEditedOutline(updated)
  }

  function updateSlideSummary(index: number, content_summary: string) {
    const updated = { ...outline, slides: [...outline.slides] }
    updated.slides[index] = { ...updated.slides[index], content_summary }
    setEditedOutline(updated)
  }

  function removeSlide(index: number) {
    const updated = { ...outline, slides: outline.slides.filter((_, i) => i !== index) }
    // Renumber slides
    updated.slides = updated.slides.map((s, i) => ({ ...s, slide_number: i + 1 }))
    updated.total_slides = updated.slides.length
    setEditedOutline(updated)
  }

  function addSlide() {
    const newSlide: SlideOutlineEntry = {
      slide_number: outline.slides.length + 1,
      layout_name: 'content_bullets',
      title: 'New Slide',
      content_summary: 'Content to be generated',
      content_type: 'bullets',
    }
    const updated = {
      ...outline,
      slides: [...outline.slides, newSlide],
      total_slides: outline.slides.length + 1,
    }
    setEditedOutline(updated)
  }

  function moveSlide(from: number, to: number) {
    if (to < 0 || to >= outline.slides.length) return
    const updated = { ...outline, slides: [...outline.slides] }
    const [removed] = updated.slides.splice(from, 1)
    updated.slides.splice(to, 0, removed)
    updated.slides = updated.slides.map((s, i) => ({ ...s, slide_number: i + 1 }))
    setEditedOutline(updated)
  }

  const hasEdits = editedOutline !== null

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-1">Review Deck Outline</h2>
        <p className="text-sm text-gray-500">
          Review and edit the outline below, then approve to generate content.
        </p>
      </div>

      {/* Deck metadata */}
      <div className="bg-purple-50 rounded-lg p-4 mb-6">
        <h3 className="font-medium text-purple-900">{outline.deck_title}</h3>
        <p className="text-sm text-purple-700 mt-1">Audience: {outline.audience}</p>
        <p className="text-sm text-purple-600 mt-1">{outline.narrative_arc}</p>
      </div>

      {/* Slide list */}
      <div className="space-y-3 mb-6">
        {outline.slides.map((slide, index) => (
          <div
            key={index}
            className="border border-gray-200 rounded-lg p-4 bg-white hover:border-purple-300 transition-colors"
          >
            <div className="flex items-start gap-3">
              <div className="flex flex-col items-center gap-1 pt-1">
                <button
                  onClick={() => moveSlide(index, index - 1)}
                  disabled={index === 0}
                  className="text-gray-300 hover:text-gray-600 disabled:opacity-30 text-xs"
                  title="Move up"
                >
                  ▲
                </button>
                <span className="text-xs text-gray-400 font-mono w-5 text-center">
                  {slide.slide_number}
                </span>
                <button
                  onClick={() => moveSlide(index, index + 1)}
                  disabled={index === outline.slides.length - 1}
                  className="text-gray-300 hover:text-gray-600 disabled:opacity-30 text-xs"
                  title="Move down"
                >
                  ▼
                </button>
              </div>

              <div className="flex-1 min-w-0">
                <input
                  type="text"
                  value={slide.title}
                  onChange={(e) => updateSlideTitle(index, e.target.value)}
                  className="font-medium text-sm w-full border-0 border-b border-transparent hover:border-gray-200 focus:border-purple-400 focus:ring-0 px-0 py-0.5 bg-transparent"
                />
                <input
                  type="text"
                  value={slide.content_summary}
                  onChange={(e) => updateSlideSummary(index, e.target.value)}
                  className="text-sm text-gray-500 w-full border-0 border-b border-transparent hover:border-gray-200 focus:border-purple-400 focus:ring-0 px-0 py-0.5 bg-transparent mt-1"
                />
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded">
                    {slide.layout_name}
                  </span>
                  <span className="text-xs text-gray-400">{slide.content_type}</span>
                </div>
              </div>

              <button
                onClick={() => removeSlide(index)}
                className="text-gray-300 hover:text-red-500 p-1"
                title="Remove slide"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={addSlide}
        className="flex items-center gap-2 text-sm text-purple-600 hover:text-purple-800 mb-8"
      >
        <Plus className="w-4 h-4" /> Add slide
      </button>

      {/* Rejection form */}
      {showRejectForm && (
        <div className="mb-6 p-4 bg-amber-50 rounded-lg border border-amber-200">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-amber-800">Revision Instructions</h4>
            <button onClick={() => setShowRejectForm(false)} className="text-amber-400 hover:text-amber-600">
              <X className="w-4 h-4" />
            </button>
          </div>
          <textarea
            value={revisionInstructions}
            onChange={(e) => setRevisionInstructions(e.target.value)}
            rows={3}
            placeholder="Describe what you'd like changed (e.g., 'Add more technical depth', 'Remove the closing slide')..."
            className="w-full border border-amber-200 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-amber-400 focus:border-amber-400"
          />
          <button
            onClick={() => rejectMutation.mutate()}
            disabled={!revisionInstructions.trim() || rejectMutation.isPending}
            className="mt-2 flex items-center gap-2 bg-amber-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-amber-700 disabled:opacity-50"
          >
            <MessageSquare className="w-4 h-4" />
            {rejectMutation.isPending ? 'Replanning...' : 'Request Changes'}
          </button>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          onClick={() => approveMutation.mutate()}
          disabled={approveMutation.isPending}
          className="flex items-center gap-2 bg-purple-600 text-white px-5 py-2.5 rounded-lg hover:bg-purple-700 disabled:opacity-50"
        >
          <CheckCircle className="w-4 h-4" />
          {approveMutation.isPending ? 'Approving...' : hasEdits ? 'Approve Edited Outline' : 'Approve & Generate'}
        </button>

        {!showRejectForm && (
          <button
            onClick={() => setShowRejectForm(true)}
            className="flex items-center gap-2 border border-gray-300 px-5 py-2.5 rounded-lg hover:bg-gray-50 text-gray-700"
          >
            <Edit3 className="w-4 h-4" />
            Request Changes
          </button>
        )}
      </div>

      {(approveMutation.error || rejectMutation.error) && (
        <div className="mt-4 text-red-500 text-sm bg-red-50 p-3 rounded">
          {(approveMutation.error || rejectMutation.error)?.message}
        </div>
      )}
    </div>
  )
}
