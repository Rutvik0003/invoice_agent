import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, FileText, Info, Layers, Loader2, Play, Search, Upload, X } from 'lucide-react'
import { useMemo, useRef, useState, type DragEvent } from 'react'

import { PageHeader } from '@/components/AppShell'
import { DecisionPill } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, type Sample } from '@/lib/api'
import { api2 } from '@/lib/api2'
import { humanize, timeAgo } from '@/lib/format'
import { Link, navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const ACCEPTED = ['application/pdf', 'image/png', 'image/jpeg']
const MAX_MB = 10

type Choice = { kind: 'files'; files: File[] } | { kind: 'sample'; sample: Sample } | null
const MAX_FILES = 50

function validate(file: File): string | null {
  const name = file.name.toLowerCase()
  const okType = ACCEPTED.includes(file.type) || /\.(pdf|png|jpe?g)$/.test(name)
  if (!okType) return `"${file.name}" is not a PDF, PNG or JPG.`
  if (file.size === 0) return `"${file.name}" is empty.`
  if (file.size > MAX_MB * 1024 * 1024) return `"${file.name}" is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is ${MAX_MB} MB.`
  return null
}

export default function NewRun() {
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  const samples = useQuery({ queryKey: ['samples'], queryFn: api.samples })
  const [choice, setChoice] = useState<Choice>(null)
  const [model, setModel] = useState<string | null>(null)
  const [modelNames, setModelNames] = useState<Record<string, string>>({})
  const [useCache, setUseCache] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const selectedModel = model ?? config.data?.default_model ?? 'gemini'
  const modelInfo = config.data?.models.find((m) => m.id === selectedModel)
  const modelName = modelNames[selectedModel] ?? modelInfo?.model_name
  const files = choice?.kind === 'files' ? choice.files : []
  const isBatch = files.length > 1

  const start = useMutation({
    mutationFn: async (): Promise<string> => {
      if (isBatch) {
        const { batch_id } = await api.startBatch({ files, model: selectedModel, modelName, useCache })
        return `/batches/${batch_id}`
      }
      const { run_id } = await api.startRun({
        file: files[0],
        sampleId: choice?.kind === 'sample' ? choice.sample.id : undefined,
        model: selectedModel,
        modelName,
        useCache,
      })
      return `/runs/${run_id}`
    },
    onSuccess: (to) => navigate(to),
  })

  const canStart = choice !== null && !!modelInfo?.configured && !start.isPending
  const addFiles = (picked: File[]) => {
    const problems = picked.map(validate).filter(Boolean) as string[]
    const good = picked.filter((f) => !validate(f))
    const merged = [...files, ...good.filter((g) => !files.some((f) => f.name === g.name && f.size === g.size))].slice(0, MAX_FILES)
    if (files.length + good.length > MAX_FILES) problems.push(`At most ${MAX_FILES} files at once.`)
    setFileError(problems.length ? problems.join(' ') : null)
    setChoice(merged.length ? { kind: 'files', files: merged } : choice?.kind === 'sample' ? choice : null)
  }

  return (
    <div>
      <PageHeader title="New Run" subtitle="Upload a vendor invoice or pick a sample. Every step of the decision is shown live." />
      <div className="grid gap-6 px-8 py-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6">
          <UploadCard
            files={files}
            error={fileError}
            onFiles={addFiles}
            onRemove={(index) => {
              const rest = files.filter((_, i) => i !== index)
              setChoice(rest.length ? { kind: 'files', files: rest } : null)
            }}
          />
          <SamplePicker
            samples={samples.data ?? []}
            loading={samples.isPending}
            selectedId={choice?.kind === 'sample' ? choice.sample.id : null}
            onSelect={(sample) => {
              setFileError(null)
              setChoice({ kind: 'sample', sample })
            }}
          />
        </div>

        <div className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <h2 className="text-sm font-semibold">Model</h2>
            <p className="mt-0.5 text-xs text-zinc-500">The AI only reads the invoice. Rules make every decision.</p>
            <div className="mt-3 space-y-2">
              {(config.data?.models ?? []).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  disabled={!m.configured}
                  onClick={() => setModel(m.id)}
                  className={cn(
                    'w-full rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                    selectedModel === m.id ? 'border-zinc-900 ring-1 ring-zinc-900' : 'border-zinc-200 hover:border-zinc-400',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{m.label}</span>
                    {m.configured ? (
                      <span className="flex items-center gap-1 text-[11px] text-emerald-700"><CheckCircle2 className="size-3" /> configured</span>
                    ) : (
                      <span className="text-[11px] text-zinc-500">API key missing</span>
                    )}
                  </div>
                  <div className="mt-0.5 font-mono text-[11px] text-zinc-500">{modelNames[m.id] ?? (m.model_name || 'model not set')}</div>
                  <div className="mt-1.5 text-xs leading-snug text-zinc-600">{m.description}</div>
                </button>
              ))}
              {modelInfo && modelInfo.choices.length > 1 && (
                <label className="block text-xs text-zinc-600">
                  {modelInfo.label} model
                  <select value={modelName} onChange={(e) => setModelNames({ ...modelNames, [selectedModel]: e.target.value })}
                          className="mt-1 h-9 w-full rounded-md border border-zinc-200 bg-white px-2 font-mono text-xs text-zinc-900">
                    {modelInfo.choices.map((c) => <option key={c} value={c}>{c}{c === modelInfo.model_name ? ' (default)' : ''}</option>)}
                  </select>
                </label>
              )}
              {config.isPending && <div className="h-36 animate-pulse rounded-lg bg-zinc-100" />}
            </div>
            <div className="mt-4 flex items-center justify-between gap-3 border-t border-zinc-100 pt-4">
              <label htmlFor="cache" className="flex items-center gap-1.5 text-sm">
                Use cached extraction
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="size-3.5 text-zinc-400" />
                  </TooltipTrigger>
                  <TooltipContent className="max-w-64">
                    Reuses an earlier reading of this exact file by this model, if one exists. Saves free-tier quota. The run is
                    clearly badged "cached extraction". Off by default.
                  </TooltipContent>
                </Tooltip>
              </label>
              <Switch id="cache" checked={useCache} onCheckedChange={setUseCache} />
            </div>
          </section>

          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <div className="text-xs text-zinc-500">{isBatch ? 'Batch' : 'Invoice'}</div>
            <div className="mt-0.5 truncate text-sm font-medium">
              {files.length === 1 && files[0].name}
              {isBatch && `${files.length} invoices, processed one by one`}
              {choice?.kind === 'sample' && `${choice.sample.id} · ${humanize(choice.sample.scenario)}`}
              {!choice && <span className="text-zinc-400">Nothing selected yet</span>}
            </div>
            {isBatch && config.data && (
              <p className="mt-1 text-xs text-zinc-500">
                At least {config.data.ai_request_gap_s} s between AI requests (Settings), so roughly {Math.ceil(files.length * Math.max(config.data.ai_request_gap_s, 15) / 60)} min in total.
              </p>
            )}
            <Button className="mt-4 w-full" size="lg" disabled={!canStart} onClick={() => start.mutate()}>
              {start.isPending ? <Loader2 className="animate-spin" /> : isBatch ? <Layers /> : <Play />}
              {isBatch ? `Queue ${files.length} invoices` : 'Start run'}
            </Button>
            {start.isError && <p className="mt-2 text-sm text-red-700">{start.error.message}</p>}
            {modelInfo && !modelInfo.configured && (
              <p className="mt-2 text-xs text-zinc-500">Set the {modelInfo.label} API key to use this model.</p>
            )}
          </section>
          <RecentBatches />
        </div>
      </div>
    </div>
  )
}

function RecentBatches() {
  const batches = useQuery({ queryKey: ['batches'], queryFn: api2.batches, refetchInterval: 5_000 })
  if (!batches.data?.length) return null
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <h2 className="text-sm font-semibold">Recent batches</h2>
      <ul className="mt-2 divide-y divide-zinc-100">
        {batches.data.slice(0, 5).map((b) => (
          <li key={b.id}>
            <Link to={`/batches/${b.id}`} className="flex items-center gap-2 py-2 text-sm hover:text-zinc-600">
              <Layers className="size-4 shrink-0 text-zinc-400" />
              <span className="min-w-0 flex-1 truncate">{b.total} invoices · {timeAgo(b.created_at)}</span>
              <span className={cn('shrink-0 text-xs', b.finished ? 'text-zinc-500' : 'font-medium text-sky-700')}>
                {b.finished ? 'done' : `${b.done}/${b.total}`}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function UploadCard({ files, error, onFiles, onRemove }: {
  files: File[]; error: string | null; onFiles: (f: File[]) => void; onRemove: (index: number) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const drop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const dropped = Array.from(e.dataTransfer.files ?? [])
    if (dropped.length) onFiles(dropped)
  }
  const file = files.length === 1 ? files[0] : null
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <h2 className="text-sm font-semibold">Upload invoices</h2>
      <p className="text-xs text-zinc-500">One file runs live. Several files are queued and processed one by one, with a combined result.</p>
      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          'mt-3 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors',
          over ? 'border-zinc-900 bg-zinc-50' : 'border-zinc-200 hover:border-zinc-400',
        )}
      >
        {file ? (
          <div className="flex items-center gap-3">
            <FileText className="size-8 text-zinc-500" />
            <div className="text-left">
              <div className="text-sm font-medium">{file.name}</div>
              <div className="text-xs text-zinc-500">{(file.size / 1024).toFixed(0)} KB · ready</div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Remove file"
              onClick={(e) => {
                e.stopPropagation()
                onRemove(0)
              }}
            >
              <X />
            </Button>
          </div>
        ) : files.length > 1 ? (
          <div className="flex items-center gap-3">
            <Layers className="size-8 text-zinc-500" />
            <div className="text-left">
              <div className="text-sm font-medium">{files.length} invoices ready</div>
              <div className="text-xs text-zinc-500">Drop or click to add more</div>
            </div>
          </div>
        ) : (
          <>
            <Upload className="size-6 text-zinc-400" />
            <div className="mt-2 text-sm font-medium">Drop PDFs, PNGs or JPGs here, or click to browse</div>
            <div className="mt-1 text-xs text-zinc-500">One invoice per file · up to 10 MB each · up to 50 files · INR invoices</div>
          </>
        )}
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          className="hidden"
          onChange={(e) => {
            const picked = Array.from(e.target.files ?? [])
            if (picked.length) onFiles(picked)
            e.target.value = ''
          }}
        />
      </div>
      {files.length > 1 && (
        <ul className="mt-3 max-h-48 divide-y divide-zinc-100 overflow-y-auto rounded-lg border border-zinc-200">
          {files.map((f, i) => (
            <li key={`${f.name}-${f.size}`} className="flex items-center gap-2 px-3 py-1.5 text-sm">
              <span className="w-6 shrink-0 text-right font-mono text-[11px] text-zinc-400">{i + 1}</span>
              <FileText className="size-4 shrink-0 text-zinc-400" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <span className="shrink-0 text-xs text-zinc-500">{(f.size / 1024).toFixed(0)} KB</span>
              <button type="button" aria-label={`Remove ${f.name}`} onClick={() => onRemove(i)} className="text-zinc-400 hover:text-zinc-900">
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
    </section>
  )
}

function SamplePicker({ samples, loading, selectedId, onSelect }: {
  samples: Sample[]; loading: boolean; selectedId: string | null; onSelect: (s: Sample) => void
}) {
  const [query, setQuery] = useState('')
  const [showExpected, setShowExpected] = useState(false)
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return samples
    return samples.filter((s) => `${s.id} ${s.scenario} ${humanize(s.scenario)} ${s.template}`.toLowerCase().includes(q))
  }, [samples, query])
  const golden = filtered.filter((s) => s.set === 'golden')
  const stress = filtered.filter((s) => s.set === 'stress')

  return (
    <section className="rounded-xl border border-zinc-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5 pb-3">
        <div>
          <h2 className="text-sm font-semibold">Or pick a sample</h2>
          <p className="text-xs text-zinc-500">Generated invoices with known answers: 12 golden demo cases, then the stress set.</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-600">
          <Switch checked={showExpected} onCheckedChange={setShowExpected} />
          Show expected outcome
        </label>
      </div>
      <div className="px-5 pb-3">
        <div className="relative">
          <Search className="absolute top-2.5 left-2.5 size-4 text-zinc-400" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by id, scenario or layout…" className="pl-8" />
        </div>
      </div>
      <div className="max-h-[420px] overflow-y-auto border-t border-zinc-100">
        {loading && <div className="p-5 text-sm text-zinc-500">Loading samples…</div>}
        {[['Golden demo set', golden], ['Stress set', stress]].map(([title, items]) =>
          (items as Sample[]).length ? (
            <div key={title as string}>
              <div className="sticky top-0 z-10 bg-zinc-50/95 px-5 py-1.5 text-[11px] font-semibold tracking-wide text-zinc-500 uppercase backdrop-blur">
                {title as string} · {(items as Sample[]).length}
              </div>
              {(items as Sample[]).map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onSelect(s)}
                  className={cn(
                    'flex w-full items-center gap-3 border-b border-zinc-100 px-5 py-2.5 text-left transition-colors last:border-0',
                    selectedId === s.id ? 'bg-zinc-100' : 'hover:bg-zinc-50',
                  )}
                >
                  <span className="w-36 shrink-0 truncate font-mono text-xs text-zinc-700">{s.id}</span>
                  <span className="min-w-0 flex-1 truncate text-sm">{humanize(s.scenario)}</span>
                  <span className="hidden shrink-0 text-xs text-zinc-500 md:inline">
                    {s.template.replace('_', ' ')}
                    {s.scan_level !== 'none' && ` · ${s.scan_level} scan`}
                  </span>
                  {showExpected && <DecisionPill outcome={s.expected_decision} className="shrink-0" />}
                </button>
              ))}
            </div>
          ) : null,
        )}
        {!loading && !filtered.length && <div className="p-5 text-sm text-zinc-500">No samples match "{query}".</div>}
      </div>
    </section>
  )
}
