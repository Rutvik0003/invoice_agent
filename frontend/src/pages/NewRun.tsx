import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, FileText, Info, Loader2, Play, Search, Upload, X } from 'lucide-react'
import { useMemo, useRef, useState, type DragEvent } from 'react'

import { PageHeader } from '@/components/AppShell'
import { DecisionPill } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, type Sample } from '@/lib/api'
import { humanize } from '@/lib/format'
import { navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const ACCEPTED = ['application/pdf', 'image/png', 'image/jpeg']
const MAX_MB = 10

type Choice = { kind: 'file'; file: File } | { kind: 'sample'; sample: Sample } | null

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
  const [useCache, setUseCache] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const selectedModel = model ?? config.data?.default_model ?? 'gemini'
  const modelInfo = config.data?.models.find((m) => m.id === selectedModel)

  const start = useMutation({
    mutationFn: () =>
      api.startRun({
        file: choice?.kind === 'file' ? choice.file : undefined,
        sampleId: choice?.kind === 'sample' ? choice.sample.id : undefined,
        model: selectedModel,
        useCache,
      }),
    onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`),
  })

  const canStart = choice !== null && !!modelInfo?.configured && !start.isPending

  return (
    <div>
      <PageHeader title="New Run" subtitle="Upload a vendor invoice or pick a sample. Every step of the decision is shown live." />
      <div className="grid gap-6 px-8 py-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6">
          <UploadCard
            file={choice?.kind === 'file' ? choice.file : null}
            error={fileError}
            onFile={(file) => {
              const problem = validate(file)
              setFileError(problem)
              if (!problem) setChoice({ kind: 'file', file })
            }}
            onClear={() => setChoice(null)}
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
                  <div className="mt-0.5 font-mono text-[11px] text-zinc-500">{m.model_name || 'model not set'}</div>
                  <div className="mt-1.5 text-xs leading-snug text-zinc-600">{m.description}</div>
                </button>
              ))}
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
            <div className="text-xs text-zinc-500">Invoice</div>
            <div className="mt-0.5 truncate text-sm font-medium">
              {choice?.kind === 'file' && choice.file.name}
              {choice?.kind === 'sample' && `${choice.sample.id} · ${humanize(choice.sample.scenario)}`}
              {!choice && <span className="text-zinc-400">Nothing selected yet</span>}
            </div>
            <Button className="mt-4 w-full" size="lg" disabled={!canStart} onClick={() => start.mutate()}>
              {start.isPending ? <Loader2 className="animate-spin" /> : <Play />}
              Start run
            </Button>
            {start.isError && <p className="mt-2 text-sm text-red-700">{start.error.message}</p>}
            {modelInfo && !modelInfo.configured && (
              <p className="mt-2 text-xs text-zinc-500">Set the {modelInfo.label} API key to use this model.</p>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function UploadCard({ file, error, onFile, onClear }: {
  file: File | null; error: string | null; onFile: (f: File) => void; onClear: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const drop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) onFile(dropped)
  }
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <h2 className="text-sm font-semibold">Upload an invoice</h2>
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
                onClear()
              }}
            >
              <X />
            </Button>
          </div>
        ) : (
          <>
            <Upload className="size-6 text-zinc-400" />
            <div className="mt-2 text-sm font-medium">Drop a PDF, PNG or JPG here, or click to browse</div>
            <div className="mt-1 text-xs text-zinc-500">One invoice per file · up to 10 MB · INR invoices</div>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          className="hidden"
          onChange={(e) => {
            const picked = e.target.files?.[0]
            if (picked) onFile(picked)
            e.target.value = ''
          }}
        />
      </div>
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
