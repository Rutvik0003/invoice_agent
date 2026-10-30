import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { PageHeader } from '@/components/AppShell'
import { Input } from '@/components/ui/input'
import { api2, type PurchaseOrder, type Vendor } from '@/lib/api2'
import { inr, num } from '@/lib/format'
import { cn } from '@/lib/utils'

const VENDOR_STATUS: Record<string, string> = {
  approved: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  pending: 'bg-amber-50 text-amber-800 ring-amber-200',
  blocked: 'bg-red-50 text-red-700 ring-red-200',
}
const PO_STATUS: Record<string, string> = {
  open: 'bg-sky-50 text-sky-800 ring-sky-200',
  partially_billed: 'bg-amber-50 text-amber-800 ring-amber-200',
  closed: 'bg-zinc-100 text-zinc-600 ring-zinc-200',
}

const Badge = ({ text, cls }: { text: string; cls: string }) => (
  <span className={cn('inline-block rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ring-1', cls)}>{text.replace('_', ' ')}</span>
)

export default function Data() {
  const [tab, setTab] = useState<'pos' | 'vendors' | 'history'>('pos')
  const [query, setQuery] = useState('')
  const vendors = useQuery({ queryKey: ['vendors'], queryFn: api2.vendors })
  const vendorById = useMemo(() => Object.fromEntries((vendors.data ?? []).map((v) => [v.vendor_id, v])), [vendors.data])

  return (
    <div>
      <PageHeader title="Data" subtitle="The master data the rules check against. Approving an invoice updates the PO balances and the invoice history." />
      <div className="space-y-4 px-8 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex rounded-lg bg-zinc-100 p-1 text-sm">
            {([['pos', 'Purchase orders'], ['vendors', 'Vendors'], ['history', 'Invoice history']] as const).map(([k, label]) => (
              <button key={k} type="button" onClick={() => setTab(k)} className={cn('rounded-md px-3 py-1', tab === k ? 'bg-white font-medium shadow-sm' : 'text-zinc-600')}>{label}</button>
            ))}
          </div>
          <div className="relative min-w-64 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-zinc-400" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search…" className="pl-8" />
          </div>
        </div>
        {tab === 'vendors' && <Vendors vendors={vendors.data ?? []} query={query} />}
        {tab === 'pos' && <PurchaseOrders vendorById={vendorById} query={query} />}
        {tab === 'history' && <History vendorById={vendorById} query={query} />}
      </div>
    </div>
  )
}

function Vendors({ vendors, query }: { vendors: Vendor[]; query: string }) {
  const q = query.toLowerCase()
  const rows = vendors.filter((v) => `${v.vendor_id} ${v.legal_name} ${v.trade_name} ${v.gstin} ${v.state} ${v.category} ${v.status}`.toLowerCase().includes(q))
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 text-left text-[11px] tracking-wide text-zinc-500 uppercase">
          <tr>{['ID', 'Vendor', 'GSTIN', 'State', 'Category', 'Bank account', 'Terms', 'Status'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((v) => (
            <tr key={v.vendor_id} className="border-t border-zinc-100">
              <td className="px-3 py-2 font-mono text-xs">{v.vendor_id}</td>
              <td className="px-3 py-2"><div>{v.legal_name}</div>{v.trade_name !== v.legal_name && <div className="text-xs text-zinc-500">trades as {v.trade_name}</div>}</td>
              <td className="px-3 py-2 font-mono text-xs">{v.gstin}</td>
              <td className="px-3 py-2 text-xs">{v.state} ({v.state_code})</td>
              <td className="px-3 py-2 text-xs">{v.category.replaceAll('_', ' ')}</td>
              <td className="px-3 py-2 text-xs"><div className="font-mono">{v.bank_account}</div><div className="text-zinc-500">{v.bank_name} · {v.ifsc}</div></td>
              <td className="px-3 py-2 text-xs">{v.payment_terms_days} days</td>
              <td className="px-3 py-2"><Badge text={v.status} cls={VENDOR_STATUS[v.status]} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PurchaseOrders({ vendorById, query }: { vendorById: Record<string, Vendor>; query: string }) {
  const pos = useQuery({ queryKey: ['pos'], queryFn: () => api2.pos() })
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [limit, setLimit] = useState(40)
  const q = query.toLowerCase()
  const rows = (pos.data ?? []).filter((p) => (!status || p.status === status)
    && `${p.po_number} ${p.vendor_id} ${vendorById[p.vendor_id]?.legal_name ?? ''}`.toLowerCase().includes(q))
  return (
    <div className="space-y-2">
      <div className="flex gap-1.5 text-sm">
        {[['', 'All'], ['open', 'Open'], ['partially_billed', 'Partially billed'], ['closed', 'Closed']].map(([v, t]) => (
          <button key={v} type="button" onClick={() => setStatus(v)}
                  className={cn('rounded-full px-3 py-1 ring-1', status === v ? 'bg-zinc-900 text-white ring-zinc-900' : 'bg-white text-zinc-700 ring-zinc-200')}>{t}</button>
        ))}
        <span className="ml-auto self-center text-xs text-zinc-500">{rows.length} POs · values before tax</span>
      </div>
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        {pos.isPending && <div className="h-40 animate-pulse bg-zinc-50" />}
        {rows.slice(0, limit).map((p) => <PORow key={p.po_number} po={p} vendor={vendorById[p.vendor_id]} open={open === p.po_number}
                                                 onToggle={() => setOpen(open === p.po_number ? null : p.po_number)} />)}
        {rows.length > limit && (
          <button type="button" onClick={() => setLimit(limit + 60)} className="w-full border-t border-zinc-100 py-2 text-sm text-zinc-600 hover:bg-zinc-50">
            Show more ({rows.length - limit} left)
          </button>
        )}
      </div>
    </div>
  )
}

function PORow({ po, vendor, open, onToggle }: { po: PurchaseOrder; vendor?: Vendor; open: boolean; onToggle: () => void }) {
  return (
    <div className="border-b border-zinc-100 last:border-0">
      <button type="button" onClick={onToggle} className="grid w-full grid-cols-[18px_120px_minmax(0,1fr)_110px_220px_110px] items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-zinc-50">
        <ChevronRight className={cn('size-4 text-zinc-400 transition-transform', open && 'rotate-90')} />
        <span className="font-mono text-xs">{po.po_number}</span>
        <span className="truncate">{vendor?.legal_name ?? po.vendor_id} <span className="text-xs text-zinc-400">{po.po_date}</span></span>
        <span className="text-right tabular-nums">{inr(po.taxable_value)}</span>
        <span>
          <span className="flex justify-between text-[11px] text-zinc-500"><span>billed {inr(po.billed_value)}</span><span>{po.billed_pct}%</span></span>
          <span className="mt-1 block h-1.5 rounded-full bg-zinc-100">
            <span className={cn('block h-1.5 rounded-full', po.billed_pct >= 100 ? 'bg-zinc-500' : 'bg-emerald-500')} style={{ width: `${Math.min(100, po.billed_pct)}%` }} />
          </span>
        </span>
        <span className="text-right"><Badge text={po.status} cls={PO_STATUS[po.status]} /></span>
      </button>
      {open && (
        <div className="grid gap-4 bg-zinc-50/60 px-10 pt-1 pb-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500"><tr><th className="py-1 font-medium">Line</th><th className="py-1 text-right font-medium">Ordered</th>
              <th className="py-1 text-right font-medium">Billed</th><th className="py-1 text-right font-medium">Left</th><th className="py-1 text-right font-medium">Unit price</th><th className="py-1 text-right font-medium">GST</th></tr></thead>
            <tbody>{po.lines.map((l) => (
              <tr key={l.line_no} className="border-t border-zinc-200/70">
                <td className="py-1 pr-2">{l.line_no}. {l.description}</td>
                <td className="py-1 text-right tabular-nums">{num(l.qty_ordered)} {l.unit}</td>
                <td className="py-1 text-right tabular-nums">{num(l.qty_billed)}</td>
                <td className="py-1 text-right tabular-nums">{num(l.qty_remaining)}</td>
                <td className="py-1 text-right tabular-nums">{inr(l.unit_price)}</td>
                <td className="py-1 text-right tabular-nums">{l.gst_rate}%</td>
              </tr>))}</tbody>
          </table>
          <div>
            <div className="mb-1 text-xs font-medium text-zinc-500">Invoices billed against this PO</div>
            {po.invoices.length ? po.invoices.map((i) => (
              <div key={i.history_id} className="flex justify-between border-t border-zinc-200/70 py-1 text-xs">
                <span><span className="font-mono">{i.invoice_number}</span> <span className="text-zinc-500">{i.invoice_date}{i.history_id.startsWith('R-') ? ' · approved in a run' : ''}</span></span>
                <span className="tabular-nums">{inr(i.taxable_value)}</span>
              </div>
            )) : <p className="text-xs text-zinc-400">None yet.</p>}
          </div>
        </div>
      )}
    </div>
  )
}

function History({ vendorById, query }: { vendorById: Record<string, Vendor>; query: string }) {
  const history = useQuery({ queryKey: ['history'], queryFn: api2.history })
  const q = query.toLowerCase()
  const rows = (history.data ?? []).filter((h) => `${h.invoice_number} ${h.vendor_id} ${vendorById[h.vendor_id]?.legal_name ?? ''} ${h.po_number ?? ''}`.toLowerCase().includes(q))
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 text-left text-[11px] tracking-wide text-zinc-500 uppercase">
          <tr>{['Date', 'Invoice', 'Vendor', 'PO', 'Before tax', 'Total', 'Status'].map((h) => <th key={h} className={cn('px-3 py-2 font-medium', ['Before tax', 'Total'].includes(h) && 'text-right')}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 300).map((h) => (
            <tr key={h.history_id} className={cn('border-t border-zinc-100', h.from_run && 'bg-emerald-50/50')}>
              <td className="px-3 py-1.5 text-xs whitespace-nowrap">{h.invoice_date}</td>
              <td className="px-3 py-1.5 font-mono text-xs">{h.invoice_number}{h.from_run && <span className="ml-1.5 rounded bg-emerald-100 px-1 font-sans text-[10px] text-emerald-800">from a run</span>}</td>
              <td className="max-w-64 truncate px-3 py-1.5">{vendorById[h.vendor_id]?.legal_name ?? h.vendor_id}</td>
              <td className="px-3 py-1.5 font-mono text-xs">{h.po_number ?? '—'}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{inr(h.taxable_value)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{inr(h.total_amount)}</td>
              <td className="px-3 py-1.5 text-xs">{h.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 300 && <p className="border-t border-zinc-100 p-2 text-center text-xs text-zinc-500">Showing 300 of {rows.length}. Search to narrow down.</p>}
    </div>
  )
}
