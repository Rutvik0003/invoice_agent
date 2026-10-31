import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Clock, Download, Loader2, Plus, RotateCcw } from 'lucide-react'

import { PageHeader } from '@/components/AppShell'
import { CheckIcon, DecisionPill, OUTCOME_STYLE } from '@/components/status'
import { Button } from '@/components/ui/button'
import { api, type Outcome } from '@/lib/api'
import { api2, type Batch, type BatchItem } from '@/lib/api2'
import { duration, humanize, inr, timeAgo } from '@/lib/format'
import { Link, navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const OUTCOMES: Outcome[] = ['APPROVE', 'HOLD', 'REJECT']
const FAILED = ['extraction_failed', 'failed', 'interrupted']
const MODEL_LABEL: Record<string, string> = { gemini: 'Gemini', groq: 'Groq' }
const otherModel = (model: string) => (model === 'gemini' ? 'groq' : 'gemini')

function itemState(item: BatchItem): { label: string; cls: string; icon?: 'spin' | 'clock' } {
  switch (item.status) {
    case 'queued':
      return { label: item.queue_position ? `Queued · #${item.queue_position}` : 'Queued', cls: 'text-zinc-500', icon: 'clock' }
    case 'running':
      return { label: 'Processing…', cls: 'text-sky-700', icon: 'spin' }
    case 'extraction_failed':
      return { label: 'AI could not read it', cls: 'text-zinc-600' }
    case 'failed':
    case 'interrupted':
      return { label: humanize(item.status), cls: 'text-zinc-600' }
    case 'resolved_by_human':
      return { label: 'Resolved by a person', cls: 'text-zinc-600' }
    default:
      return { label: 'Done', cls: 'text-zinc-600' }
  }
}

function csv(batch: Batch): string {
  const rows = [['file', 'status', 'decision', 'vendor', 'invoice_number', 'total', 'po', 'reasons', 'run_id']]
  for (const i of batch.items ?? []) {
    rows.push([i.file_name, i.status, i.decision ?? '', i.vendor_name ?? '', i.invoice_number ?? '', i.total_amount?.toString() ?? '',
      i.po_number ?? '', i.reasons.map((r) => r.code).join(' '), i.id])
  }
  return rows.map((r) => r.map((v) => `"${String(v).replaceAll('"', '""')}"`).join(',')).join('\n')
}

/** A bulk upload: progress while the queue runs, then every invoice's decision and the combined result. */
export default function BatchView({ batchId }: { batchId: string }) {
  const queryClient = useQueryClient()
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  const retry = useMutation({
    mutationFn: (body: { model: string; run_ids?: string[] }) => api2.retryBatch(batchId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batch', batchId] }),
  })
  const usable = (model: string) => !!config.data?.models.find((m) => m.id === model)?.configured
  const batch = useQuery({
    queryKey: ['batch', batchId],
    queryFn: () => api2.batch(batchId),
    refetchInterval: (q) => (q.state.data?.finished ? false : 2_000),
  })
  if (batch.isError) return <div className="p-8 text-sm text-red-700">Could not load this batch: {batch.error.message}</div>
  if (!batch.data) return <div className="grid h-screen place-items-center text-zinc-400"><Loader2 className="animate-spin" /></div>
  const b = batch.data
  const items = b.items ?? []
  const pct = b.total ? Math.round((b.done / b.total) * 100) : 0
  const running = items.find((i) => i.status === 'running')
  const failed = b.failed
  const retryModel = otherModel(b.model)
  const download = () => {
    const url = URL.createObjectURL(new Blob([csv(b)], { type: 'text/csv' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `batch_${b.id.slice(0, 8)}.csv` })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <PageHeader
        title={`Batch of ${b.total} invoice${b.total === 1 ? '' : 's'}`}
        subtitle={`Uploaded ${timeAgo(b.created_at)} · ${b.model === 'gemini' ? 'Gemini' : 'Groq'}${b.model_name ? ` · ${b.model_name}` : ''} · processed one by one, in upload order`}
        actions={<div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={download} disabled={!items.length}><Download />CSV</Button>
          <Button variant="outline" size="sm" onClick={() => navigate('/')}><Plus />New run</Button>
        </div>}
      />
      <div className="space-y-5 px-8 py-6">
        <section className="rounded-xl border border-zinc-200 bg-white p-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{b.finished ? 'Finished' : 'In progress'}</div>
              <div className="mt-0.5 text-2xl font-semibold tabular-nums">{b.done} / {b.total}</div>
              {!b.finished && running && <div className="mt-0.5 text-sm text-sky-700">Now reading {running.file_name}…</div>}
              {b.finished && <div className="mt-0.5 text-sm text-zinc-600">Total invoiced {inr(b.total_amount)}</div>}
            </div>
            <div className="flex flex-wrap gap-2">
              {OUTCOMES.map((o) => (
                <div key={o} className={cn('min-w-24 rounded-lg px-3 py-2 ring-1', OUTCOME_STYLE[o].soft, OUTCOME_STYLE[o].ring)}>
                  <div className={cn('text-xs font-medium', OUTCOME_STYLE[o].text)}>{OUTCOME_STYLE[o].label}</div>
                  <div className="text-xl font-semibold tabular-nums">{b.by_decision[o] ?? 0}</div>
                </div>
              ))}
              {failed > 0 && (
                <div className="min-w-24 rounded-lg bg-zinc-100 px-3 py-2 ring-1 ring-zinc-200">
                  <div className="text-xs font-medium text-zinc-600">Not decided</div>
                  <div className="text-xl font-semibold tabular-nums">{failed}</div>
                </div>
              )}
            </div>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="flex h-full">
              {OUTCOMES.map((o) => <div key={o} className={cn('h-full transition-all', OUTCOME_STYLE[o].bg)} style={{ width: `${((b.by_decision[o] ?? 0) / b.total) * 100}%` }} />)}
              <div className="h-full bg-zinc-400 transition-all" style={{ width: `${(failed / b.total) * 100}%` }} />
            </div>
          </div>
          {failed > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-zinc-100 px-3 py-2.5 text-sm">
              <AlertTriangle className="size-4 text-zinc-600" />
              <span className="min-w-0 flex-1">{failed} invoice{failed > 1 ? 's' : ''} could not be read by the AI (for example a rate limit). They can be queued again here.</span>
              <Button size="sm" disabled={retry.isPending || !usable(retryModel)} onClick={() => retry.mutate({ model: retryModel })}>
                {retry.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}Retry all with {MODEL_LABEL[retryModel]}
              </Button>
              <Button size="sm" variant="outline" disabled={retry.isPending || !usable(b.model)} onClick={() => retry.mutate({ model: b.model })}>
                Retry with {MODEL_LABEL[b.model]}
              </Button>
              {retry.isError && <span className="w-full text-xs text-red-700">{retry.error.message}</span>}
            </div>
          )}
          {b.file_errors.length > 0 && (
            <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">
              <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="size-4" />{b.file_errors.length} file{b.file_errors.length > 1 ? 's were' : ' was'} not queued</div>
              <ul className="mt-1 space-y-0.5 text-xs">{b.file_errors.map((e) => <li key={e.file_name}><b>{e.file_name}</b>: {e.error}</li>)}</ul>
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-[11px] tracking-wide text-zinc-500 uppercase">
              <tr>
                <th className="w-10 px-4 py-2 font-medium">#</th>
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-4 py-2 font-medium">Decision</th>
                <th className="px-4 py-2 font-medium">Vendor · invoice</th>
                <th className="px-4 py-2 text-right font-medium">Total</th>
                <th className="px-4 py-2 font-medium">Main reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => {
                const state = itemState(item)
                // the reason behind the decision: a Reject code for a reject, a Hold code for a hold, a note for an approval
                const severity = item.decision === 'APPROVE' ? 'INFO' : item.decision
                const top = item.reasons.find((r) => r.severity === severity) ?? item.reasons[0]
                return (
                  <tr key={item.id} onClick={() => item.status !== 'queued' && navigate(`/runs/${item.id}`)}
                      className={cn('border-t border-zinc-100 align-top', item.status !== 'queued' && 'cursor-pointer hover:bg-zinc-50')}>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">{index + 1}</td>
                    <td className="max-w-56 px-4 py-2.5">
                      <div className="truncate font-medium">{item.file_name}</div>
                      <div className={cn('flex items-center gap-1 text-xs', state.cls)}>
                        {state.icon === 'spin' && <Loader2 className="size-3 animate-spin" />}
                        {state.icon === 'clock' && <Clock className="size-3" />}
                        {state.label}{item.duration_ms && item.status !== 'queued' && item.status !== 'running' ? ` · ${duration(item.duration_ms)}` : ''}
                        {item.attempt > 1 && ` · attempt ${item.attempt} (${MODEL_LABEL[item.model]})`}
                      </div>
                      {FAILED.includes(item.status) && (
                        <div className="mt-1 flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                          {[otherModel(item.model), item.model].map((m) => (
                            <button key={m} type="button" disabled={retry.isPending || !usable(m)}
                                    onClick={() => retry.mutate({ model: m, run_ids: [item.id] })}
                                    className="flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium text-zinc-700 ring-1 ring-zinc-300 hover:bg-zinc-100 disabled:opacity-40">
                              <RotateCcw className="size-3" />Retry with {MODEL_LABEL[m]}
                            </button>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5">{item.decision ? <DecisionPill outcome={item.decision} /> : <span className="text-xs text-zinc-400">—</span>}</td>
                    <td className="max-w-64 px-4 py-2.5">
                      <div className="truncate">{item.vendor_name ?? <span className="text-zinc-400">—</span>}</div>
                      <div className="truncate text-xs text-zinc-500">{item.invoice_number ?? ''}{item.po_number ? ` · ${item.po_number}` : ''}</div>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{item.total_amount != null ? inr(item.total_amount) : '—'}</td>
                    <td className="px-4 py-2.5">
                      {top ? (
                        <div className="flex gap-1.5">
                          <CheckIcon severity={top.severity} />
                          <span className="line-clamp-2 text-xs leading-snug text-zinc-700">{top.message}
                            {item.reasons.length > 1 && <span className="text-zinc-400"> (+{item.reasons.length - 1} more)</span>}</span>
                        </div>
                      ) : item.error ? <span className="text-xs text-zinc-600">{item.error.message}</span>
                        : item.decision === 'APPROVE' ? <span className="text-xs text-emerald-700">Matches its PO</span> : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
        <p className="text-xs text-zinc-500">
          Held invoices are also in the <Link to="/holds" className="underline underline-offset-2">Hold Queue</Link>. AI requests are spaced by the pause set in <Link to="/settings" className="underline underline-offset-2">Settings</Link> to stay inside the free-tier rate limits.
        </p>
      </div>
    </div>
  )
}
