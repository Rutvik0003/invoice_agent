/** Small dashboard charts. Decision colours are status colours (green/amber/red) and always carry a label. */

import { useState } from 'react'

import type { Outcome } from '@/lib/api'
import { humanize } from '@/lib/format'

const OUTCOMES: Outcome[] = ['APPROVE', 'HOLD', 'REJECT']
const FILL: Record<Outcome, string> = { APPROVE: '#059669', HOLD: '#f59e0b', REJECT: '#dc2626' }
const LABEL: Record<Outcome, string> = { APPROVE: 'Paid', HOLD: 'Needs human verification', REJECT: 'Rejected' }

type DayRow = { date: string; decision: Outcome; count: number }

function lastDays(rows: DayRow[], days: number): string[] {
  const end = rows.length ? new Date(rows.at(-1)!.date) : new Date()
  const today = new Date()
  const last = end > today ? end : today
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(last)
    d.setDate(d.getDate() - (days - 1 - i))
    return d.toISOString().slice(0, 10)
  })
}

/** Stacked bars: decisions per day (last 14 days). */
export function DecisionsByDay({ rows }: { rows: DayRow[] }) {
  const [hover, setHover] = useState<{ date: string; decision: Outcome; count: number; x: number; y: number } | null>(null)
  const dates = lastDays(rows, 14)
  const byDate = Object.fromEntries(dates.map((d) => [d, { APPROVE: 0, HOLD: 0, REJECT: 0 } as Record<Outcome, number>]))
  for (const r of rows) if (byDate[r.date]) byDate[r.date][r.decision] += r.count
  const max = Math.max(1, ...dates.map((d) => OUTCOMES.reduce((s, o) => s + byDate[d][o], 0)))
  const W = 560, H = 150, padL = 26, padB = 20, gap = 2
  const band = (W - padL) / dates.length
  const barW = Math.min(22, band * 0.62)
  const y = (v: number) => (H - padB) * (1 - v / max)
  const ticks = max <= 4 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max]

  return (
    <div className="relative">
      <div className="mb-2 flex gap-4 text-xs text-zinc-600">
        {OUTCOMES.map((o) => (
          <span key={o} className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: FILL[o] }} />{LABEL[o]}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Decisions per day, last 14 days">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W} y1={y(t)} y2={y(t)} stroke="#e4e4e7" strokeWidth={1} />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={9} fill="#71717a">{t}</text>
          </g>
        ))}
        {dates.map((d, i) => {
          const cx = padL + band * i + band / 2
          let acc = 0
          const total = OUTCOMES.reduce((s, o) => s + byDate[d][o], 0)
          return (
            <g key={d}>
              {OUTCOMES.map((o) => {
                const v = byDate[d][o]
                if (!v) return null
                const top = y(acc + v)
                const height = Math.max(1, y(acc) - top - (acc + v < total ? gap : 0))
                acc += v
                const isTop = acc === total
                return (
                  <rect key={o} x={cx - barW / 2} y={top} width={barW} height={height} rx={isTop ? 3 : 0} fill={FILL[o]}
                        onMouseEnter={() => setHover({ date: d, decision: o, count: v, x: cx, y: top })}
                        onMouseLeave={() => setHover(null)} />
                )
              })}
              {(i % 2 === 0 || dates.length <= 7) && (
                <text x={cx} y={H - 5} textAnchor="middle" fontSize={9} fill="#71717a">
                  {new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute rounded-md bg-zinc-900 px-2 py-1 text-[11px] whitespace-nowrap text-white shadow"
             style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100}%`, transform: 'translate(-50%, -110%)' }}>
          {new Date(hover.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} · {LABEL[hover.decision]}: {hover.count}
        </div>
      )}
      {!rows.length && <p className="absolute inset-0 grid place-items-center text-sm text-zinc-400">No runs yet</p>}
    </div>
  )
}

/** Horizontal bars for the most frequent reason codes (one series, so no legend; values labelled). */
export function ReasonBars({ rows }: { rows: [string, number][] }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-zinc-400">No reasons yet</p>
  const max = Math.max(...rows.map(([, n]) => n))
  return (
    <ul className="space-y-2">
      {rows.map(([code, n]) => (
        <li key={code} className="group" title={`${code}: ${n}`}>
          <div className="mb-0.5 flex justify-between text-xs">
            <span className="truncate text-zinc-700">{humanize(code)}</span>
            <span className="ml-2 tabular-nums text-zinc-500">{n}</span>
          </div>
          <div className="h-2 rounded-full bg-zinc-100">
            <div className="h-2 rounded-full bg-zinc-700 transition-colors group-hover:bg-zinc-900" style={{ width: `${(n / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  )
}
