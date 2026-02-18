import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listTemplates, uploadTemplate, updateTemplateStatus, listTemplateVersions } from '../api/client'
import { Upload, ChevronDown, ChevronRight, ToggleLeft, ToggleRight, FileSliders, Sparkles, AlertCircle, Check, ArrowLeft } from 'lucide-react'
import type { TemplateSummary } from '../api/types'

interface Props {
  onBack: () => void
}

export default function TemplateManager({ onBack }: Props) {
  const [showUpload, setShowUpload] = useState(false)
  const [expandedTemplate, setExpandedTemplate] = useState<string | null>(null)

  const queryClient = useQueryClient()
  const { data: templates, isLoading } = useQuery({
    queryKey: ['templates-all'],
    queryFn: listTemplates,
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-gray-500 hover:text-gray-800">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h2 className="text-xl font-semibold">Template Manager</h2>
        </div>
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm"
        >
          <Upload className="w-4 h-4" />
          Upload Template
        </button>
      </div>

      {showUpload && (
        <UploadForm
          onSuccess={() => {
            setShowUpload(false)
            queryClient.invalidateQueries({ queryKey: ['templates-all'] })
            queryClient.invalidateQueries({ queryKey: ['templates'] })
          }}
          onCancel={() => setShowUpload(false)}
        />
      )}

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading templates...</div>
      ) : (
        <div className="space-y-3">
          {templates?.map((t) => (
            <TemplateRow
              key={t.template_id}
              template={t}
              isExpanded={expandedTemplate === t.template_id}
              onToggle={() =>
                setExpandedTemplate(
                  expandedTemplate === t.template_id ? null : t.template_id
                )
              }
              onStatusChange={() => {
                queryClient.invalidateQueries({ queryKey: ['templates-all'] })
                queryClient.invalidateQueries({ queryKey: ['templates'] })
              }}
            />
          ))}
          {templates?.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              No templates yet. Upload one to get started.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TemplateRow({
  template,
  isExpanded,
  onToggle,
  onStatusChange,
}: {
  template: TemplateSummary
  isExpanded: boolean
  onToggle: () => void
  onStatusChange: () => void
}) {
  const toggleMutation = useMutation({
    mutationFn: () => updateTemplateStatus(template.template_id, !template.is_active),
    onSuccess: onStatusChange,
  })

  return (
    <div className="border border-gray-200 rounded-lg bg-white">
      <div className="flex items-center gap-3 p-4">
        <button onClick={onToggle} className="text-gray-400 hover:text-gray-600">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </button>

        {template.mode === 'mode2' ? (
          <Sparkles className="w-5 h-5 text-purple-500 shrink-0" />
        ) : (
          <FileSliders className="w-5 h-5 text-blue-500 shrink-0" />
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm">{template.display_name}</span>
            <span className="text-xs text-gray-400">v{template.version}</span>
            <span
              className={`text-xs px-2 py-0.5 rounded-full ${
                template.mode === 'mode2'
                  ? 'bg-purple-50 text-purple-600'
                  : 'bg-blue-50 text-blue-600'
              }`}
            >
              {template.mode === 'mode2' ? 'AI Generated' : 'Template Fill'}
            </span>
          </div>
          {template.description && (
            <p className="text-xs text-gray-400 mt-0.5 truncate">
              {template.description}
            </p>
          )}
        </div>

        <button
          onClick={(e) => {
            e.stopPropagation()
            toggleMutation.mutate()
          }}
          disabled={toggleMutation.isPending}
          className="text-gray-400 hover:text-gray-600 shrink-0"
          title={template.is_active ? 'Deactivate' : 'Activate'}
        >
          {template.is_active !== false ? (
            <ToggleRight className="w-6 h-6 text-green-500" />
          ) : (
            <ToggleLeft className="w-6 h-6 text-gray-300" />
          )}
        </button>
      </div>

      {isExpanded && <VersionHistory templateId={template.template_id} />}
    </div>
  )
}

function VersionHistory({ templateId }: { templateId: string }) {
  const { data: versions, isLoading } = useQuery({
    queryKey: ['template-versions', templateId],
    queryFn: () => listTemplateVersions(templateId),
  })

  if (isLoading) {
    return <div className="px-4 pb-4 text-sm text-gray-400">Loading versions...</div>
  }

  return (
    <div className="border-t border-gray-100 px-4 pb-4 pt-3">
      <h4 className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wider">
        Version History
      </h4>
      {versions && versions.length > 0 ? (
        <div className="space-y-1.5">
          {versions.map((v) => (
            <div
              key={v.version}
              className="flex items-center justify-between text-sm py-1.5 px-3 rounded bg-gray-50"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs">{v.version}</span>
                <span className="text-xs text-gray-400">{v.display_name}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  {new Date(v.created_at).toLocaleDateString()}
                </span>
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    v.is_active
                      ? 'bg-green-50 text-green-600'
                      : 'bg-gray-100 text-gray-400'
                  }`}
                >
                  {v.is_active ? 'active' : 'inactive'}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-400">No version history available.</p>
      )}
    </div>
  )
}

function UploadForm({
  onSuccess,
  onCancel,
}: {
  onSuccess: () => void
  onCancel: () => void
}) {
  const [templateId, setTemplateId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState('mode1')
  const [version, setVersion] = useState('1.0.0')
  const [schemaText, setSchemaText] = useState('')
  const [pptxFile, setPptxFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const mutation = useMutation({
    mutationFn: () => {
      if (!pptxFile) throw new Error('PPTX file is required')
      if (!schemaText.trim()) throw new Error('Schema JSON is required')
      return uploadTemplate(pptxFile, schemaText, templateId, displayName, description, mode, version)
    },
    onSuccess: (data) => {
      setWarnings(data.warnings)
      if (data.warnings.length === 0) {
        onSuccess()
      }
    },
    onError: (err) => {
      setError(err.message)
    },
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) {
      setPptxFile(file)
      // Auto-derive template_id from filename if empty
      if (!templateId) {
        const name = file.name.replace(/\.pptx$/i, '').replace(/\s+/g, '-').toLowerCase()
        setTemplateId(name)
      }
    }
  }

  function handleSchemaFileLoad(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onload = () => setSchemaText(reader.result as string)
      reader.readAsText(file)
    }
  }

  return (
    <div className="border border-blue-200 rounded-lg bg-blue-50/50 p-5 mb-6">
      <h3 className="text-sm font-semibold mb-4">Upload New Template</h3>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            PPTX File <span className="text-red-400">*</span>
          </label>
          <div
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-gray-300 rounded-md p-4 text-center cursor-pointer hover:border-blue-400 transition-colors bg-white"
          >
            {pptxFile ? (
              <div className="flex items-center justify-center gap-2 text-sm text-green-600">
                <Check className="w-4 h-4" />
                {pptxFile.name}
              </div>
            ) : (
              <div className="text-sm text-gray-400">
                <Upload className="w-5 h-5 mx-auto mb-1" />
                Click to select .pptx file
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pptx"
            onChange={handleFileChange}
            className="hidden"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Template ID <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value.replace(/[^a-z0-9-]/g, ''))}
            placeholder="e.g. weekly-report"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
          />
          <p className="text-xs text-gray-400 mt-0.5">Lowercase letters, numbers, and hyphens only</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Display Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Weekly Status Report"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Version</label>
          <input
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Mode</label>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
          >
            <option value="mode1">Template Fill (Mode 1)</option>
            <option value="mode2">AI Generated (Mode 2)</option>
            <option value="both">Both</option>
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
          />
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between mb-1">
          <label className="block text-xs font-medium text-gray-600">
            Schema JSON <span className="text-red-400">*</span>
          </label>
          <label className="text-xs text-blue-600 hover:text-blue-800 cursor-pointer">
            Load from file
            <input type="file" accept=".json" onChange={handleSchemaFileLoad} className="hidden" />
          </label>
        </div>
        <textarea
          value={schemaText}
          onChange={(e) => setSchemaText(e.target.value)}
          rows={8}
          placeholder='{"slides": {"1": {"fields": {...}}}}'
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono bg-white"
        />
      </div>

      {error && (
        <div className="flex items-start gap-2 mt-3 text-red-600 text-sm bg-red-50 p-3 rounded">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mt-3 bg-amber-50 text-amber-700 text-sm p-3 rounded">
          <p className="font-medium mb-1">Upload succeeded with warnings:</p>
          <ul className="list-disc list-inside text-xs space-y-0.5">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
          <button
            onClick={onSuccess}
            className="mt-2 text-xs text-amber-800 underline hover:text-amber-900"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="flex gap-3 mt-4">
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !pptxFile || !templateId || !displayName || !schemaText.trim()}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
        >
          <Upload className="w-4 h-4" />
          {mutation.isPending ? 'Uploading...' : 'Upload'}
        </button>
        <button
          onClick={onCancel}
          className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
