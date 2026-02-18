import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listTemplates } from '../api/client'
import { useJobStore } from '../stores/jobStore'
import { FileSliders, Sparkles, Search } from 'lucide-react'

export default function TemplateSelector() {
  const selectTemplate = useJobStore((s) => s.selectTemplate)
  const [search, setSearch] = useState('')
  const [modeFilter, setModeFilter] = useState<string>('all')

  const { data: templates, isLoading, error } = useQuery({
    queryKey: ['templates'],
    queryFn: listTemplates,
  })

  if (isLoading) {
    return <div className="text-center py-12 text-gray-500">Loading templates...</div>
  }

  if (error) {
    return (
      <div className="text-center py-12 text-red-500">
        Failed to load templates: {error.message}
      </div>
    )
  }

  const filtered = templates?.filter((t) => {
    const matchesSearch =
      !search ||
      t.display_name.toLowerCase().includes(search.toLowerCase()) ||
      t.description?.toLowerCase().includes(search.toLowerCase()) ||
      t.template_id.toLowerCase().includes(search.toLowerCase())
    const matchesMode = modeFilter === 'all' || t.mode === modeFilter || t.mode === 'both'
    return matchesSearch && matchesMode
  })

  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Select a Template</h2>

      <div className="flex gap-3 mb-5">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates..."
            className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
          />
        </div>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          {(['all', 'mode1', 'mode2'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setModeFilter(m)}
              className={`px-3 py-2 ${
                modeFilter === m
                  ? 'bg-gray-100 text-gray-900 font-medium'
                  : 'text-gray-500 hover:bg-gray-50'
              }`}
            >
              {m === 'all' ? 'All' : m === 'mode1' ? 'Fill' : 'AI'}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered?.map((t) => (
          <button
            key={t.template_id}
            onClick={() => selectTemplate(t.template_id, t.mode)}
            className="border border-gray-200 rounded-lg p-5 text-left hover:border-blue-400 hover:shadow-md transition-all cursor-pointer bg-white"
          >
            <div className="flex items-center gap-3 mb-2">
              {t.mode === 'mode2' ? (
                <Sparkles className="w-5 h-5 text-purple-500" />
              ) : (
                <FileSliders className="w-5 h-5 text-blue-500" />
              )}
              <span className="font-medium">{t.display_name}</span>
            </div>
            {t.description && (
              <p className="text-sm text-gray-500">{t.description}</p>
            )}
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-gray-400">v{t.version}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                t.mode === 'mode2'
                  ? 'bg-purple-50 text-purple-600'
                  : 'bg-blue-50 text-blue-600'
              }`}>
                {t.mode === 'mode2' ? 'AI Generated' : 'Template Fill'}
              </span>
            </div>
          </button>
        ))}
      </div>

      {filtered?.length === 0 && (
        <div className="text-center py-8 text-gray-400">
          No templates match your search.
        </div>
      )}
    </div>
  )
}
