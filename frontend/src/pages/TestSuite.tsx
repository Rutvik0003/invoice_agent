import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Clock, Loader2, Play, X } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/AppShell'
import { Markdown } from '@/components/Markdown'
import { DecisionPill } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { api2, type ReportKind } from '@/lib/api2'
import { humanize } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const REPORT_TABS: [ReportKind, string][] = [
  ['rules', 'Rules (all invoices)'],
  ['verification', 'Verification (no AI)'],
  ['extraction_gemini', 'Extraction · Gemini'],
  ['extraction_groq', 'Extraction · Groq'],
]

export default function TestSuite() {
  const queryClient = useQueryClient()
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  const suite = useQuery({
    queryKey: ['suite'],
    queryFn: api2.suite,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1000 : false),
  })
  const reports = useQuery({ queryKey: ['reports'], queryFn: api2.reports })
  const [model, setModel] = useState<string | null>(null)
  const [useCache, setUseCache] = useState(true)
  const [delay, setDelay] = useState(13)
  const [tab, setTab] = useState<ReportKind>('rules')
  const chosen = model ?? config.data?.default_model ?? 'gemini'
  const start = useMutation({
    mutationFn: () => api2.startSuite({ model: chosen, use_cache: useCache, delay_s: delay }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['suite'] }),
  })
  const s = suite.data
  const running = s?.status === 'running'
  const total = s?.total ?? 12

  return (
    <div>
      <PageHeader title="Test Suite & Evaluation" subtitle="Run the 12 golden invoices end to end, sandboxed from the demo ledger, and read the saved evaluation reports." />
      <div className="space-y-6 px-8 py-6">
        <section className="rounded-xl border border-zinc-200 bg-white">
          <div className="flex flex-wrap items-end gap-4 border-b border-zinc-100 p-5">
            <div>
              <div className="mb-1 text-xs text-zinc-500">Model</div>
              <select value={chosen} onChange={(e) => setModel(e.target.value)} disabled={running}
                      className="h-9 rounded-md border border-zinc-200 bg-white px-2 text-sm">
                {(config.data?.models ?? []).map((m) => <option key={m.id} value={m.id} disabled={!m.configured}>{m.label}</option>)}
              </select>
            </div>
            <label className="flex items-center gap-2 pb-1.5 text-sm" title="Reuse earlier readings of the same files: saves free-tier quota.">
              <Switch checked={useCache} onCheckedChange={setUseCache} disabled={running} />Use cached extractions
            </label>
            <div>
              <div className="mb-1 text-xs text-zinc-500">Pause after each live model call</div>
              <div className="flex items-center gap-1.5">
                <Input type="number" min={0} max={120} value={delay} onChange={(e) => setDelay(Number(e.target.value))} className="h-9 w-20" disabled={running} />
                <span className="text-sm text-zinc-500">s</span>
              </div>
            </div>
            <Button className="ml-auto" disabled={running || start.isPending} onClick={() => start.mutate()}>
              {running || start.isPending ? <Loader2 className="animate-spin" /> : <Play />}Run golden test suite
            </Button>
          </div>
          {start.isError && <p className="px-5 pt-3 text-sm text-red-700">{start.error.message}</p>}

          {s && s.status !== 'never_run' ? (
            <div className="p-5">
              <div className="mb-4 flex flex-wrap items-center gap-4">
                <div className="text-3xl font-semibold tabular-nums">{s.passed ?? 0}<span className="text-lg text-zinc-400">/{total}</span></div>
                <div className="min-w-48 flex-1">
                  <div className="mb-1 flex justify-between text-xs text-zinc-500">
                    <span>{running ? `Running ${s.done ?? 0} of ${total}…` : `Finished · ${s.model === 'groq' ? 'Groq' : 'Gemini'}${s.use_cache ? ' · cached extractions allowed' : ''}`}</span>
                    {running && s.next_call_in_s != null && s.next_call_in_s > 0 && (
                      <span className="flex items-center gap-1 text-amber-700"><Clock className="size-3" />next model call in {s.next_call_in_s}s (free-tier pacing)</span>
                    )}
                  </div>
                  <div className="h-2 rounded-full bg-zinc-100">
                    <div className="h-2 rounded-full bg-zinc-800 transition-all" style={{ width: `${((s.done ?? 0) / total) * 100}%` }} />
                  </div>
                </div>
              </div>
              <div className="overflow-hidden rounded-lg ring-1 ring-zinc-200">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-50 text-left text-[11px] tracking-wide text-zinc-500 uppercase">
                    <tr><th className="px-3 py-2 font-medium">Case</th><th className="px-3 py-2 font-medium">Expected</th><th className="px-3 py-2 font-medium">Actual</th>
                      <th className="px-3 py-2 font-medium">Reason codes</th><th className="px-3 py-2 text-center font-medium">Result</th></tr>
                  </thead>
                  <tbody>
                    {s.items.map((it) => (
                      <tr key={it.sample_id} className="border-t border-zinc-100 align-top">
                        <td className="px-3 py-2">
                          <div className="font-mono text-xs">{it.sample_id}</div>
                          <div className="text-xs text-zinc-500">{humanize(it.scenario)}</div>
                        </td>
                        <td className="px-3 py-2"><DecisionPill outcome={it.expected} /></td>
                        <td className="px-3 py-2">
                          {it.status === 'running' ? <Loader2 className="size-4 animate-spin text-zinc-400" />
                            : it.status === 'pending' ? <span className="text-xs text-zinc-400">waiting</span>
                            : it.actual ? <DecisionPill outcome={it.actual} /> : <span className="text-xs text-zinc-600">{it.status.replace('_', ' ')}</span>}
                          {it.cached && <span className="ml-1 text-[10px] text-sky-700">cached</span>}
                        </td>
                        <td className="max-w-72 px-3 py-2 text-[11px] text-zinc-600">
                          {(it.codes ?? []).join(', ') || (it.status === 'completed' ? 'none' : '')}
                          {it.problems && it.problems.length > 0 && <div className="text-red-700">{it.problems.join('; ')}</div>}
                          {it.error && <div className="text-red-700">{it.error}</div>}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {it.passed === true && <Check className="mx-auto size-4 text-emerald-600" strokeWidth={3} />}
                          {it.passed === false && <X className="mx-auto size-4 text-red-600" strokeWidth={3} />}
                          {it.run_id && <Link to={`/runs/${it.run_id}`} className="mt-0.5 block text-[11px] text-zinc-500 underline-offset-2 hover:underline">run</Link>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-zinc-500">Test runs are judged against the seeded master data and never change the demo ledger; they are hidden from the dashboard unless you include test runs.</p>
            </div>
          ) : (
            <p className="p-8 text-center text-sm text-zinc-500">Not run yet. With cached extractions the suite needs no model calls for invoices read before.</p>
          )}
        </section>

        <section className="rounded-xl border border-zinc-200 bg-white">
          <div className="flex flex-wrap gap-1 border-b border-zinc-100 p-2">
            {REPORT_TABS.map(([k, label]) => (
              <button key={k} type="button" onClick={() => setTab(k)}
                      className={cn('rounded-md px-3 py-1.5 text-sm', tab === k ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-100')}>{label}</button>
            ))}
          </div>
          <div className="p-5">
            {reports.isPending && <div className="h-40 animate-pulse rounded bg-zinc-100" />}
            {reports.data && (reports.data[tab] ? (
              <>
                <div className="mb-2 font-mono text-[11px] text-zinc-400">{reports.data[tab]!.file}</div>
                <Markdown text={reports.data[tab]!.markdown} />
              </>
            ) : <p className="text-sm text-zinc-500">No saved report yet. Generate it with the evaluation scripts (see README).</p>)}
          </div>
        </section>
      </div>
    </div>
  )
}
