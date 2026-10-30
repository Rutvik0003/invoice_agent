import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Wifi, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AuditTrail, RawData } from '@/components/run/AuditTrail'
import { ExtractedFields, VerifiedFields } from '@/components/run/FieldTables'
import { DecisionCard, FailureCard } from '@/components/run/DecisionCard'
import { PageViewer } from '@/components/run/PageViewer'
import { ChecksList, StageStepper } from '@/components/run/StageStepper'
import { Button } from '@/components/ui/button'
import { api, type ExtractedInvoice, type RunDetail } from '@/lib/api'
import { duration, humanize, inr } from '@/lib/format'
import { Link, navigate } from '@/lib/router'
import { useRunEvents, type LiveState, type StageKey } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

const FINAL = ['completed', 'extraction_failed', 'failed', 'resolved_by_human']

export default function LiveRun({ runId }: { runId: string }) {
  const queryClient = useQueryClient()
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.run(runId) })
  const [finishedAtOpen, setFinishedAtOpen] = useState<boolean | null>(null)
  useEffect(() => setFinishedAtOpen(null), [runId])
  useEffect(() => {
    if (run.data && finishedAtOpen === null) setFinishedAtOpen(FINAL.includes(run.data.status))
  }, [run.data, finishedAtOpen])

  const live = useRunEvents(runId, finishedAtOpen)
  const [selected, setSelected] = useState<string | null>(null)
  const [pulseKey, setPulseKey] = useState(0)
  const [tab, setTab] = useState<'overview' | 'audit' | 'raw'>('overview')
  const select = (field: string) => {
    setSelected(field)
    setPulseKey((k) => k + 1)
  }

  // once the last event is shown, fetch the stored decision (reasons, routed questions, vendor note, ledger)
  useEffect(() => {
    if (live.finished) queryClient.invalidateQueries({ queryKey: ['run', runId] })
  }, [live.finished, runId, queryClient])

  if (run.isError) {
    return <div className="p-8 text-sm text-red-700">Could not load this run: {run.error.message}</div>
  }
  if (!run.data) {
    return <div className="grid h-screen place-items-center text-zinc-400"><Loader2 className="animate-spin" /></div>
  }
  const detail = run.data
  const threshold = config.data?.confidence_threshold ?? 0.8
  const extractionError = live.stages.extraction.error ?? (live.finished?.status === 'extraction_failed' ? detail.error : null)
  const decided = live.finished?.decision && detail.rules?.decision

  const renderDetail = (key: StageKey) => <StageDetail stageKey={key} live={live} detail={detail} threshold={threshold}
                                                       selected={selected} onSelect={select} />

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-200 bg-white px-6 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-base font-semibold">{detail.file_name}</h1>
            {detail.sample && <span className="truncate text-sm text-zinc-500">· {humanize(detail.sample.scenario)}</span>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-medium text-zinc-700">
              {detail.model === 'gemini' ? 'Gemini' : 'Groq'}{detail.model_name ? ` · ${detail.model_name}` : ''}
            </span>
            {(detail.used_cache || live.stages.extraction.payload.cached) && (
              <span className="rounded bg-sky-100 px-1.5 py-0.5 font-medium text-sky-800">cached extraction</span>
            )}
            {detail.retry_of && <Link to={`/runs/${detail.retry_of}`} className="underline underline-offset-2">retry of an earlier run</Link>}
            <span className="font-mono text-[11px] text-zinc-400">{runId.slice(0, 8)}</span>
            {detail.duration_ms && live.finished && <span>· {duration(detail.duration_ms)} total</span>}
          </div>
        </div>
        <ConnectionBadge live={live} />
        <Button variant="outline" size="sm" onClick={() => navigate('/')}><Plus />New run</Button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(400px,500px)]">
        <div className="min-h-0 border-r border-zinc-200">
          <PageViewer runId={runId} pageCount={detail.page_count ?? 1} fields={live.fields} selected={selected}
                      pulseKey={pulseKey} onSelect={select} />
        </div>
        <div className="min-h-0 space-y-4 overflow-y-auto bg-zinc-50 p-5">
          {live.finished && (
            <div className="flex gap-1 rounded-lg bg-zinc-200/60 p-1 text-sm">
              {(['overview', 'audit', 'raw'] as const).map((t) => (
                <button key={t} type="button" onClick={() => setTab(t)}
                        className={cn('flex-1 rounded-md px-3 py-1.5 transition-colors', tab === t ? 'bg-white font-medium shadow-sm' : 'text-zinc-600 hover:text-zinc-900')}>
                  {{ overview: 'Overview', audit: 'Audit trail', raw: 'Raw data' }[t]}
                </button>
              ))}
            </div>
          )}
          {tab === 'audit' && live.finished && <AuditTrail run={detail} />}
          {tab === 'raw' && live.finished && <RawData run={detail} />}
          {(tab === 'overview' || !live.finished) && <>
          {detail.retries.length > 0 && (
            <div className="rounded-lg bg-white px-4 py-2.5 text-sm ring-1 ring-zinc-200">
              Retried as {detail.retries.map((id) => <Link key={id} to={`/runs/${id}`} className="ml-1 font-mono text-xs underline underline-offset-2">{id.slice(0, 8)}</Link>)}
            </div>
          )}
          {detail.status === 'resolved_by_human' && <HumanResolution run={detail} />}
          {extractionError && <FailureCard run={detail} error={extractionError} config={config.data} />}
          {decided && <DecisionCard decision={detail.rules!.decision} ledger={detail.rules!.ledger_change} sample={detail.sample} />}
          {live.finished?.decision && !detail.rules && (
            <div className="flex items-center gap-2 rounded-xl bg-white p-4 text-sm text-zinc-500 ring-1 ring-zinc-200">
              <Loader2 className="size-4 animate-spin" /> Loading the decision…
            </div>
          )}
          {live.finished?.status === 'failed' && (
            <div className="rounded-xl bg-white p-4 text-sm text-red-700 ring-1 ring-red-200">
              Processing stopped because of an internal error. {detail.error?.message}
            </div>
          )}
          <section className="rounded-xl bg-white px-4 py-2 ring-1 ring-zinc-200">
            <StageStepper state={live} renderDetail={renderDetail} />
          </section>
          </>}
        </div>
      </div>
    </div>
  )
}

/** A person resolved this hold: show the final decision, who, when and why, above the engine's decision. */
function HumanResolution({ run }: { run: RunDetail }) {
  const final = [...(run.hold_actions ?? [])].reverse().find((a) => a.action === 'approve' || a.action === 'reject')
  return (
    <div className={cn('rounded-xl p-4 ring-1', run.decision === 'APPROVE' ? 'bg-emerald-50 ring-emerald-200' : 'bg-red-50 ring-red-200')}>
      <div className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Resolved by a person</div>
      <div className="mt-0.5 text-lg font-semibold">{run.decision === 'APPROVE' ? 'Approved' : 'Rejected'}
        {final && <span className="text-sm font-normal text-zinc-600"> by {final.actor_role} · {new Date(final.created_at).toLocaleString('en-IN')}</span>}</div>
      {final && <p className="mt-1 text-sm text-zinc-700">“{final.comment}”</p>}
      {run.rules?.ledger_applied && run.decision === 'APPROVE' && run.rules.ledger_change && (
        <p className="mt-1 text-xs text-zinc-600">PO ledger updated: {run.rules.ledger_change.po_number} billed {inr(run.rules.ledger_change.billed_before)} → {inr(run.rules.ledger_change.billed_after)}</p>
      )}
      <p className="mt-2 text-xs text-zinc-500">The engine's original decision (Hold) and its reasons are below. Full history in the Audit trail tab.</p>
    </div>
  )
}

function ConnectionBadge({ live }: { live: LiveState }) {
  if (live.connection === 'closed') return null
  const reconnecting = live.connection === 'reconnecting'
  return (
    <span className={cn('flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs', reconnecting ? 'bg-amber-50 text-amber-800' : 'bg-zinc-100 text-zinc-600')}>
      {reconnecting ? <WifiOff className="size-3.5" /> : <Wifi className="size-3.5" />}
      {reconnecting ? 'Reconnecting…' : live.connection === 'live' ? 'Live' : 'Connecting…'}
    </span>
  )
}

function StageDetail({ stageKey, live, detail, threshold, selected, onSelect }: {
  stageKey: StageKey; live: LiveState; detail: RunDetail; threshold: number; selected: string | null; onSelect: (f: string) => void
}) {
  const st = live.stages[stageKey]
  const p = st.payload
  switch (stageKey) {
    case 'intake':
      return (
        <div className="space-y-1.5 text-sm">
          <div className="flex flex-wrap gap-1.5">
            {(p.pages ?? []).map((pg: { page: number; text_layer: boolean }) => (
              <span key={pg.page} className={cn('rounded-full px-2 py-0.5 text-xs ring-1',
                pg.text_layer ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-zinc-100 text-zinc-700 ring-zinc-200')}>
                Page {pg.page}: {pg.text_layer ? 'digital text' : 'scanned image (OCR)'}
              </span>
            ))}
          </div>
          <div className="text-xs text-zinc-500">
            {p.mime} · {p.size_bytes ? `${Math.round(p.size_bytes / 1024)} KB` : ''} · SHA-256 <span className="font-mono">{String(p.file_hash ?? '').slice(0, 16)}…</span>
          </div>
        </div>
      )
    case 'extraction':
      if (st.status === 'failed') return <p className="text-sm text-zinc-600">{st.error?.message}</p>
      return (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-medium text-zinc-700">{p.provider} · {p.model_name}</span>
            {p.cached && <span className="rounded bg-sky-100 px-1.5 py-0.5 font-medium text-sky-800">cached extraction</span>}
            {p.repaired && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">answer repaired once</span>}
            {!p.cached && p.latency_ms && <span className="text-zinc-500">model answered in {duration(p.latency_ms)}</span>}
          </div>
          {p.invoice && <ExtractedFields invoice={p.invoice as ExtractedInvoice} threshold={threshold} />}
          <p className="text-[11px] text-zinc-500">Confidence is the model's own estimate; red is below {Math.round(threshold * 100)}%. Stage 3 checks the values independently.</p>
        </div>
      )
    case 'verification':
      return (
        <div className="space-y-2">
          {p.engine_used && (
            <div className="text-xs text-zinc-500">
              Read from the {p.engine_used === 'text_layer' ? 'PDF text layer (exact)' : p.engine_used === 'ocr' ? 'page image with OCR' : p.engine_used}. Click a row to see it on the page.
            </div>
          )}
          <VerifiedFields fields={live.fields} selected={selected} onSelect={onSelect} />
        </div>
      )
    case 'decision':
      return <p className="text-sm text-zinc-600">{live.finished?.summary ?? detail.rules?.decision.summary ?? 'Deciding…'}</p>
    default:
      return <ChecksList checks={st.checks} />
  }
}
