import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Check, Copy, Loader2, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { CheckIcon, OUTCOME_STYLE } from '@/components/status'
import { Button } from '@/components/ui/button'
import { api, type AppConfig, type Decision, type LedgerChange, type RunDetail, type RunError } from '@/lib/api'
import { humanize, inr, num } from '@/lib/format'
import { navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const ROLE_ORDER = ['Finance controller', 'Procurement', 'Tax team', 'Buyer', 'AP clerk']

/** The final answer: Approve / Hold / Reject, every reason, and what happens next. */
export function DecisionCard({ decision, ledger, sample }: {
  decision: Decision; ledger: LedgerChange | null; sample: RunDetail['sample']
}) {
  const style = OUTCOME_STYLE[decision.outcome]
  const reasons = decision.reasons
  return (
    <section className={cn('overflow-hidden rounded-xl bg-white ring-1', style.ring)}>
      <div className={cn('flex items-center justify-between gap-3 px-5 py-4', style.bg)}>
        <div className="text-2xl font-bold tracking-tight text-white">
          {decision.outcome}
          {decision.approve_with_note && <span className="ml-2 align-middle text-sm font-medium opacity-90">with note</span>}
        </div>
        {sample && (
          <span className="rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-medium text-white">
            Expected for {sample.id}: {sample.expected_decision} {sample.expected_decision === decision.outcome ? '✓' : '✗'}
          </span>
        )}
      </div>
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm leading-relaxed text-zinc-700">{decision.summary}</p>

        {reasons.length > 0 && (
          <div>
            <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-zinc-500 uppercase">Why ({reasons.length})</h3>
            <ul className="space-y-1.5">
              {reasons.map((r, i) => (
                <li key={i} className="flex gap-2 text-sm">
                  <CheckIcon severity={r.severity} />
                  <div className="min-w-0">
                    <span className="leading-snug">{r.message}</span>
                    <span className="ml-1.5 font-mono text-[10px] text-zinc-400">{r.code}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {decision.outcome === 'HOLD' && <RoutedQuestions decision={decision} />}
        {decision.outcome === 'REJECT' && decision.vendor_note && <VendorNote note={decision.vendor_note} />}
        {decision.outcome === 'APPROVE' && ledger && <LedgerTable ledger={ledger} />}
      </div>
    </section>
  )
}

function RoutedQuestions({ decision }: { decision: Decision }) {
  const questions = [...decision.routed_questions].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role))
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-zinc-500 uppercase">Sent to</h3>
      <div className="space-y-2">
        {questions.map((q) => (
          <div key={q.role} className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
            <div className="mb-1 flex flex-wrap items-center gap-1.5">
              <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[11px] font-semibold text-white">{q.role}</span>
              {q.codes.map((c) => <span key={c} className="text-[11px] text-amber-800">{humanize(c)}</span>)}
            </div>
            <p className="text-sm leading-relaxed whitespace-pre-line text-zinc-800">{q.question}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function VendorNote({ note }: { note: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Draft note to the vendor</h3>
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => {
          navigator.clipboard.writeText(note).then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1500)
          })
        }}>
          {copied ? <Check /> : <Copy />}{copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <pre className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-sans text-sm leading-relaxed whitespace-pre-wrap text-zinc-800">{note}</pre>
    </div>
  )
}

function LedgerTable({ ledger }: { ledger: LedgerChange }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-zinc-500 uppercase">PO ledger updated: {ledger.po_number}</h3>
      <div className="overflow-hidden rounded-lg border border-zinc-200">
        <table className="w-full table-fixed text-sm">
          <thead className="bg-zinc-50 text-[11px] text-zinc-500">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium">PO line</th>
              <th className="w-28 px-3 py-1.5 text-right font-medium">Billed</th>
              <th className="w-28 px-3 py-1.5 text-right font-medium">Left on PO</th>
            </tr>
          </thead>
          <tbody>
            {ledger.lines.map((l) => (
              <tr key={l.line_no} className="border-t border-zinc-100">
                <td className="truncate px-3 py-1.5" title={l.description}><span className="text-zinc-400">{l.line_no}.</span> {l.description}</td>
                <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                  {num(l.billed_before)} <ArrowRight className="inline size-3 text-zinc-400" /> <b>{num(l.billed_after)}</b>
                </td>
                <td className="px-3 py-1.5 text-right text-xs tabular-nums whitespace-nowrap text-zinc-600">
                  {num(l.remaining_after)} of {num(l.ordered)} {l.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between gap-2 border-t border-zinc-200 bg-zinc-50 px-3 py-2 text-sm">
          <span className="text-xs text-zinc-500">PO billed, before tax (value {inr(ledger.po_value)})</span>
          <span className="tabular-nums whitespace-nowrap">
            {inr(ledger.billed_before)} <ArrowRight className="inline size-3 text-zinc-400" /> <b>{inr(ledger.billed_after)}</b>
          </span>
        </div>
      </div>
      <p className="mt-1.5 text-xs text-zinc-500">
        PO status {ledger.status_before.replace('_', ' ')} → {ledger.status_after.replace('_', ' ')}; invoice added to history as {ledger.history_id}.
      </p>
    </div>
  )
}

const ERROR_TITLE: Record<string, string> = {
  rate_limited: 'The model is rate-limited',
  timeout: 'The model took too long to answer',
  invalid_response: "The model's answer could not be read",
  provider_error: 'The model service had a problem',
  auth_error: 'The API key was rejected',
  unsupported_file: 'This file type cannot be read',
  internal_error: 'Processing stopped unexpectedly',
  interrupted: 'The server restarted during this run',
}

/** Extraction failed: say why in plain words and offer a one-click retry (same file). */
export function FailureCard({ run, error, config, heading = 'Could not read the invoice' }:
  { run: RunDetail; error: RunError; config: AppConfig | undefined; heading?: string }) {
  const other = run.model === 'gemini' ? 'groq' : 'gemini'
  const otherInfo = config?.models.find((m) => m.id === other)
  const retry = useMutation({ mutationFn: (model: string) => api.retry(run.id, model), onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`) })
  return (
    <section className="overflow-hidden rounded-xl bg-white ring-1 ring-zinc-300">
      <div className="bg-zinc-700 px-5 py-4 text-white">
        <div className="text-xs font-medium tracking-wide uppercase opacity-80">{heading}</div>
        <div className="text-lg font-semibold">{ERROR_TITLE[error.type] ?? 'Extraction failed'}</div>
      </div>
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm leading-relaxed text-zinc-700">{error.message}</p>
        <p className="text-xs text-zinc-500">No decision was made: the rules only run on an invoice that was read and checked completely.</p>
        <div className="flex flex-wrap gap-2">
          {otherInfo && (
            <Button disabled={!otherInfo.configured || retry.isPending} onClick={() => retry.mutate(other)}>
              {retry.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}Retry with {otherInfo.label}
            </Button>
          )}
          <Button variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(run.model)}>
            Retry with {run.model === 'gemini' ? 'Gemini' : 'Groq'}
          </Button>
        </div>
        {retry.isError && <p className="text-sm text-red-700">{retry.error.message}</p>}
        {error.detail && (
          <details className="text-xs text-zinc-500">
            <summary className="cursor-pointer">Technical detail</summary>
            <p className="mt-1 break-all">{error.detail}</p>
          </details>
        )}
      </div>
    </section>
  )
}
