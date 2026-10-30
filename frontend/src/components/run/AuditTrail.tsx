import { UserCheck } from 'lucide-react'

import type { RunDetail, RunEvent } from '@/lib/api'
import { duration, fieldLabel, humanize } from '@/lib/format'
import { STAGES } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

const STAGE_TITLE: Record<string, string> = Object.fromEntries(STAGES.map((s) => [s.key, s.title]))

function describe(e: RunEvent): { text: string; tone: 'ok' | 'warn' | 'bad' | 'plain' } {
  const p = e.payload
  switch (e.type) {
    case 'stage_started':
      return { text: 'started', tone: 'plain' }
    case 'stage_completed':
      return { text: `${p.status ?? 'passed'} in ${duration(p.duration_ms)}`, tone: p.status === 'failed' ? 'bad' : p.status === 'warning' ? 'warn' : 'ok' }
    case 'stage_failed':
      return { text: `failed: ${p.error?.message ?? ''}`, tone: 'bad' }
    case 'run_completed':
      return { text: p.decision ? `decision ${p.decision}${p.ledger_applied ? ' · PO ledger updated' : ''}` : `ended: ${p.status}`, tone: p.decision === 'REJECT' ? 'bad' : p.decision === 'HOLD' ? 'warn' : 'ok' }
    case 'check_result':
      if (e.stage === 'verification') {
        return { text: `${fieldLabel(p.field)}: ${String(p.status).replace('_', ' ')}${p.matched_text ? ` (“${p.matched_text}”, ${p.source === 'ocr' ? 'OCR' : 'text layer'})` : ''}`,
                 tone: p.status === 'not_found' ? 'bad' : p.status === 'verified' ? 'ok' : 'plain' }
      }
      return { text: p.code ? `${humanize(p.code)}: ${p.message}` : p.message, tone: p.severity === 'REJECT' ? 'bad' : p.severity === 'HOLD' ? 'warn' : p.code ? 'plain' : 'ok' }
    default:
      return { text: e.type, tone: 'plain' }
  }
}

/** Every recorded event of the run, then every human action with role, comment and time. */
export function AuditTrail({ run }: { run: RunDetail }) {
  const actions = run.hold_actions ?? []
  return (
    <div className="space-y-4">
      {actions.length > 0 && (
        <section className="rounded-xl bg-white p-4 ring-1 ring-zinc-200">
          <h3 className="mb-2 text-sm font-semibold">People</h3>
          <ol className="space-y-2">
            {actions.map((a, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <UserCheck className="mt-0.5 size-4 shrink-0 text-zinc-500" />
                <div>
                  <div><b>{a.actor_role}</b> · {a.action.replace('_', ' ')}
                    <span className="ml-1.5 text-xs text-zinc-500">{new Date(a.created_at).toLocaleString('en-IN')}</span></div>
                  <div className="text-zinc-700">“{a.comment}”</div>
                  {a.payload && Object.keys(a.payload).length > 0 && (
                    <div className="font-mono text-[11px] text-zinc-500">{Object.entries(a.payload).map(([k, v]) => `${k}=${String(v)}`).join('  ')}</div>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      <section className="rounded-xl bg-white p-4 ring-1 ring-zinc-200">
        <h3 className="mb-2 text-sm font-semibold">System events ({run.events.length})</h3>
        <ol className="space-y-0.5 font-mono text-[11px]">
          {run.events.map((e) => {
            const { text, tone } = describe(e)
            return (
              <li key={e.id} className="grid grid-cols-[70px_120px_1fr] gap-2 border-b border-zinc-50 py-0.5">
                <span className="text-zinc-400">{e.created_at ? new Date(e.created_at).toLocaleTimeString('en-IN', { hour12: false }) : ''}</span>
                <span className="truncate text-zinc-500">{STAGE_TITLE[e.stage] ?? e.stage}</span>
                <span className={cn('break-words', tone === 'bad' && 'text-red-700', tone === 'warn' && 'text-amber-700', tone === 'ok' && 'text-emerald-700')}>{text}</span>
              </li>
            )
          })}
        </ol>
      </section>
    </div>
  )
}

/** Raw JSON as stored for the run (collapsible). */
export function RawData({ run }: { run: RunDetail }) {
  const blocks: [string, unknown][] = [
    ['Extracted by the AI (Stage 2)', run.extracted],
    ['Found on the page (Stage 3)', run.verification],
    ['Rules and decision (Stages 4-8)', run.rules],
    ['Error', run.error_detail],
  ]
  return (
    <div className="space-y-2">
      {blocks.filter(([, v]) => v).map(([title, value]) => (
        <details key={title} className="rounded-xl bg-white ring-1 ring-zinc-200">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium">{title}</summary>
          <pre className="max-h-[420px] overflow-auto border-t border-zinc-100 bg-zinc-50 p-3 text-[11px] leading-snug">{JSON.stringify(value, null, 2)}</pre>
        </details>
      ))}
    </div>
  )
}
