/** Shared status visuals. People see two outcomes: green Paid and amber Needs human verification (the engine's Hold
 *  and Reject both wait for a person; a Reject is tagged "vendor must fix"). Once a person sends a bill back it shows
 *  gray "Changes requested". The engine's codes stay APPROVE / HOLD / REJECT. */

import { AlertTriangle, Check, Circle, Info, Loader2, X } from 'lucide-react'

import type { Outcome, Severity, Shown } from '@/lib/api'
import type { StageStatus } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

type Style = { bg: string; text: string; ring: string; soft: string; label: string; fill: string }

export const SHOWN_STYLE: Record<Shown, Style> = {
  PAID: { bg: 'bg-emerald-600', text: 'text-emerald-700', ring: 'ring-emerald-200', soft: 'bg-emerald-50', label: 'Paid', fill: '#059669' },
  NEEDS_VERIFICATION: { bg: 'bg-amber-500', text: 'text-amber-700', ring: 'ring-amber-200', soft: 'bg-amber-50', label: 'Needs human verification', fill: '#f59e0b' },
  CHANGES_REQUESTED: { bg: 'bg-slate-500', text: 'text-slate-700', ring: 'ring-slate-200', soft: 'bg-slate-50', label: 'Changes requested', fill: '#64748b' },
}
export const SHOWN_ORDER: Shown[] = ['PAID', 'NEEDS_VERIFICATION', 'CHANGES_REQUESTED']

/** The engine's decision as people see it (before a person acts on it). */
export const OUTCOME_STYLE: Record<Outcome, Style> = {
  APPROVE: SHOWN_STYLE.PAID,
  HOLD: SHOWN_STYLE.NEEDS_VERIFICATION,
  REJECT: SHOWN_STYLE.NEEDS_VERIFICATION,
}

/** Paid / Needs human verification / Changes requested, from the engine's decision and the run status. */
export function shownOf(decision: Outcome | null, status?: string): Shown | null {
  if (!decision) return null
  if (decision === 'APPROVE') return 'PAID'
  return status === 'resolved_by_human' ? 'CHANGES_REQUESTED' : 'NEEDS_VERIFICATION'
}

export function DecisionPill({ outcome, status, shown, className }: {
  outcome?: Outcome | null; status?: string; shown?: Shown | null; className?: string
}) {
  const value = shown ?? shownOf(outcome ?? null, status)
  if (!value) return <span className={cn('rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600', className)}>—</span>
  const s = SHOWN_STYLE[value]
  return (
    <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap text-white', s.bg, className)}>{s.label}</span>
  )
}

export function StageIcon({ status }: { status: StageStatus }) {
  const base = 'grid size-6 shrink-0 place-items-center rounded-full'
  switch (status) {
    case 'running':
      return <span className={cn(base, 'bg-zinc-100 text-zinc-600')}><Loader2 className="size-3.5 animate-spin" /></span>
    case 'passed':
      return <span className={cn(base, 'bg-emerald-600 text-white')}><Check className="size-3.5" strokeWidth={3} /></span>
    case 'warning':
      return <span className={cn(base, 'bg-amber-500 text-white')}><AlertTriangle className="size-3.5" strokeWidth={2.5} /></span>
    case 'failed':
      return <span className={cn(base, 'bg-red-600 text-white')}><X className="size-3.5" strokeWidth={3} /></span>
    default:
      return <span className={cn(base, 'border border-zinc-300 bg-white text-zinc-300')}><Circle className="size-2 fill-current" /></span>
  }
}

/** ✓ for a clean check, ! for Hold/Info, ✗ for something the vendor must fix. */
export function CheckIcon({ severity }: { severity: Severity | null }) {
  if (severity === 'REJECT') return <X className="mt-0.5 size-4 shrink-0 text-red-600" strokeWidth={2.5} />
  if (severity === 'HOLD') return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
  if (severity === 'INFO') return <Info className="mt-0.5 size-4 shrink-0 text-sky-600" />
  return <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" strokeWidth={2.5} />
}
