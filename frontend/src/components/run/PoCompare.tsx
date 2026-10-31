import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Loader2 } from 'lucide-react'
import { useState } from 'react'

import { api2, type PoComparison } from '@/lib/api2'
import { humanize, inr, num } from '@/lib/format'
import { cn } from '@/lib/utils'

type Line = NonNullable<PoComparison['comparison']>['lines'][number]

const ISSUE_TEXT: Record<string, string> = {
  not_on_po: 'Not on this PO',
  qty_exceeds_po: 'Quantity above what is open',
  price_over_tolerance: 'Price above tolerance',
}

const OPTION_LABEL: Record<string, string> = {
  matched: ' (this invoice’s PO)',
  quoted: ' (printed on the invoice)',
  suggested: ' (suggested)',
}

function Verdict({ line }: { line: Line }) {
  if (line.adjustment) return <span className="text-xs text-zinc-500">Discount / credit line</span>
  if (line.issues.length) {
    return (
      <div className="space-y-0.5">
        {line.issues.map((i) => <div key={i} className="flex items-center gap-1 text-xs font-medium text-red-700"><AlertTriangle className="size-3" />{ISSUE_TEXT[i]}</div>)}
      </div>
    )
  }
  if (line.price_status === 'within_tolerance') return <span className="text-xs text-amber-700">Price slightly above, within tolerance</span>
  if (line.price_status === 'below_po') return <span className="text-xs text-emerald-700">✓ Below PO price</span>
  return <span className="text-xs text-emerald-700">✓ Matches</span>
}

function priceDiff(line: Line): string | null {
  if (!line.po_line || !line.po_line.unit_price || line.price_status === 'match') return null
  const pct = ((line.unit_price - line.po_line.unit_price) / line.po_line.unit_price) * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
}

/** The invoice next to a purchase order, line by line, with the PO balance before and after this invoice. */
export function PoCompare({ runId }: { runId: string }) {
  const [po, setPo] = useState<string | undefined>(undefined)
  const data = useQuery({ queryKey: ['po-compare', runId, po ?? ''], queryFn: () => api2.poCompare(runId, po), placeholderData: (prev) => prev })
  if (data.isPending) return <div className="flex items-center gap-2 p-4 text-sm text-zinc-500"><Loader2 className="size-4 animate-spin" />Loading the PO…</div>
  if (data.isError) return <p className="p-4 text-sm text-red-700">{data.error.message}</p>
  const { options, option_reasons: why, selected, comparison: c } = data.data
  if (!options.length || !c) {
    return <p className="p-4 text-sm text-zinc-500">No purchase order to compare with: the vendor is not in the vendor master or has no open POs.</p>
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-zinc-500" htmlFor={`po-${runId}`}>Compare with</label>
        <select id={`po-${runId}`} value={selected ?? ''} onChange={(e) => setPo(e.target.value)}
                className="h-8 rounded-md border border-zinc-200 bg-white px-2 font-mono text-xs">
          {options.map((o) => <option key={o} value={o}>{o}{OPTION_LABEL[why[o]] ?? ''}</option>)}
        </select>
        {data.isFetching && <Loader2 className="size-3.5 animate-spin text-zinc-400" />}
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-700">{humanize(c.po.status)}</span>
        <span className="text-xs text-zinc-500">dated {new Date(c.po.po_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
        {!c.belongs_to_vendor && <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 ring-1 ring-red-200">belongs to vendor {c.po.vendor_id}</span>}
        {c.closed && <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 ring-1 ring-red-200">closed</span>}
      </div>

      {selected && why[selected] === 'other' && !po && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
          No PO is linked to this invoice, so this is just the first open PO of the vendor. Pick the right one above.
        </p>
      )}
      {c.lines.length > 0 && c.lines.every((l) => l.adjustment || l.issues.includes('not_on_po')) && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
          None of the invoice lines are items on {c.po.po_number}: this is probably not the right PO.
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-zinc-200">
        <table className="w-full min-w-[540px] text-sm">
          <thead className="bg-zinc-50 text-left text-[11px] tracking-wide text-zinc-500 uppercase">
            <tr>
              <th className="px-2.5 py-2 font-medium">Invoice line</th>
              <th className="px-2.5 py-2 text-right font-medium">Qty</th>
              <th className="px-2.5 py-2 text-right font-medium">Unit price</th>
              <th className="border-l border-zinc-200 px-2.5 py-2 font-medium">PO line</th>
              <th className="px-2.5 py-2 text-right font-medium">Open qty</th>
              <th className="px-2.5 py-2 text-right font-medium">PO price</th>
              <th className="px-2.5 py-2 font-medium">Check</th>
            </tr>
          </thead>
          <tbody>
            {c.lines.map((l) => {
              const diff = priceDiff(l)
              return (
                <tr key={l.index} className={cn('border-t border-zinc-100 align-top', l.issues.length > 0 && 'bg-red-50/40')}>
                  <td className="px-2.5 py-2"><div className="line-clamp-2" title={l.description}>{l.description}</div><div className="text-[11px] text-zinc-500">{inr(l.amount)}</div></td>
                  <td className={cn('px-2.5 py-2 text-right tabular-nums', l.issues.includes('qty_exceeds_po') && 'font-semibold text-red-700')}>{num(l.quantity)}</td>
                  <td className={cn('px-2.5 py-2 text-right tabular-nums', l.issues.includes('price_over_tolerance') && 'font-semibold text-red-700')}>
                    {inr(l.unit_price)}{diff && <div className="text-[11px] text-zinc-500">{diff} vs PO</div>}
                  </td>
                  {l.po_line ? <>
                    <td className="border-l border-zinc-200 px-2.5 py-2"><div className="line-clamp-2" title={l.po_line.description}><span className="font-mono text-[11px] text-zinc-400">#{l.po_line.line_no}</span> {l.po_line.description}</div></td>
                    <td className="px-2.5 py-2 text-right tabular-nums">{num(l.po_line.qty_remaining)}<div className="text-[11px] text-zinc-500">of {num(l.po_line.qty_ordered)} {l.po_line.unit}</div></td>
                    <td className="px-2.5 py-2 text-right tabular-nums">{inr(l.po_line.unit_price)}</td>
                  </> : <td colSpan={3} className="border-l border-zinc-200 px-2.5 py-2 text-xs text-zinc-400">{l.adjustment ? '—' : 'No matching line on this PO'}</td>}
                  <td className="px-2.5 py-2"><Verdict line={l} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-zinc-50 px-2.5 py-2 text-sm">
        <span>PO value <b className="tabular-nums">{inr(c.po.taxable_value)}</b></span>
        <span className="text-zinc-500">billed so far {inr(c.po.billed_value)}</span>
        <span className="flex items-center gap-1.5">
          open <b className="tabular-nums">{inr(c.totals.remaining_before)}</b>
          <ArrowRight className="size-3.5 text-zinc-400" />
          <b className={cn('tabular-nums', c.totals.overrun ? 'text-red-700' : c.totals.remaining_after < 0 ? 'text-amber-700' : 'text-zinc-900')}>{inr(c.totals.remaining_after)}</b>
          <span className="text-xs text-zinc-500">after this invoice ({inr(c.totals.this_invoice)} before tax)</span>
        </span>
        {c.totals.overrun && <span className="text-xs font-medium text-red-700">Over the PO value by more than the {inr(c.totals.tolerance)} tolerance</span>}
        {!c.totals.overrun && c.totals.remaining_after < 0 && <span className="text-xs text-amber-700">Slightly over the PO value, within the {inr(c.totals.tolerance)} tolerance</span>}
      </div>
      {c.po_lines_not_billed.length > 0 && (
        <p className="text-xs text-zinc-500">
          Not on this invoice: {c.po_lines_not_billed.map((l) => `#${l.line_no} ${l.description} (${num(l.qty_remaining)} ${l.unit} open)`).join(' · ')}
        </p>
      )}
    </div>
  )
}
