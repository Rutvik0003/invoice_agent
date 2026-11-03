import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, Clock, Layers, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/AppShell'
import { DecisionPill, SHOWN_ORDER } from '@/components/status'
import { api2, runningInterval, type Batch, type RunSummary } from '@/lib/api2'
import { duration, inr, timeAgo } from '@/lib/format'
import { Link } from '@/lib/router'

function BatchRow({ batch }: { batch: Batch }) {
  const pct = batch.total ? Math.round((batch.done / batch.total) * 100) : 0
  return (
    <Link to={`/batches/${batch.id}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-zinc-50">
      <Layers className="size-5 shrink-0 text-zinc-400" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">Batch of {batch.total} invoice{batch.total === 1 ? '' : 's'}</div>
        <div className="text-xs text-zinc-500">
          started {timeAgo(batch.created_at)} · {batch.model === 'gemini' ? 'Gemini' : 'Groq'}{batch.model_name ? ` · ${batch.model_name}` : ''}
        </div>
        {!batch.finished && (
          <div className="mt-2 h-1.5 w-full max-w-md overflow-hidden rounded-full bg-zinc-100">
            <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
      <div className="shrink-0 text-right text-xs text-zinc-600">
        {batch.finished
          ? <span className="flex gap-1.5">{SHOWN_ORDER.filter((o) => batch.by_outcome[o])
              .map((o) => <DecisionPill key={o} shown={o} className="px-1.5 py-0 text-[10px]" />)}{batch.failed > 0 && `${batch.failed} not read`}</span>
          : <span className="tabular-nums"><b className="text-zinc-900">{batch.done}</b> / {batch.total} done</span>}
      </div>
    </Link>
  )
}

function RunRow({ run }: { run: RunSummary & { stage?: { title: string; number: number; of: number } | null } }) {
  const active = run.status === 'queued' || run.status === 'running'
  return (
    <Link to={`/runs/${run.id}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-zinc-50">
      {active ? <Loader2 className="size-5 shrink-0 animate-spin text-sky-600" /> : <CheckCircle2 className="size-5 shrink-0 text-zinc-300" />}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{run.file_name}</div>
        <div className="truncate text-xs text-zinc-500">
          {active
            ? run.stage ? `Stage ${run.stage.number} of ${run.stage.of}: ${run.stage.title}` : 'Waiting to start'
            : [run.vendor_name, run.invoice_number, run.total_amount != null ? inr(run.total_amount) : null].filter(Boolean).join(' · ')}
        </div>
      </div>
      <div className="shrink-0 text-right text-xs text-zinc-500">
        {active ? <>started {timeAgo(run.created_at)}</>
          : run.decision ? <DecisionPill outcome={run.decision} status={run.status} />
          : <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-medium text-zinc-600">{run.status.replaceAll('_', ' ')}</span>}
        {!active && run.duration_ms && <div className="mt-0.5">{duration(run.duration_ms)}</div>}
      </div>
    </Link>
  )
}

function Section({ title, icon, empty, children }: { title: string; icon: React.ReactNode; empty: string; children: React.ReactNode[] }) {
  return (
    <section className="overflow-hidden rounded-xl bg-white ring-1 ring-zinc-200">
      <h2 className="flex items-center gap-2 border-b border-zinc-100 px-5 py-3 text-sm font-semibold">{icon}{title}</h2>
      {children.length ? <div className="divide-y divide-zinc-100">{children}</div>
        : <p className="px-5 py-6 text-sm text-zinc-500">{empty}</p>}
    </section>
  )
}

/** Everything still being processed. Processing runs on the server, so it carries on when you leave a live screen. */
export default function RunningPage() {
  const running = useQuery({ queryKey: ['running'], queryFn: api2.running, refetchInterval: (q) => runningInterval(q.state.data) })
  const data = running.data
  return (
    <div>
      <PageHeader
        title="Running processes"
        subtitle="Invoices and batches keep processing on the server when you leave their screen; find them here."
      />
      <div className="mx-auto max-w-5xl space-y-6 px-8 py-6">
        {running.isError && <p className="text-sm text-red-700">Could not load: {running.error.message}</p>}
        {!data && !running.isError && <div className="grid place-items-center py-16 text-zinc-400"><Loader2 className="animate-spin" /></div>}
        {data && (
          <>
            <Section title={`In progress (${data.active})`} icon={<Activity className="size-4 text-sky-600" />}
                     empty="Nothing is running right now.">
              {[...data.batches.map((b) => <BatchRow key={b.id} batch={b} />), ...data.runs.map((r) => <RunRow key={r.id} run={r} />)]}
            </Section>
            <Section title="Finished in the last 30 minutes" icon={<Clock className="size-4 text-zinc-400" />}
                     empty="Nothing finished recently.">
              {[...data.recent_batches.map((b) => <BatchRow key={b.id} batch={b} />), ...data.recent_runs.map((r) => <RunRow key={r.id} run={r} />)]}
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
