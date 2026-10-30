import type { ExtractedInvoice } from '@/lib/api'
import { fieldLabel, fieldValue } from '@/lib/format'
import type { FieldEvent } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

export const KEY_FIELDS = [
  'document_type', 'vendor_name', 'vendor_gstin', 'buyer_gstin', 'invoice_number', 'invoice_date', 'po_reference',
  'subtotal', 'cgst', 'sgst', 'igst', 'total_amount', 'bank_account',
]

function ConfidenceBar({ value, threshold }: { value: number; threshold: number }) {
  const low = value < threshold
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-10 overflow-hidden rounded-full bg-zinc-100">
        <div className={cn('h-full rounded-full', low ? 'bg-red-500' : 'bg-emerald-500')} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className={cn('w-8 text-right text-[11px] tabular-nums', low ? 'font-semibold text-red-600' : 'text-zinc-500')}>
        {Math.round(value * 100)}%
      </span>
    </div>
  )
}

/** Stage 2: what the AI read, with its own confidence (red below the threshold). */
export function ExtractedFields({ invoice, threshold }: { invoice: ExtractedInvoice; threshold: number }) {
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200">
      <table className="w-full text-sm">
        <tbody>
          {KEY_FIELDS.map((name) => {
            const f = invoice[name]
            if (!f) return null
            const absent = f.value === null || f.value === undefined || f.value === ''
            return (
              <tr key={name} className="border-b border-zinc-100 last:border-0">
                <td className="w-28 px-3 py-1.5 text-xs text-zinc-500">{fieldLabel(name)}</td>
                <td className={cn('px-3 py-1.5 font-medium', absent && 'font-normal text-zinc-400')}>
                  <span className="break-words">{absent ? 'not printed' : fieldValue(name, f.value)}</span>
                </td>
                <td className="px-3 py-1.5">{!absent && <ConfidenceBar value={f.confidence} threshold={threshold} />}</td>
              </tr>
            )
          })}
          <tr>
            <td className="px-3 py-1.5 text-xs text-zinc-500">Line items</td>
            <td className="px-3 py-1.5 font-medium" colSpan={2}>{invoice.line_items.length}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

const BADGE: Record<string, { text: (f: FieldEvent) => string; cls: string }> = {
  verified: { text: (f) => (f.source === 'ocr' ? '✓ OCR' : '✓ text layer'), cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  not_found: { text: () => '✗ not found on page', cls: 'bg-red-50 text-red-700 ring-red-200' },
  unavailable: { text: () => '— OCR unavailable', cls: 'bg-zinc-100 text-zinc-600 ring-zinc-200' },
  not_applicable: { text: () => 'not printed', cls: 'bg-white text-zinc-400 ring-zinc-200' },
}

/** Stage 3: each value looked up on the page. Click a row to jump to its box. */
export function VerifiedFields({ fields, selected, onSelect }: {
  fields: Record<string, FieldEvent>; selected: string | null; onSelect: (field: string) => void
}) {
  const rows = Object.values(fields)
  if (!rows.length) return <p className="text-sm text-zinc-500">Looking for each value on the page…</p>
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200">
      <table className="w-full text-sm">
        <tbody>
          {rows.map((f) => {
            const badge = BADGE[f.status] ?? BADGE.not_applicable
            const clickable = f.status === 'verified' || f.status === 'not_found'
            return (
              <tr
                key={f.field}
                onClick={() => clickable && onSelect(f.field)}
                className={cn('border-b border-zinc-100 last:border-0', clickable && 'cursor-pointer hover:bg-zinc-50',
                  selected === f.field && 'bg-emerald-50/60')}
              >
                <td className="w-28 px-3 py-1.5 text-xs text-zinc-500">{fieldLabel(f.field)}</td>
                <td className="px-3 py-1.5"><span className="break-words">{fieldValue(f.field, f.value)}</span></td>
                <td className="px-3 py-1.5 text-right">
                  <span className={cn('inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1', badge.cls)}>
                    {badge.text(f)}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
