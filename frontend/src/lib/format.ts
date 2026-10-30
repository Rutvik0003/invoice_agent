/** Formatting helpers: INR amounts, field labels, durations. */

const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })
const NUMBER = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

/** 123456 -> "₹1,23,456.00" */
export function inr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return INR.format(value)
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return NUMBER.format(value)
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return ''
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export const FIELD_LABELS: Record<string, string> = {
  document_type: 'Document type',
  vendor_name: 'Vendor',
  vendor_gstin: 'Vendor GSTIN',
  vendor_address: 'Vendor address',
  vendor_state: 'Vendor state',
  buyer_name: 'Buyer',
  buyer_gstin: 'Buyer GSTIN',
  invoice_number: 'Invoice number',
  invoice_date: 'Invoice date',
  po_reference: 'PO reference',
  subtotal: 'Subtotal',
  discount: 'Discount',
  other_charges: 'Other charges',
  cgst: 'CGST',
  sgst: 'SGST',
  igst: 'IGST',
  round_off: 'Round off',
  total_amount: 'Total',
  amount_in_words: 'Amount in words',
  bank_account: 'Bank account',
  bank_ifsc: 'IFSC',
  page_count: 'Pages',
}

export const MONEY_FIELDS = new Set(['subtotal', 'discount', 'other_charges', 'cgst', 'sgst', 'igst', 'round_off', 'total_amount'])

export function fieldLabel(name: string): string {
  const line = /^line_items\[(\d+)\]\.amount$/.exec(name)
  if (line) return `Line ${Number(line[1]) + 1} amount`
  return FIELD_LABELS[name] ?? name.replaceAll('_', ' ')
}

/** A field value as shown to people: money as ₹, document type in words. */
export function fieldValue(name: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number' && (MONEY_FIELDS.has(name) || name.startsWith('line_items'))) return inr(value)
  if (name === 'document_type') return String(value).replaceAll('_', ' ')
  if (name === 'page_count' && typeof value === 'number') return String(Math.round(value))
  return String(value)
}

/** NO_PO_CLEAR_MATCH -> "No PO clear match" */
export function humanize(code: string): string {
  const text = code.toLowerCase().replaceAll('_', ' ').replace(/\b(po|gst|ocr|ifsc)\b/g, (w) => w.toUpperCase())
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
