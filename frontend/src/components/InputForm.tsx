import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { getTemplate, createJob } from '../api/client'
import { useJobStore } from '../stores/jobStore'
import type { FieldSchema } from '../api/types'
import { ArrowLeft, Send, Sparkles } from 'lucide-react'

export default function InputForm() {
  const templateId = useJobStore((s) => s.templateId)!
  const templateMode = useJobStore((s) => s.templateMode)
  const startJob = useJobStore((s) => s.startJob)
  const setStep = useJobStore((s) => s.setStep)
  const reset = useJobStore((s) => s.reset)

  const [formData, setFormData] = useState<Record<string, string>>({})
  const [keyMessages, setKeyMessages] = useState<string[]>([''])
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})

  const { data: template, isLoading } = useQuery({
    queryKey: ['template', templateId],
    queryFn: () => getTemplate(templateId),
  })

  const mutation = useMutation({
    mutationFn: () => {
      if (templateMode === 'mode2') {
        const inputData: Record<string, unknown> = { ...formData }
        const filtered = keyMessages.filter((m) => m.trim())
        if (filtered.length > 0) inputData.key_messages = filtered
        return createJob(templateId, 'mode2', inputData)
      }
      return createJob(templateId, 'mode1', formData)
    },
    onSuccess: (data) => {
      startJob(data.job_id)
    },
    onError: () => {
      setStep('input')
    },
  })

  if (isLoading || !template) {
    return <div className="text-center py-12 text-gray-500">Loading template...</div>
  }

  function updateField(name: string, value: string) {
    setFormData((prev) => ({ ...prev, [name]: value }))
    setValidationErrors((prev) => {
      const next = { ...prev }
      delete next[name]
      return next
    })
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()

    if (templateMode === 'mode2') {
      const errors: Record<string, string> = {}
      if (!formData.title?.trim()) errors.title = 'Title is required'
      if (!formData.audience?.trim()) errors.audience = 'Audience is required'
      if (Object.keys(errors).length > 0) {
        setValidationErrors(errors)
        return
      }
    } else {
      const schema = template!.schema
      if (schema) {
        const errors: Record<string, string> = {}
        for (const [, slide] of Object.entries(schema)) {
          for (const [fieldName, field] of Object.entries(slide.fields)) {
            if (field.required !== false && !formData[fieldName]?.trim()) {
              errors[fieldName] = 'This field is required'
            }
          }
        }
        if (Object.keys(errors).length > 0) {
          setValidationErrors(errors)
          return
        }
      }
    }

    setStep('submitting')
    mutation.mutate()
  }

  // Mode 2: Brief input form
  if (templateMode === 'mode2') {
    return (
      <div>
        <button
          onClick={reset}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800 mb-4"
        >
          <ArrowLeft className="w-4 h-4" /> Back to templates
        </button>

        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="w-5 h-5 text-purple-500" />
          <h2 className="text-xl font-semibold">{template.display_name}</h2>
        </div>
        {template.description && (
          <p className="text-sm text-gray-500 mb-6">{template.description}</p>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Deck Title <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={formData.title || ''}
              onChange={(e) => updateField('title', e.target.value)}
              placeholder="e.g. Q1 Strategy Review"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
            />
            {validationErrors.title && (
              <p className="text-xs text-red-500 mt-1">{validationErrors.title}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Audience <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={formData.audience || ''}
              onChange={(e) => updateField('audience', e.target.value)}
              placeholder="e.g. Executive leadership team"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
            />
            {validationErrors.audience && (
              <p className="text-xs text-red-500 mt-1">{validationErrors.audience}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Key Messages
            </label>
            <div className="space-y-2">
              {keyMessages.map((msg, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    type="text"
                    value={msg}
                    onChange={(e) => {
                      const updated = [...keyMessages]
                      updated[i] = e.target.value
                      setKeyMessages(updated)
                    }}
                    placeholder={`Message ${i + 1}`}
                    className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
                  />
                  {keyMessages.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setKeyMessages(keyMessages.filter((_, j) => j !== i))}
                      className="text-gray-400 hover:text-red-500 text-sm px-2"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setKeyMessages([...keyMessages, ''])}
                className="text-sm text-purple-600 hover:text-purple-800"
              >
                + Add message
              </button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tone
            </label>
            <select
              value={formData.tone || ''}
              onChange={(e) => updateField('tone', e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
            >
              <option value="">Auto</option>
              <option value="professional">Professional</option>
              <option value="casual">Casual</option>
              <option value="technical">Technical</option>
              <option value="persuasive">Persuasive</option>
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Min Slides
              </label>
              <input
                type="number"
                min="1"
                max="20"
                value={formData.slide_count_min || ''}
                onChange={(e) => updateField('slide_count_min', e.target.value)}
                placeholder="3"
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Max Slides
              </label>
              <input
                type="number"
                min="1"
                max="30"
                value={formData.slide_count_max || ''}
                onChange={(e) => updateField('slide_count_max', e.target.value)}
                placeholder="8"
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Additional Brief
            </label>
            <textarea
              value={formData.brief || ''}
              onChange={(e) => updateField('brief', e.target.value)}
              rows={4}
              placeholder="Any additional context, requirements, or specific topics to cover..."
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-purple-400 focus:border-purple-400"
            />
          </div>

          {mutation.error && (
            <div className="text-red-500 text-sm bg-red-50 p-3 rounded">
              {mutation.error.message}
            </div>
          )}

          <button
            type="submit"
            disabled={mutation.isPending}
            className="flex items-center gap-2 bg-purple-600 text-white px-5 py-2.5 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Sparkles className="w-4 h-4" />
            {mutation.isPending ? 'Submitting...' : 'Plan Deck'}
          </button>
        </form>
      </div>
    )
  }

  // Mode 1: Schema-driven form
  const schema = template.schema
  if (!schema) {
    return <div className="text-red-500">No schema available for this template.</div>
  }

  return (
    <div>
      <button
        onClick={reset}
        className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back to templates
      </button>

      <h2 className="text-xl font-semibold mb-1">{template.display_name}</h2>
      {template.description && (
        <p className="text-sm text-gray-500 mb-6">{template.description}</p>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {Object.entries(schema).map(([slideKey, slide]) => (
          <fieldset key={slideKey} className="border border-gray-200 rounded-lg p-4">
            <legend className="text-sm font-medium text-gray-600 px-2">
              Slide {slide.slide_index}
              {slide.description && ` — ${slide.description}`}
            </legend>
            <div className="space-y-4 mt-2">
              {Object.entries(slide.fields).map(([fieldName, field]) => (
                <FieldInput
                  key={fieldName}
                  name={fieldName}
                  field={field}
                  value={formData[fieldName] || ''}
                  error={validationErrors[fieldName]}
                  onChange={(v) => updateField(fieldName, v)}
                />
              ))}
            </div>
          </fieldset>
        ))}

        {mutation.error && (
          <div className="text-red-500 text-sm bg-red-50 p-3 rounded">
            {mutation.error.message}
          </div>
        )}

        <button
          type="submit"
          disabled={mutation.isPending}
          className="flex items-center gap-2 bg-blue-600 text-white px-5 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Send className="w-4 h-4" />
          {mutation.isPending ? 'Submitting...' : 'Generate Deck'}
        </button>
      </form>
    </div>
  )
}

function FieldInput({
  name,
  field,
  value,
  error,
  onChange,
}: {
  name: string
  field: FieldSchema
  value: string
  error?: string
  onChange: (value: string) => void
}) {
  const label = name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  const isRequired = field.required !== false

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {isRequired && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {field.description && (
        <p className="text-xs text-gray-400 mb-1">{field.description}</p>
      )}

      {field.type === 'enum' && field.allowed_values ? (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
        >
          <option value="">Select...</option>
          {field.allowed_values.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      ) : field.type === 'date' ? (
        <input
          type="text"
          placeholder={field.date_format || 'e.g. 17 Feb 2026'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
        />
      ) : field.type === 'number' ? (
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
        />
      ) : (
        <div>
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
          />
          {field.max_chars && (
            <span className={`text-xs mt-0.5 block ${value.length > field.max_chars ? 'text-red-500' : 'text-gray-400'}`}>
              {value.length}/{field.max_chars}
            </span>
          )}
        </div>
      )}

      {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
    </div>
  )
}
