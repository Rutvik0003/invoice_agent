import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Info, Search } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { PageHeader } from '@/components/AppShell'
import { DecisionsByDay, ReasonBars } from '@/components/charts'
import { DecisionPill, SHOWN_ORDER, SHOWN_STYLE } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api2 } from '@/lib/api2'
import { duration, inr, timeAgo } from '@/lib/format'
import { navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 12
const STATUS_TEXT: Record<string, string> = {
  completed: 'Completed', resolved_by_human: 'Checked by a person', extraction_failed: 'Extraction failed',
  failed: 'Failed', interrupted: 'Interrupted', running: 'Running', queued: 'Queued',
}

function Tile({ label, value, hint, accent, children }: { label: string; value: ReactNode; hint?: ReactNode; accent?: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="flex items-center gap-1 text-xs text-zinc-500">
        {accent && <span className="size-2 rounded-full" style={{ background: accent }} />}
        {label}
        {hint && (
          <Tooltip>
            <TooltipTrigger asChild><Info className="size-3 text-zinc-400" /></TooltipTrigger>
            <TooltipContent className="max-w-64">{hint}</TooltipContent>
          </Tooltip>
        )}
      </div>
      <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {children}
    </div>
  )
}

export default function Dashboard() {
  const [includeTest, setIncludeTest] = useState(false)
  const [search, setSearch] = useState('')
  const [outcome, setOutcome] = useState('')
  const [model, setModel] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const stats = useQuery({ queryKey: ['stats', includeTest], queryFn: () => api2.stats(includeTest), refetchInterval: 10_000 })
  const runs = useQuery({
    queryKey: ['runs', { includeTest, search, outcome, model, status, page }],
    queryFn: () => api2.runs({ include_test: includeTest, search, outcome, model, status, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  })
  const s = stats.data
  const total = s?.total_runs ?? 0
  const pct = (n: number | undefined) => (total ? `${Math.round(((n ?? 0) / total) * 100)}%` : '–')
  const pages = Math.max(1, Math.ceil((runs.data?.total ?? 0) / PAGE_SIZE))
  const resetPage = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1) }

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Every run, its decision, and why. Numbers update as runs finish."
        actions={<label className="flex items-center gap-2 text-sm text-zinc-600"><Switch checked={includeTest} onCheckedChange={resetPage(setIncludeTest)} />Include test runs</label>}
      />
      <div className="space-y-6 px-8 py-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="Total runs" value={total}>
            <div className="mt-1 text-xs text-zinc-500">{s?.by_status.extraction_failed ?? 0} could not be read</div>
          </Tile>
          {SHOWN_ORDER.map((o) => (
            <Tile key={o} label={SHOWN_STYLE[o].label} accent={SHOWN_STYLE[o].fill} value={s?.by_outcome[o] ?? 0}>
              <div className="mt-1 text-xs text-zinc-500">
                {o === 'CHANGES_REQUESTED' ? 'sent back to the vendor by a person' : `${pct(s?.by_outcome[o])} of runs`}
              </div>
            </Tile>
          ))}
          <Tile label="Avg processing time" value={s?.avg_duration_ms ? duration(s.avg_duration_ms) : '–'}>
            <div className="mt-1 text-xs text-zinc-500">upload to decision</div>
          </Tile>
          <Tile label="Critical fields verified" value={s?.critical_fields_verified_pct != null ? `${s.critical_fields_verified_pct}%` : '–'}
                hint="Share of printed vendor GSTIN, vendor name, invoice number, date and total that were found on the page itself (text layer or OCR), independently of the AI.">
            <div className="mt-1 text-xs text-zinc-500">all key fields: {s?.fields_verified_pct != null ? `${s.fields_verified_pct}%` : '–'}</div>
          </Tile>
          <Tile label="Est. AP time saved" value={s ? `${Math.floor(s.ap_minutes_saved / 60)} h ${s.ap_minutes_saved % 60} min` : '–'} hint={s?.ap_minutes_assumption}>
            <div className="mt-1 text-xs text-zinc-500">{s?.decided_automatically ?? 0} decided without a person</div>
          </Tile>
          <Tile label="Runs by model" value={<span className="text-base">
            {Object.entries(s?.runs_by_model ?? {}).map(([m, n]) => `${m === 'gemini' ? 'Gemini' : 'Groq'} ${n}`).join(' · ') || '–'}</span>} />
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <section className="rounded-xl border border-zinc-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold">Outcomes per day</h2>
            <DecisionsByDay rows={s?.outcomes_by_day ?? []} />
          </section>
          <section className="rounded-xl border border-zinc-200 bg-white p-4">
            <h2 className="mb-3 text-sm font-semibold">Top reasons</h2>
            <ReasonBars rows={s?.top_reason_codes ?? []} />
          </section>
        </div>

        <section className="rounded-xl border border-zinc-200 bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-zinc-100 p-3">
            <div className="relative min-w-56 flex-1">
              <Search className="absolute top-2.5 left-2.5 size-4 text-zinc-400" />
              <Input value={search} onChange={(e) => resetPage(setSearch)(e.target.value)} placeholder="Search file, vendor, invoice no., PO…" className="pl-8" />
            </div>
            <Filter value={outcome} onChange={resetPage(setOutcome)} label="Outcome" options={SHOWN_ORDER.map((o) => [o, SHOWN_STYLE[o].label])} />
            <Filter value={status} onChange={resetPage(setStatus)} label="Status" options={Object.entries(STATUS_TEXT)} />
            <Filter value={model} onChange={resetPage(setModel)} label="Model" options={[['gemini', 'Gemini'], ['groq', 'Groq']]} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-left text-[11px] tracking-wide text-zinc-500 uppercase">
                <tr>{['Time', 'File', 'Vendor', 'Amount', 'PO', 'Model', 'Outcome', 'Status', 'Duration'].map((h) => (
                  <th key={h} className={cn('px-3 py-2 font-medium', h === 'Amount' || h === 'Duration' ? 'text-right' : '')}>{h}</th>))}</tr>
              </thead>
              <tbody>
                {runs.data?.items.map((r) => (
                  <tr key={r.id} onClick={() => navigate(`/runs/${r.id}`)} className="cursor-pointer border-t border-zinc-100 hover:bg-zinc-50">
                    <td className="px-3 py-2 whitespace-nowrap text-zinc-500">{timeAgo(r.created_at)}</td>
                    <td className="max-w-48 truncate px-3 py-2" title={r.file_name}>
                      {r.file_name}{r.is_test_run && <span className="ml-1.5 rounded bg-zinc-100 px-1 text-[10px] text-zinc-500">test</span>}
                    </td>
                    <td className="max-w-48 truncate px-3 py-2" title={r.vendor_name ?? ''}>{r.vendor_name ?? '—'}</td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{inr(r.total_amount)}</td>
                    <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{r.po_number ?? '—'}</td>
                    <td className="px-3 py-2">{r.model === 'gemini' ? 'Gemini' : 'Groq'}{r.used_cache && <span className="ml-1 text-[10px] text-sky-700">cached</span>}</td>
                    <td className="px-3 py-2"><DecisionPill shown={r.outcome} /></td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap text-zinc-600">{STATUS_TEXT[r.status] ?? r.status}</td>
                    <td className="px-3 py-2 text-right text-xs tabular-nums text-zinc-500">{duration(r.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {runs.data && !runs.data.items.length && <p className="p-8 text-center text-sm text-zinc-500">No runs match. Start one from New Run.</p>}
          </div>
          <div className="flex items-center justify-between border-t border-zinc-100 px-3 py-2 text-xs text-zinc-500">
            <span>{runs.data?.total ?? 0} runs</span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" className="size-7" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
              <span className="tabular-nums">Page {page} of {pages}</span>
              <Button variant="ghost" size="icon" className="size-7" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

function Filter({ value, onChange, label, options }: { value: string; onChange: (v: string) => void; label: string; options: [string, string][] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
            className="h-9 rounded-md border border-zinc-200 bg-white px-2 text-sm text-zinc-700 outline-none focus:border-zinc-400">
      <option value="">{label}: all</option>
      {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
  )
}
