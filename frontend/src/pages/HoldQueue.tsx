import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, CornerUpLeft, ExternalLink, Loader2, Scale, UserCheck } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/AppShell'
import { BoxCrop } from '@/components/BoxCrop'
import { PoCompare } from '@/components/run/PoCompare'
import { VendorEmail } from '@/components/run/VendorEmail'
import { CheckIcon } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api2, type HoldItem } from '@/lib/api2'
import { fieldLabel, fieldValue, humanize, inr, MONEY_FIELDS, timeAgo } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const ROLE_ORDER = ['Finance controller', 'Procurement', 'Tax team', 'Buyer', 'AP clerk']
const PO_CODES = new Set(['PO_INFERRED', 'PO_AMBIGUOUS', 'PO_NOT_FOUND', 'PO_VENDOR_MISMATCH'])
const FIELD_CODES = new Set(['LOW_CONFIDENCE_FIELD', 'FIELD_NOT_VERIFIED', 'MISSING_REQUIRED_FIELD'])
const DUPLICATE_CODES = new Set(['DUPLICATE_FILE', 'DUPLICATE_INVOICE_NUMBER', 'POSSIBLE_DUPLICATE'])

/** The fields a person can confirm or fill in: doubtful values, and required values missing from the invoice. */
function confirmableFields(item: HoldItem): string[] {
  const fields = item.reasons
    .filter((r) => r.code && FIELD_CODES.has(r.code) && r.evidence?.invoice_field)
    .flatMap((r) => r.evidence.invoice_field!.split(',').map((f) => f.trim()))
  return [...new Set(fields)].filter((f) => f !== 'line_items')
}

function primaryRole(item: HoldItem): string {
  const roles = item.routed_questions.map((q) => q.role)
  return [...roles].sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b))[0] ?? 'AP clerk'
}

export default function HoldQueue() {
  const [state, setState] = useState<'open' | 'resolved'>('open')
  const holds = useQuery({ queryKey: ['holds', state], queryFn: () => api2.holds(state), refetchInterval: 15_000 })
  const items = holds.data?.items ?? []

  return (
    <div>
      <PageHeader
        title="Verification queue"
        subtitle="Every invoice the rules would not pay on their own. Check the points listed, then approve and pay it, or send the vendor a mail asking for a corrected bill."
        actions={
          <div className="flex rounded-lg bg-zinc-100 p-1 text-sm">
            {(['open', 'resolved'] as const).map((s) => (
              <button key={s} type="button" onClick={() => setState(s)}
                      className={cn('rounded-md px-3 py-1', state === s ? 'bg-white font-medium shadow-sm' : 'text-zinc-600')}>
                {s === 'open' ? `To check${state === 'open' && items.length ? ` (${items.length})` : ''}` : 'Done'}
              </button>
            ))}
          </div>
        }
      />
      <div className="space-y-4 px-8 py-6">
        {holds.isPending && <div className="h-40 animate-pulse rounded-xl bg-zinc-100" />}
        {!holds.isPending && !items.length && (
          <div className="rounded-xl border border-dashed border-zinc-300 p-12 text-center text-sm text-zinc-500">
            {state === 'open' ? 'Nothing needs human verification right now.' : 'No invoices checked by a person yet.'}
          </div>
        )}
        {items.map((item) => <HoldCard key={item.id} item={item} />)}
      </div>
    </div>
  )
}

function HoldCard({ item }: { item: HoldItem }) {
  const queryClient = useQueryClient()
  const codes = new Set(item.reasons.map((r) => r.code))
  const role = primaryRole(item)
  const fields = confirmableFields(item)
  const needsPo = [...codes].some((c) => c && PO_CODES.has(c))
  const [comparing, setComparing] = useState(false)
  const [comment, setComment] = useState('')
  const [message, setMessage] = useState('')
  const [payAgain, setPayAgain] = useState(false)
  const [po, setPo] = useState(item.po_candidates[0]?.po_number ?? item.po_number ?? '')
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((f) => {
    const v = item.extracted?.[f]?.value
    return [f, v != null ? String(v) : '']
  })))

  const act = useMutation({
    mutationFn: (action: 'approve' | 'request_changes') => {
      // what the person checked travels with the approval: the PO, and every value they confirmed or corrected
      const checked = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim())
        .map(([f, v]) => [f, MONEY_FIELDS.has(f) ? Number(v.replace(/[₹,\s]|rs\.?/gi, '')) : v.trim()]))
      const payload = action === 'approve'
        ? { ...(needsPo && po.trim() ? { po_number: po.trim() } : {}), fields: checked, ...(payAgain ? { pay_again: true } : {}) }
        : { message: message.trim() }
      return api2.holdAction(item.id, { action, role, comment: comment.trim(), payload })
    },
    onSuccess: () => {
      setComment('')
      queryClient.invalidateQueries({ queryKey: ['holds'] })
      queryClient.invalidateQueries({ queryKey: ['run', item.id] })
    },
  })
  const needComment = !comment.trim()
  // paying twice needs a tick: shown for a duplicate, or once the server says it was already paid
  const askPayAgain = [...codes].some((c) => c && DUPLICATE_CODES.has(c)) || (act.isError && act.error.message.includes('Pay it again'))

  // evidence with a crop of the page where the AI's value was found
  const evidence = item.reasons.filter((r) => r.code).map((r) => {
    const name = r.evidence?.invoice_field ?? undefined
    const box = name ? item.verification_fields[name] : undefined
    return { reason: r, box: box?.status === 'verified' && box.bbox && box.page ? box : undefined, missing: box?.status === 'not_found' }
  })

  return (
    <article className={cn('overflow-hidden rounded-xl border bg-white', item.resolved ? 'border-zinc-200' : 'border-amber-200')}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-zinc-100 px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{item.vendor_name ?? 'Unknown vendor'} · {item.invoice_number ?? 'no invoice number'}</div>
          <div className="text-xs text-zinc-500">{inr(item.total_amount)} · {item.po_number ?? 'no PO'} · {item.file_name} · {timeAgo(item.created_at)}</div>
        </div>
        {item.vendor_must_fix && <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 ring-1 ring-red-200">Vendor must fix the bill</span>}
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-900">Usually checked by: {role}</span>
        <Button size="sm" variant={comparing ? 'secondary' : 'outline'} onClick={() => setComparing(!comparing)} disabled={!item.vendor_id}
                title={item.vendor_id ? undefined : 'The vendor is not in the vendor master, so there is no PO to compare with'}>
          <Scale />Compare with PO<ChevronDown className={cn('transition-transform', comparing && 'rotate-180')} />
        </Button>
        <Link to={`/runs/${item.id}`} className="flex items-center gap-1 text-xs text-zinc-600 underline-offset-2 hover:underline">Open run <ExternalLink className="size-3" /></Link>
      </header>
      {comparing && <div className="border-b border-zinc-100 bg-zinc-50/50 p-5"><PoCompare runId={item.id} /></div>}

      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-3">
          <div className="space-y-2">
            {evidence.map(({ reason, box, missing }, i) => (
              <div key={i} className="flex gap-3 rounded-lg bg-zinc-50 p-2.5">
                <CheckIcon severity={reason.severity} />
                <div className="min-w-0 flex-1 text-sm">
                  <div className="leading-snug">{reason.message}</div>
                  {missing && <div className="mt-1 text-xs text-red-700">This value was not found on the page.</div>}
                </div>
                {box && <BoxCrop runId={item.id} page={box.page!} bbox={box.bbox as [number, number, number, number]} width={200} />}
              </div>
            ))}
          </div>
        </div>

        {item.resolved ? (
          <div className="space-y-3"><ResolvedPanel item={item} /><VendorEmail runId={item.id} compact previewOnly /></div>
        ) : (
          <div className="space-y-3">
          <div className="space-y-4 rounded-lg border border-zinc-200 p-4">
            <h3 className="text-sm font-semibold">Your check</h3>
            {needsPo && (
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-zinc-700">1. Which purchase order is this invoice for?</div>
                {item.po_candidates.map((c) => (
                  <label key={c.po_number} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm',
                    po === c.po_number ? 'border-zinc-900' : 'border-zinc-200')}>
                    <input type="radio" checked={po === c.po_number} onChange={() => setPo(c.po_number)} />
                    <span className="font-mono text-xs">{c.po_number}</span>
                    <span className="ml-auto text-xs text-zinc-500">match {Math.round(c.score * 100)}%</span>
                  </label>
                ))}
                <Input value={po} onChange={(e) => setPo(e.target.value)} placeholder="or type a PO number, e.g. PO-2026-1201" className="font-mono text-xs" />
              </div>
            )}
            {fields.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-zinc-700">
                  {needsPo ? '2. ' : '1. '}Compare with the invoice; correct anything the AI read wrongly
                </div>
                {fields.map((f) => (
                  <label key={f} className="block">
                    <span className="text-[11px] text-zinc-500">{fieldLabel(f)} · AI read: {fieldValue(f, item.extracted?.[f]?.value ?? null)}</span>
                    <Input value={values[f] ?? ''} onChange={(e) => setValues({ ...values, [f]: e.target.value })}
                           placeholder="as printed on the invoice" className="mt-0.5 h-8 text-sm" />
                  </label>
                ))}
              </div>
            )}
            {!needsPo && !fields.length && (
              <p className="text-xs text-zinc-600">Read the points on the left (open “Compare with PO” if it helps), then decide.</p>
            )}
            {askPayAgain && (
              <label className="flex items-start gap-2 rounded-md bg-red-50 px-2.5 py-2 text-xs text-red-800 ring-1 ring-red-200">
                <input type="checkbox" className="mt-0.5" checked={payAgain} onChange={(e) => setPayAgain(e.target.checked)} />
                <span><b>Pay it again.</b> This invoice looks already paid; tick only if paying it a second time is really right.</span>
              </label>
            )}
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)}
                      placeholder="Note for the audit trail (required), e.g. “Price agreed by phone with the vendor”" className="min-h-14 text-sm" />
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" disabled={needComment || act.isPending || (needsPo && !po.trim())}
                      onClick={() => act.mutate('approve')}><Check />Approve &amp; pay</Button>
              <Button size="sm" variant={item.vendor_must_fix ? 'default' : 'outline'} disabled={needComment || act.isPending}
                      onClick={() => act.mutate('request_changes')}><CornerUpLeft />Send mail for changes</Button>
              {act.isPending && <Loader2 className="size-4 animate-spin text-zinc-400" />}
              <span className="ml-auto text-[11px] text-zinc-400">logged as {role}</span>
            </div>
            <details className="text-xs text-zinc-600">
              <summary className="cursor-pointer">Add a line for the vendor (optional)</summary>
              <Textarea value={message} onChange={(e) => setMessage(e.target.value)} className="mt-1.5 min-h-12 text-sm"
                        placeholder="Added to the mail, e.g. “Please also quote our PO number.”" />
            </details>
            {act.isError && <p className="text-xs text-red-700">{act.error.message}</p>}
            {item.hold_actions.length > 0 && (
              <div className="border-t border-zinc-100 pt-2 text-[11px] text-zinc-500">
                {item.hold_actions.map((a, i) => <div key={i}>{a.actor_role}: {a.action.replace('_', ' ')} · “{a.comment}”</div>)}
              </div>
            )}
          </div>
          <VendorEmail runId={item.id} compact previewOnly />
          </div>
        )}
      </div>
    </article>
  )
}

function ResolvedPanel({ item }: { item: HoldItem }) {
  return (
    <div className="space-y-2 rounded-lg bg-zinc-50 p-4">
      <div className={cn('text-sm font-semibold', item.decision === 'APPROVE' ? 'text-emerald-700' : 'text-slate-700')}>
        {item.decision === 'APPROVE' ? 'Approved and paid by a person' : 'A person asked the vendor for changes'}
      </div>
      <ol className="space-y-2">
        {item.hold_actions.map((a, i) => (
          <li key={i} className="flex gap-2 text-sm">
            <UserCheck className="mt-0.5 size-4 shrink-0 text-zinc-400" />
            <div>
              <div><b>{a.actor_role}</b> · {humanize(a.action)} <span className="text-xs text-zinc-500">{new Date(a.created_at).toLocaleString('en-IN')}</span></div>
              <div className="text-zinc-700">“{a.comment}”</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
