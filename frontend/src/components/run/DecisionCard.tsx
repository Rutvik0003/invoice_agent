import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Clock, Loader2, RotateCcw } from 'lucide-react'

import { CheckIcon, OUTCOME_STYLE } from '@/components/status'
import { Button } from '@/components/ui/button'
import { api, type AppConfig, type Decision, type LedgerChange, type RunDetail, type RunError } from '@/lib/api'
import { inr, num } from '@/lib/format'
import { useMode } from '@/lib/mode'
import { navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const ROLE_ORDER = ['Finance controller', 'Procurement', 'Tax team', 'Buyer', 'AP clerk']

/** The final answer, kept short: Paid / Needs human verification / Rejected, who checks it, and every reason in one line. */
export function DecisionCard({ decision, ledger, sample }: {
  decision: Decision; ledger: LedgerChange | null; sample: RunDetail['sample']
}) {
  const style = OUTCOME_STYLE[decision.outcome]
  const reasons = decision.reasons
  const roles = [...new Set(decision.routed_questions.map((q) => q.role))].sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b))
  return (
    <section className={cn('overflow-hidden rounded-xl bg-white ring-1', style.ring)}>
      <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5', style.bg)}>
        <div className="text-lg font-bold tracking-tight text-white">
          {style.label}
          {decision.approve_with_note && <span className="ml-1.5 align-middle text-xs font-medium opacity-90">with note</span>}
        </div>
        {roles.length > 0 && <span className="text-xs text-white/90">for {roles.join(', ')}</span>}
        {sample && (
          <span className="ml-auto rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-medium text-white">
            Expected: {OUTCOME_STYLE[sample.expected_decision].label} {sample.expected_decision === decision.outcome ? '✓' : '✗'}
          </span>
        )}
      </div>
      <div className="space-y-3 px-4 py-3">
        {reasons.length > 0 ? (
          <ul className="space-y-1">
            {reasons.map((r, i) => (
              <li key={i} className="flex gap-2 text-[13px] leading-snug">
                <CheckIcon severity={r.severity} />
                <span className="min-w-0" title={r.code ?? undefined}>{r.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-zinc-600">Every check passed.</p>
        )}
        {decision.outcome === 'APPROVE' && ledger && <LedgerSummary ledger={ledger} />}
      </div>
    </section>
  )
}

/** Approve: one line for the PO ledger change, the per-line detail folded away. */
function LedgerSummary({ ledger }: { ledger: LedgerChange }) {
  return (
    <details className="rounded-lg bg-zinc-50 px-3 py-2 text-[13px]">
      <summary className="cursor-pointer">
        {ledger.po_number} billed {inr(ledger.billed_before)} <ArrowRight className="inline size-3 text-zinc-400" /> <b>{inr(ledger.billed_after)}</b>
        <span className="text-xs text-zinc-500"> of {inr(ledger.po_value)}</span>
      </summary>
      <div className="mt-2"><LedgerTable ledger={ledger} /></div>
    </details>
  )
}

function LedgerTable({ ledger }: { ledger: LedgerChange }) {
  return (
    <div>
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

/** Demo: the free-tier AI key is busy. Not an error of the invoice or the app: try again later. */
function RateLimitNotice({ onRetry, current, others, retry }: {
  onRetry: (choice: string) => void; current: string | null; others: string[]
  retry: { isPending: boolean; isError: boolean; error: Error | null }
}) {
  return (
    <section className="rounded-xl bg-sky-50 px-5 py-4 ring-1 ring-sky-200">
      <div className="flex items-center gap-2 text-sky-900">
        <Clock className="size-5" />
        <h2 className="text-base font-semibold">The AI model has reached its rate limit</h2>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-sky-900/80">
        The demo uses a free-tier AI key, which allows only a few requests per minute and per day. Please try again after
        some time, or with another Gemini model (each model has its own free-tier limit).
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => onRetry('gemini')}>
          {retry.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}Try again
          {current && <> · <span className="font-mono text-xs">{current}</span></>}
        </Button>
        {others.map((m) => (
          <Button key={m} size="sm" variant="outline" disabled={retry.isPending} onClick={() => onRetry(m)}>
            Try · <span className="font-mono text-xs">{m}</span>
          </Button>
        ))}
      </div>
      {retry.isError && <p className="mt-2 text-sm text-sky-900">{retry.error?.message}</p>}
    </section>
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
  // a model name ('gemini-…') retries with that Gemini model; 'gemini' / 'groq' retries with the provider's model
  const retry = useMutation({
    mutationFn: (choice: string) => (choice.startsWith('gemini-') ? api.retry(run.id, 'gemini', choice) : api.retry(run.id, choice)),
    onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`),
  })
  const { isDemo } = useMode()
  const otherGemini = (config?.models.find((m) => m.id === 'gemini')?.choices ?? []).filter((c) => c !== run.model_name)
  if (isDemo && error.type === 'rate_limited') {
    return <RateLimitNotice onRetry={(choice) => retry.mutate(choice)} current={run.model_name} others={otherGemini} retry={retry} />
  }
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
          {otherInfo && !isDemo && (
            <Button disabled={!otherInfo.configured || retry.isPending} onClick={() => retry.mutate(other)}>
              {retry.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}Retry with {otherInfo.label}
            </Button>
          )}
          <Button variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(run.model)}>
            {isDemo && retry.isPending ? <Loader2 className="animate-spin" /> : isDemo ? <RotateCcw /> : null}
            {isDemo ? 'Try again' : `Retry with ${run.model === 'gemini' ? 'Gemini' : 'Groq'}`}
            {run.model_name && <> · <span className="font-mono text-xs">{run.model_name}</span></>}
          </Button>
          {isDemo && otherGemini.map((m) => (
            <Button key={m} variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(m)}>
              Try · <span className="font-mono text-xs">{m}</span>
            </Button>
          ))}
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
