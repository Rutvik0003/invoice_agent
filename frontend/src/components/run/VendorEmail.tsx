import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, CornerUpLeft, Loader2, Mail, Paperclip } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { api2 } from '@/lib/api2'
import { timeAgo } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

/** One tap "emails" the vendor what is wrong and what to change, with the invoice attached (demo: logged, not delivered).
 *  An invoice that arrived by email is answered in that email's thread. */
export function VendorEmail({ runId, compact = false }: { runId: string; compact?: boolean }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const preview = useQuery({ queryKey: ['email', runId], queryFn: () => api2.emailPreview(runId), retry: false })
  const send = useMutation({
    mutationFn: () => api2.sendEmail(runId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['email', runId] }),
  })
  if (preview.isError || !preview.data) return null  // approved invoices, or nothing for the vendor to change
  const mail = preview.data
  const lastSent = [...mail.history].reverse().find((h) => h.sent)

  return (
    <section className={cn('rounded-xl bg-white ring-1 ring-zinc-200', compact ? 'p-3' : 'p-4')}>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => send.mutate()} disabled={send.isPending}>
          {send.isPending ? <Loader2 className="animate-spin" /> : mail.thread ? <CornerUpLeft /> : <Mail />}
          {mail.thread ? (lastSent ? 'Reply to vendor again' : 'Reply to vendor') : lastSent ? 'Email vendor again' : 'Email vendor'}
        </Button>
        <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1 text-xs text-zinc-600 hover:text-zinc-900">
          Preview <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
        </button>
        {lastSent && !send.isSuccess && (
          <span className="ml-auto text-[11px] text-zinc-500">Sent {timeAgo(lastSent.created_at)}</span>
        )}
      </div>
      {send.isSuccess && (
        <div role="status" className="mt-2 flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 ring-1 ring-emerald-200">
          <CheckCircle2 className="size-4 shrink-0" />
          {send.data.in_thread
            ? <span>Reply sent to {send.data.recipient} in the thread “{mail.thread?.subject}”. <Link to={`/inbox?open=${mail.thread?.message_id}`} className="underline underline-offset-2">See it in the inbox</Link></span>
            : <>Mail sent to {send.data.recipient}</>}
        </div>
      )}
      {send.isError && <p className="mt-2 text-xs text-red-700">{send.error.message}</p>}
      {open && (
        <div className="mt-3 space-y-2 rounded-lg bg-zinc-50 p-3 text-sm">
          <div className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs">
            <span className="text-zinc-500">To</span><span>{mail.recipient}</span>
            {mail.thread && <><span className="text-zinc-500">Thread</span><span>reply to “{mail.thread.subject}” from {mail.thread.from_name}</span></>}
            <span className="text-zinc-500">Subject</span><span className="font-medium">{mail.subject}</span>
          </div>
          <pre className="max-h-72 overflow-y-auto border-t border-zinc-200 pt-2 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-zinc-800">{mail.body}</pre>
          <div className="flex items-center gap-1.5 text-xs text-zinc-600"><Paperclip className="size-3.5" />{mail.attachment_name}</div>
          <p className="text-[11px] text-zinc-400">Demo: emails are logged against the run, not delivered.</p>
        </div>
      )}
    </section>
  )
}
