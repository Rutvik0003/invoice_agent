import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CornerUpLeft, ExternalLink, FileText, Info, Loader2, Mail, Paperclip, Play } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/AppShell'
import { DecisionPill } from '@/components/status'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { timeAgo } from '@/lib/format'
import { attachmentUrl, modeApi, useMode, type InboxAttachment, type InboxMessage } from '@/lib/mode'
import { Link, navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

type Pick = { message_id: string; attachment_id: string }
const key = (p: Pick) => `${p.message_id}/${p.attachment_id}`
const kb = (bytes: number) => `${Math.max(1, Math.round(bytes / 1024))} KB`
const bills = (m: InboxMessage) => m.attachments.filter((a) => a.is_invoice_file)

function LastRun({ attachment }: { attachment: InboxAttachment }) {
  const run = attachment.last_run
  if (!run) return <span className="text-[11px] text-zinc-400">not checked yet</span>
  return (
    <Link to={`/runs/${run.id}`} className="inline-flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-900">
      {run.decision ? <DecisionPill outcome={run.decision} className="px-1.5 py-0 text-[10px]" />
        : <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-medium text-zinc-600">{run.status.replace('_', ' ')}</span>}
      last run
    </Link>
  )
}

function MessageRow({ message, active, picked, onOpen, onToggle }: {
  message: InboxMessage; active: boolean; picked: Set<string>; onOpen: () => void; onToggle: (p: Pick) => void
}) {
  const files = bills(message)
  const allPicked = files.length > 0 && files.every((a) => picked.has(key({ message_id: message.id, attachment_id: a.id })))
  return (
    <li className={cn('flex gap-3 border-b border-zinc-100 px-4 py-3', active ? 'bg-zinc-100' : 'hover:bg-zinc-50')}>
      <input
        type="checkbox"
        aria-label={`Select the bill in "${message.subject}"`}
        className="mt-1 size-4 accent-zinc-900 disabled:opacity-30"
        disabled={!files.length}
        checked={allPicked}
        onChange={() => files.forEach((a) => {
          const p = { message_id: message.id, attachment_id: a.id }
          if (picked.has(key(p)) === allPicked) onToggle(p)
        })}
      />
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-sm font-medium">{message.from_name}</span>
          <span className="ml-auto shrink-0 text-[11px] text-zinc-400">{timeAgo(message.received_at)}</span>
        </div>
        <div className="truncate text-[13px] text-zinc-700">{message.subject}</div>
        <div className="mt-1 flex items-center gap-2">
          {files.length ? (
            <>
              <span className="inline-flex items-center gap-1 text-[11px] text-zinc-500"><Paperclip className="size-3" />{files.length} bill</span>
              <LastRun attachment={files[0]} />
            </>
          ) : <span className="text-[11px] text-zinc-400">no bill attached</span>}
          {message.replies.length > 0 && (
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-sky-700"><CornerUpLeft className="size-3" />{message.replies.length} replied</span>
          )}
        </div>
      </button>
    </li>
  )
}

function Reader({ message, picked, onToggle, onRun, running }: {
  message: InboxMessage; picked: Set<string>; onToggle: (p: Pick) => void; onRun: (p: Pick[]) => void; running: boolean
}) {
  return (
    <article className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="border-b border-zinc-200 px-6 py-4">
        <h2 className="text-lg font-semibold">{message.subject}</h2>
        <div className="mt-1 text-sm text-zinc-600">
          <b className="font-medium text-zinc-900">{message.from_name}</b> &lt;{message.from_email}&gt;
          <span className="text-zinc-400"> → {message.to}</span>
        </div>
        <div className="text-xs text-zinc-400">{new Date(message.received_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</div>
      </div>
      <div className="px-6 py-4 text-sm leading-relaxed whitespace-pre-line text-zinc-700">{message.body}</div>
      {message.attachments.length > 0 && (
        <div className="space-y-2 px-6 pb-6">
          {message.attachments.map((a) => {
            const p = { message_id: message.id, attachment_id: a.id }
            return (
              <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-200 px-3 py-2.5">
                <input type="checkbox" aria-label={`Select ${a.file_name}`} className="size-4 accent-zinc-900"
                       checked={picked.has(key(p))} onChange={() => onToggle(p)} disabled={!a.is_invoice_file} />
                <FileText className="size-5 text-zinc-400" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{a.file_name}</div>
                  <div className="flex items-center gap-2 text-[11px] text-zinc-500">{kb(a.size)} · <LastRun attachment={a} /></div>
                </div>
                <a href={attachmentUrl(message.id, a.id)} target="_blank" rel="noreferrer"
                   className="inline-flex items-center gap-1 text-xs text-zinc-600 underline-offset-2 hover:underline">
                  Open <ExternalLink className="size-3" />
                </a>
                <Button size="sm" disabled={running || !a.is_invoice_file} onClick={() => onRun([p])}>
                  <Play />Check this bill
                </Button>
              </div>
            )
          })}
        </div>
      )}
      {message.replies.map((reply) => (
        <div key={reply.sent_at} className="mx-6 mb-4 rounded-lg border border-sky-200 bg-sky-50/50">
          <div className="flex flex-wrap items-baseline gap-x-2 border-b border-sky-100 px-4 py-2.5 text-sm">
            <CornerUpLeft className="size-3.5 self-center text-sky-700" />
            <b className="font-medium">{reply.from}</b>
            <span className="text-zinc-500">→ {reply.to}</span>
            <span className="ml-auto text-xs text-zinc-400">{timeAgo(reply.sent_at)}</span>
            <div className="w-full text-xs text-zinc-600">{reply.subject} · <Link to={`/runs/${reply.run_id}`} className="underline underline-offset-2">from this run</Link></div>
          </div>
          <div className="px-4 py-3 text-[13px] leading-relaxed whitespace-pre-line text-zinc-700">{reply.body}</div>
          <p className="px-4 pb-2.5 text-[11px] text-zinc-400">Demo: logged in this thread, not delivered.</p>
        </div>
      ))}
    </article>
  )
}

/** The inbox invoices arrive in: read an email, open its attachment, and check the bills you choose. */
export default function Inbox() {
  const queryClient = useQueryClient()
  const { isDemo, demo } = useMode()
  const inbox = useQuery({ queryKey: ['inbox'], queryFn: modeApi.inbox })
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  const gemini = config.data?.models.find((m) => m.id === 'gemini')
  const [modelName, setModelName] = useState<string | null>(null)
  const chosenModel = modelName ?? gemini?.model_name
  const [openId, setOpenId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('open'))
  const [onlyBills, setOnlyBills] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const toggle = (p: Pick) => setPicked((old) => {
    const next = new Set(old)
    if (next.has(key(p))) next.delete(key(p))
    else next.add(key(p))
    return next
  })
  const run = useMutation({
    mutationFn: (items: Pick[]) => modeApi.runAttachments(items, chosenModel),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['mode'] })
      navigate(r.run_id ? `/runs/${r.run_id}` : `/batches/${r.batch_id}`)
    },
  })

  const data = inbox.data
  if (data && !data.connected) {
    return (
      <div>
        <PageHeader title="Inbox" subtitle="Bills arriving by email" />
        <div className="mx-auto mt-12 max-w-md rounded-xl bg-white p-6 text-center ring-1 ring-zinc-200">
          <Mail className="mx-auto size-8 text-zinc-400" />
          <h2 className="mt-3 font-semibold">Gmail is not connected yet</h2>
          <p className="mt-1 text-sm text-zinc-600">Connecting a Gmail inbox is coming next. Until then, upload invoices on New Run.</p>
          <Button className="mt-4" variant="outline" onClick={() => navigate('/')}>Go to New Run</Button>
        </div>
      </div>
    )
  }
  const messages = (data?.messages ?? []).filter((m) => !onlyBills || bills(m).length > 0)
  const open = messages.find((m) => m.id === openId) ?? messages.find((m) => bills(m).length > 0) ?? messages[0]
  const chosen = [...picked].map((k) => { const [message_id, attachment_id] = k.split('/'); return { message_id, attachment_id } })
  const left = demo ? Math.max(0, demo.max_runs_per_hour - demo.runs_last_hour) : null

  return (
    <div className="flex h-screen flex-col">
      <PageHeader
        title="Inbox"
        subtitle={data ? <>{data.mailbox} · {data.messages.length} emails{isDemo && ' · sample inbox of the demo'}</> : 'Loading…'}
        actions={
          <>
            {left !== null && <span className="text-xs text-zinc-500">{left} of {demo!.max_runs_per_hour} demo runs left this hour</span>}
            {gemini && gemini.choices.length > 1 && (
              <label className="flex items-center gap-1.5 text-xs text-zinc-500">
                Gemini model
                <select value={chosenModel ?? ''} onChange={(e) => setModelName(e.target.value)}
                        className="h-8 rounded-md border border-zinc-300 bg-white px-2 font-mono text-xs text-zinc-800">
                  {gemini.choices.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            )}
            <Button disabled={!chosen.length || run.isPending} onClick={() => run.mutate(chosen)}>
              {run.isPending ? <Loader2 className="animate-spin" /> : <Play />}
              {chosen.length > 1 ? `Check ${chosen.length} bills (batch)` : 'Check selected bill'}
            </Button>
          </>
        }
      />
      {run.isError && (
        <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-8 py-2 text-sm text-amber-900">
          <Info className="size-4 shrink-0" />{run.error.message}
        </div>
      )}
      {inbox.isError && <div className="p-8 text-sm text-red-700">Could not load the inbox: {inbox.error.message}</div>}
      {!data && !inbox.isError && <div className="grid flex-1 place-items-center text-zinc-400"><Loader2 className="animate-spin" /></div>}
      {data && (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-[380px] shrink-0 flex-col border-r border-zinc-200 bg-white">
            <div className="flex items-center gap-1 border-b border-zinc-200 px-4 py-2 text-xs">
              {[['All emails', false], ['With bills', true]].map(([label, value]) => (
                <button key={String(label)} type="button" onClick={() => setOnlyBills(value as boolean)}
                        className={cn('rounded-md px-2.5 py-1', onlyBills === value ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-100')}>
                  {label as string}
                </button>
              ))}
              <span className="ml-auto text-zinc-400">{picked.size ? `${picked.size} selected` : 'tick bills to check several'}</span>
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto">
              {messages.map((m) => (
                <MessageRow key={m.id} message={m} active={m.id === open?.id} picked={picked}
                            onOpen={() => setOpenId(m.id)} onToggle={toggle} />
              ))}
            </ul>
          </aside>
          {open ? <Reader message={open} picked={picked} onToggle={toggle} onRun={(p) => run.mutate(p)} running={run.isPending} />
            : <div className="grid flex-1 place-items-center text-sm text-zinc-400">No emails</div>}
        </div>
      )}
    </div>
  )
}
