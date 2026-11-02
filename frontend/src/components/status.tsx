/** Shared status visuals: decision colours (green Paid, amber Needs human verification, red Rejected, gray running/failed).
 *  The engine's codes stay APPROVE / HOLD / REJECT; these are the words people see (approving pays the invoice). */

import { AlertTriangle, Check, Circle, Info, Loader2, X } from 'lucide-react'

import type { Outcome, Severity } from '@/lib/api'
import type { StageStatus } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

export const OUTCOME_STYLE: Record<Outcome, { bg: string; text: string; ring: string; soft: string; label: string }> = {
  APPROVE: { bg: 'bg-emerald-600', text: 'text-emerald-700', ring: 'ring-emerald-200', soft: 'bg-emerald-50', label: 'Paid' },
  HOLD: { bg: 'bg-amber-500', text: 'text-amber-700', ring: 'ring-amber-200', soft: 'bg-amber-50', label: 'Needs human verification' },
  REJECT: { bg: 'bg-red-600', text: 'text-red-700', ring: 'ring-red-200', soft: 'bg-red-50', label: 'Rejected' },
}

export function DecisionPill({ outcome, className }: { outcome: Outcome | null; className?: string }) {
  if (!outcome) return <span className={cn('rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600', className)}>—</span>
  const s = OUTCOME_STYLE[outcome]
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

/** ✓ for a clean check, ! for Hold/Info, ✗ for Reject. */
export function CheckIcon({ severity }: { severity: Severity | null }) {
  if (severity === 'REJECT') return <X className="mt-0.5 size-4 shrink-0 text-red-600" strokeWidth={2.5} />
  if (severity === 'HOLD') return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
  if (severity === 'INFO') return <Info className="mt-0.5 size-4 shrink-0 text-sky-600" />
  return <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" strokeWidth={2.5} />
}
