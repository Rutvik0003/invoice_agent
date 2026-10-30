/** A small Markdown renderer for the evaluation reports: headings, tables, lists, code blocks, bold, inline code. */

import type { ReactNode } from 'react'

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`') && p.endsWith('`')) return <code key={i} className="rounded bg-zinc-100 px-1 font-mono text-[0.85em]">{p.slice(1, -1)}</code>
    return p
  })
}

const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

export function Markdown({ text }: { text: string }) {
  const lines = text.split(/\r?\n/)
  const out: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const block: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) block.push(lines[i++])
      i++
      out.push(<pre key={out.length} className="my-2 overflow-x-auto rounded-md bg-zinc-50 p-3 text-xs whitespace-pre-wrap ring-1 ring-zinc-200">{block.join('\n')}</pre>)
      continue
    }
    if (/^#{1,3} /.test(line)) {
      const level = line.indexOf(' ')
      const cls = level === 1 ? 'mt-1 text-lg font-semibold' : level === 2 ? 'mt-5 text-base font-semibold' : 'mt-4 text-sm font-semibold'
      out.push(<div key={out.length} className={cls}>{inline(line.slice(level + 1))}</div>)
      i++
      continue
    }
    if (line.trim().startsWith('|') && lines[i + 1]?.trim().match(/^\|[\s:|-]+\|$/)) {
      const head = cells(line)
      const align = cells(lines[i + 1]).map((c) => (c.endsWith(':') ? 'right' : 'left'))
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(cells(lines[i++]))
      out.push(
        <div key={out.length} className="my-2 overflow-x-auto rounded-md ring-1 ring-zinc-200">
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 text-zinc-500"><tr>{head.map((h, k) => <th key={k} className="px-2.5 py-1.5 font-medium" style={{ textAlign: align[k] as 'left' | 'right' }}>{inline(h)}</th>)}</tr></thead>
            <tbody>{rows.map((r, j) => (
              <tr key={j} className="border-t border-zinc-100">{r.map((c, k) => <td key={k} className="px-2.5 py-1 tabular-nums" style={{ textAlign: align[k] as 'left' | 'right' }}>{inline(c)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>,
      )
      continue
    }
    if (/^\s*- /.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*- /.test(lines[i])) items.push(lines[i++].replace(/^\s*- /, ''))
      out.push(<ul key={out.length} className="my-1.5 list-disc space-y-0.5 pl-5 text-sm">{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</ul>)
      continue
    }
    if (line.trim()) out.push(<p key={out.length} className="my-1.5 text-sm leading-relaxed">{inline(line)}</p>)
    i++
  }
  return <div className="text-zinc-800">{out}</div>
}
