import { Minus, Plus, ScanSearch } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { pageUrl } from '@/lib/api'
import { fieldLabel, fieldValue } from '@/lib/format'
import type { FieldEvent } from '@/lib/useRunEvents'
import { cn } from '@/lib/utils'

const ZOOMS = [0.75, 1, 1.25, 1.5, 2]

type Props = {
  runId: string
  pageCount: number
  fields: Record<string, FieldEvent>
  selected: string | null
  pulseKey: number
  onSelect: (field: string) => void
}

/** The invoice pages with Stage 3 boxes drawn on top: green = found on the page, red chip = AI value not found. */
export function PageViewer({ runId, pageCount, fields, selected, pulseKey, onSelect }: Props) {
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [loaded, setLoaded] = useState<Record<number, boolean>>({})
  const [showAllMissing, setShowAllMissing] = useState(false)
  const boxRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const all = Object.values(fields)
  const onPage = all.filter((f) => (f.status === 'verified' || f.status === 'cross_checked') && f.page === page && f.bbox)
  const missing = all.filter((f) => f.status === 'not_found')
  const unavailable = all.some((f) => f.status === 'unavailable')

  // jump to the selected field's page and bring its box into view
  useEffect(() => {
    if (!selected) return
    const field = fields[selected]
    if (field?.page && field.page !== page) setPage(field.page)
    const t = window.setTimeout(() => boxRefs.current[selected]?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 120)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, pulseKey])

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 bg-white px-4 py-2">
        <div className="flex items-center gap-1">
          {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => (
            <Button key={n} size="sm" variant={n === page ? 'default' : 'outline'} className="h-7 px-2.5 text-xs" onClick={() => setPage(n)}>
              Page {n}
            </Button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Button size="icon" variant="ghost" className="size-7" aria-label="Zoom out" disabled={zoom === ZOOMS[0]}
            onClick={() => setZoom(ZOOMS[Math.max(0, ZOOMS.indexOf(zoom) - 1)])}><Minus /></Button>
          <span className="w-11 text-center text-xs tabular-nums text-zinc-600">{Math.round(zoom * 100)}%</span>
          <Button size="icon" variant="ghost" className="size-7" aria-label="Zoom in" disabled={zoom === ZOOMS.at(-1)}
            onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(zoom) + 1)])}><Plus /></Button>
        </div>
      </div>

      {(missing.length > 0 || unavailable) && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-zinc-200 bg-white px-4 py-2 text-xs">
          {missing.length > 3 && !showAllMissing ? (
            <button type="button" onClick={() => setShowAllMissing(true)}
              className="rounded-md border border-dashed border-red-400 bg-red-50 px-2 py-0.5 font-medium text-red-700">
              ✗ {missing.length} AI values could not be found on the page · show
            </button>
          ) : (
            missing.map((f) => (
              <button key={f.field} type="button" onClick={() => onSelect(f.field)}
                className="rounded-md border border-dashed border-red-400 bg-red-50 px-2 py-0.5 font-medium text-red-700">
                ✗ {fieldLabel(f.field)}: AI value not found on page
              </button>
            ))
          )}
          {unavailable && <span className="rounded-md bg-zinc-100 px-2 py-0.5 text-zinc-600">— OCR unavailable: some values not verified</span>}
        </div>
      )}

      <div className="relative flex-1 overflow-auto bg-zinc-100 p-4">
        <div className="relative mx-auto bg-white shadow-sm ring-1 ring-zinc-200" style={{ width: `${zoom * 100}%` }}>
          <img
            key={`${runId}-${page}`}
            src={pageUrl(runId, page)}
            alt={`Invoice page ${page}`}
            className="block w-full select-none"
            draggable={false}
            onLoad={() => setLoaded((l) => ({ ...l, [page]: true }))}
          />
          {!loaded[page] && <div className="absolute inset-0 grid place-items-center text-sm text-zinc-400"><ScanSearch className="size-6 animate-pulse" /></div>}
          {loaded[page] && onPage.map((f) => {
            const [x0, y0, x1, y1] = f.bbox!
            const isLine = f.field.startsWith('line_items')
            const active = selected === f.field
            const confirmed = f.status === 'cross_checked'  // the master value printed here; the AI misread it
            return (
              <div
                key={active ? `${f.field}-${pulseKey}` : f.field}
                ref={(el) => { boxRefs.current[f.field] = el }}
                onClick={() => onSelect(f.field)}
                className={cn(
                  'group absolute cursor-pointer rounded-[2px] border-2 animate-in fade-in zoom-in-95 duration-300',
                  confirmed ? 'border-teal-500 bg-teal-500/15'
                    : isLine ? 'border-emerald-400/80 bg-emerald-400/10' : 'border-emerald-500 bg-emerald-500/15',
                  active && 'box-pulse z-10 border-emerald-600 bg-emerald-500/20',
                )}
                style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`,
                         margin: '-2px', boxSizing: 'content-box', padding: '1px' }}
              >
                <div className={cn(
                  'pointer-events-none absolute bottom-full left-0 mb-1 whitespace-nowrap rounded bg-zinc-900 px-1.5 py-0.5 text-[11px] text-white shadow',
                  active ? 'block' : 'hidden group-hover:block',
                )}>
                  {confirmed ? <>{fieldLabel(f.field)} · page shows {f.reference_value}<span className="text-zinc-400"> · AI read {fieldValue(f.field, f.value)}</span></>
                    : <>{fieldLabel(f.field)} · {fieldValue(f.field, f.value)}
                      <span className="text-zinc-400"> · found “{f.matched_text}” ({f.source === 'ocr' ? 'OCR' : 'text layer'})</span></>}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
