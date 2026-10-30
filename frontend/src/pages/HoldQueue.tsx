import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, Loader2, UserCheck, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { PageHeader } from '@/components/AppShell'
import { BoxCrop } from '@/components/BoxCrop'
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
const FIELD_CODES = new Set(['LOW_CONFIDENCE_FIELD', 'FIELD_NOT_VERIFIED'])

function primaryRole(item: HoldItem): string {
  const roles = item.routed_questions.map((q) => q.role)
  return [...roles].sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b))[0] ?? 'AP clerk'
}

export default function HoldQueue() {
  const [state, setState] = useState<'open' | 'resolved'>('open')
  const [role, setRole] = useState<string>('all')
  const holds = useQuery({ queryKey: ['holds', state], queryFn: () => api2.holds(state), refetchInterval: 15_000 })
  const items = holds.data?.items ?? []
  const roles = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const i of items) counts[primaryRole(i)] = (counts[primaryRole(i)] ?? 0) + 1
    return Object.entries(counts).sort((a, b) => ROLE_ORDER.indexOf(a[0]) - ROLE_ORDER.indexOf(b[0]))
  }, [items])
  const shown = items.filter((i) => role === 'all' || primaryRole(i) === role)
  const groups = ROLE_ORDER.map((r) => [r, shown.filter((i) => primaryRole(i) === r)] as const).filter(([, list]) => list.length)

  return (
    <div>
      <PageHeader
        title="Hold Queue"
        subtitle="Invoices the rules could not decide alone, grouped by who has to act. Every action needs a comment and is logged."
        actions={
          <div className="flex rounded-lg bg-zinc-100 p-1 text-sm">
            {(['open', 'resolved'] as const).map((s) => (
              <button key={s} type="button" onClick={() => setState(s)}
                      className={cn('rounded-md px-3 py-1', state === s ? 'bg-white font-medium shadow-sm' : 'text-zinc-600')}>
                {s === 'open' ? 'Open' : 'Resolved'}
              </button>
            ))}
          </div>
        }
      />
      <div className="space-y-5 px-8 py-6">
        <div className="flex flex-wrap gap-1.5">
          {[['all', items.length] as const, ...roles].map(([r, n]) => (
            <button key={r} type="button" onClick={() => setRole(r)}
                    className={cn('rounded-full px-3 py-1 text-sm ring-1', role === r ? 'bg-zinc-900 text-white ring-zinc-900' : 'bg-white text-zinc-700 ring-zinc-200 hover:ring-zinc-400')}>
              {r === 'all' ? 'All' : r} <span className="opacity-60">{n}</span>
            </button>
          ))}
        </div>
        {holds.isPending && <div className="h-40 animate-pulse rounded-xl bg-zinc-100" />}
        {!holds.isPending && !items.length && (
          <div className="rounded-xl border border-dashed border-zinc-300 p-12 text-center text-sm text-zinc-500">
            {state === 'open' ? 'Nothing on hold. Held invoices appear here with the question for the right person.' : 'No holds resolved yet.'}
          </div>
        )}
        {groups.map(([r, list]) => (
          <section key={r} className="space-y-3">
            <h2 className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{r} · {list.length}</h2>
            {list.map((item) => <HoldCard key={item.id} item={item} />)}
          </section>
        ))}
      </div>
    </div>
  )
}

function HoldCard({ item }: { item: HoldItem }) {
  const queryClient = useQueryClient()
  const codes = new Set(item.reasons.map((r) => r.code))
  const roles = [...new Set(item.routed_questions.map((q) => q.role))].sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b))
  const fieldReasons = item.reasons.filter((r) => r.code && FIELD_CODES.has(r.code) && r.evidence?.invoice_field)
  const [mode, setMode] = useState<'decide' | 'po' | 'confirm'>('decide')
  const [role, setRole] = useState(roles[0] ?? 'AP clerk')
  const [comment, setComment] = useState('')
  const [po, setPo] = useState(item.po_candidates[0]?.po_number ?? item.po_number ?? '')
  const [field, setField] = useState(fieldReasons[0]?.evidence.invoice_field ?? '')
  const extractedValue = field && item.extracted?.[field] ? item.extracted[field].value : null
  const [value, setValue] = useState(extractedValue != null ? String(extractedValue) : '')

  const act = useMutation({
    mutationFn: (body: { action: string; payload?: Record<string, unknown> }) =>
      api2.holdAction(item.id, { ...body, role, comment: comment.trim() }),
    onSuccess: () => {
      setComment('')
      queryClient.invalidateQueries({ queryKey: ['holds'] })
      queryClient.invalidateQueries({ queryKey: ['run', item.id] })
    },
  })
  const needComment = !comment.trim()

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
        <div className="flex flex-wrap gap-1">{roles.map((r) => <span key={r} className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-900">{r}</span>)}</div>
        <Link to={`/runs/${item.id}`} className="flex items-center gap-1 text-xs text-zinc-600 underline-offset-2 hover:underline">Open run <ExternalLink className="size-3" /></Link>
      </header>

      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-3">
          {item.routed_questions.map((q) => (
            <p key={q.role} className="text-sm leading-relaxed whitespace-pre-line text-zinc-800"><b className="text-amber-800">{q.role}: </b>{q.question}</p>
          ))}
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
          <ResolvedPanel item={item} />
        ) : (
          <div className="space-y-3 rounded-lg border border-zinc-200 p-4">
            <div className="flex gap-1 rounded-md bg-zinc-100 p-0.5 text-xs">
              {([['decide', 'Approve / Reject'], ['po', 'Assign PO'], ['confirm', 'Confirm value']] as const).map(([m, label]) => (
                <button key={m} type="button" onClick={() => setMode(m)}
                        disabled={(m === 'po' && ![...codes].some((c) => c && PO_CODES.has(c))) || (m === 'confirm' && !fieldReasons.length)}
                        className={cn('flex-1 rounded px-2 py-1 disabled:opacity-40', mode === m ? 'bg-white font-medium shadow-sm' : 'text-zinc-600')}>{label}</button>
              ))}
            </div>
            {mode === 'po' && (
              <div className="space-y-1.5">
                {item.po_candidates.map((c) => (
                  <label key={c.po_number} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm',
                    po === c.po_number ? 'border-zinc-900' : 'border-zinc-200')}>
                    <input type="radio" checked={po === c.po_number} onChange={() => setPo(c.po_number)} />
                    <span className="font-mono text-xs">{c.po_number}</span>
                    <span className="ml-auto text-xs text-zinc-500">match {Math.round(c.score * 100)}%</span>
                  </label>
                ))}
                <Input value={po} onChange={(e) => setPo(e.target.value)} placeholder="PO number, e.g. PO-2026-1201" className="font-mono text-xs" />
              </div>
            )}
            {mode === 'confirm' && (
              <div className="space-y-1.5">
                <select value={field} onChange={(e) => {
                  setField(e.target.value)
                  const v = item.extracted?.[e.target.value]?.value
                  setValue(v != null ? String(v) : '')
                }} className="h-9 w-full rounded-md border border-zinc-200 bg-white px-2 text-sm">
                  {[...new Set(fieldReasons.map((r) => r.evidence.invoice_field!))].map((f) => <option key={f} value={f}>{fieldLabel(f)}</option>)}
                </select>
                <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="The correct value as printed" />
                <p className="text-[11px] text-zinc-500">AI read: {fieldValue(field, extractedValue)}. Type what the document really says.</p>
              </div>
            )}
            <select value={role} onChange={(e) => setRole(e.target.value)} className="h-9 w-full rounded-md border border-zinc-200 bg-white px-2 text-sm" aria-label="Acting as">
              {ROLE_ORDER.map((r) => <option key={r} value={r}>Acting as: {r}</option>)}
            </select>
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (required): why you decided this" className="min-h-16 text-sm" />
            <div className="flex flex-wrap gap-2">
              {mode === 'decide' && <>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" disabled={needComment || act.isPending}
                        onClick={() => act.mutate({ action: 'approve' })}><Check />Approve</Button>
                <Button size="sm" variant="outline" className="border-red-300 text-red-700 hover:bg-red-50" disabled={needComment || act.isPending}
                        onClick={() => act.mutate({ action: 'reject' })}><X />Reject</Button>
              </>}
              {mode === 'po' && <Button size="sm" disabled={needComment || !po || act.isPending} onClick={() => act.mutate({ action: 'assign_po', payload: { po_number: po.trim() } })}>Assign PO</Button>}
              {mode === 'confirm' && <Button size="sm" disabled={needComment || !value || act.isPending} onClick={() => act.mutate({
                action: 'confirm_field',
                payload: { field, value: MONEY_FIELDS.has(field) ? Number(value.replace(/[₹,\s]|rs\.?/gi, '')) : value },
              })}>Confirm value</Button>}
              {act.isPending && <Loader2 className="size-4 animate-spin self-center text-zinc-400" />}
            </div>
            {act.isError && <p className="text-xs text-red-700">{act.error.message}</p>}
            {act.isSuccess && !item.resolved && <p className="text-xs text-emerald-700">Saved. {String(act.data.result.decision ?? 'The hold stays open until someone approves or rejects it.')}</p>}
            {item.hold_actions.length > 0 && (
              <div className="border-t border-zinc-100 pt-2 text-[11px] text-zinc-500">
                {item.hold_actions.map((a, i) => <div key={i}>{a.actor_role}: {a.action.replace('_', ' ')} · “{a.comment}”</div>)}
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  )
}

function ResolvedPanel({ item }: { item: HoldItem }) {
  return (
    <div className="space-y-2 rounded-lg bg-zinc-50 p-4">
      <div className={cn('text-sm font-semibold', item.decision === 'APPROVE' ? 'text-emerald-700' : 'text-red-700')}>
        {item.decision === 'APPROVE' ? 'Approved' : 'Rejected'} by a person
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
