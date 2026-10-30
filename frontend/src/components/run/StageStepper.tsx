import { ChevronDown } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { CheckIcon, StageIcon } from '@/components/status'
import type { CheckResult } from '@/lib/api'
import { duration, fieldLabel, fieldValue, humanize } from '@/lib/format'
import { STAGES, type LiveState, type StageKey } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

type Props = {
  state: LiveState
  renderDetail: (key: StageKey) => ReactNode
}

/** The 8 stages top to bottom; each expands to show exactly what it checked. */
export function StageStepper({ state, renderDetail }: Props) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  // auto-open the stage that is running, and keep any stage that raised something open
  useEffect(() => {
    const updates: Record<string, boolean> = {}
    for (const s of STAGES) {
      const st = state.stages[s.key]
      if (st.status === 'running' && open[s.key] === undefined && (s.key === 'extraction' || s.key === 'verification')) updates[s.key] = true
      if ((st.status === 'warning' || st.status === 'failed') && open[s.key] === undefined) updates[s.key] = true
    }
    if (Object.keys(updates).length) setOpen((o) => ({ ...updates, ...o }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.stages])

  return (
    <ol className="relative">
      {STAGES.map((s, i) => {
        const st = state.stages[s.key]
        const expandable = st.status !== 'pending'
        const isOpen = !!open[s.key] && expandable
        return (
          <li key={s.key} className="relative pl-9">
            {i < STAGES.length - 1 && (
              <span className={cn('absolute top-7 bottom-0 left-[11px] w-px', st.status === 'pending' ? 'bg-zinc-200' : 'bg-zinc-300')} />
            )}
            <span className="absolute top-2.5 left-0"><StageIcon status={st.status} /></span>
            <button
              type="button"
              disabled={!expandable}
              onClick={() => setOpen((o) => ({ ...o, [s.key]: !isOpen }))}
              className="flex w-full items-start gap-2 rounded-md py-2.5 pr-1 text-left disabled:cursor-default"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-[11px] font-medium text-zinc-400 tabular-nums">{i + 1}</span>
                  <span className={cn('text-sm font-medium', st.status === 'pending' && 'text-zinc-400')}>{s.title}</span>
                  <StageSummary state={state} stageKey={s.key} />
                </div>
                <div className="text-xs text-zinc-500">{s.blurb}</div>
              </div>
              <span className="shrink-0 pt-0.5 text-[11px] text-zinc-400 tabular-nums">
                {st.status === 'running' ? 'running…' : duration(st.durationMs)}
              </span>
              {expandable && <ChevronDown className={cn('mt-0.5 size-4 shrink-0 text-zinc-400 transition-transform', isOpen && 'rotate-180')} />}
            </button>
            {isOpen && <div className="animate-in fade-in slide-in-from-top-1 pb-3 duration-200">{renderDetail(s.key)}</div>}
          </li>
        )
      })}
    </ol>
  )
}

function StageSummary({ state, stageKey }: { state: LiveState; stageKey: StageKey }) {
  const st = state.stages[stageKey]
  if (st.status === 'pending' || st.status === 'running') return null
  let text = ''
  if (stageKey === 'verification' && st.payload.printed !== undefined) text = `${st.payload.verified}/${st.payload.printed} found`
  else if (stageKey === 'extraction' && st.status !== 'failed') text = st.payload.cached ? 'cached' : ''
  else {
    const raised = st.checks.filter((c) => c.code && c.severity !== 'INFO').length
    if (raised) text = `${raised} issue${raised > 1 ? 's' : ''}`
  }
  if (!text) return null
  return <span className={cn('text-xs', st.status === 'failed' ? 'text-red-600' : st.status === 'warning' ? 'text-amber-700' : 'text-zinc-500')}>· {text}</span>
}

function show(field: string | null, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'number' && field) return fieldValue(field, value)
  return String(value)
}

/** One line per check: ✓ / ! / ✗, the plain-English message, and invoice value vs reference value. */
export function ChecksList({ checks }: { checks: CheckResult[] }) {
  if (!checks.length) return <p className="text-sm text-zinc-500">Nothing to check here.</p>
  return (
    <ul className="space-y-1.5">
      {checks.map((c, i) => {
        const e = c.evidence
        const hasEvidence = e && (e.reference_value !== null && e.reference_value !== undefined || e.reference_source)
        return (
          <li key={i} className={cn('flex gap-2 rounded-md px-2.5 py-1.5 text-sm',
            c.severity === 'REJECT' ? 'bg-red-50' : c.severity === 'HOLD' ? 'bg-amber-50' : c.severity === 'INFO' ? 'bg-sky-50' : '')}>
            <CheckIcon severity={c.code ? c.severity : null} />
            <div className="min-w-0">
              <div className="leading-snug">{c.message}</div>
              {c.code && <div className="mt-0.5 font-mono text-[10px] tracking-wide text-zinc-500">{c.code} · {humanize(c.code)}</div>}
              {c.code && hasEvidence && (
                <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 text-[11px] text-zinc-600">
                  {e.invoice_field && <><span className="text-zinc-400">Invoice</span><span className="break-all">{fieldLabel(e.invoice_field)}: {show(e.invoice_field, e.invoice_value)}{e.verification_status ? ` (${e.verification_status.replace('_', ' ')})` : ''}</span></>}
                  {e.reference_source && <><span className="text-zinc-400">Reference</span><span className="break-all">{e.reference_source}: {show(e.invoice_field, e.reference_value)}</span></>}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
