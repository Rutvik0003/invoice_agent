import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, Inbox, Loader2, Mail, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ApiError, modeApi, useMode } from '@/lib/mode'
import { navigate } from '@/lib/router'

const DEMO_POINTS = [
  'A sample AP inbox with 12 vendor bills: clean approvals and the hard cases (PO overrun, duplicate, changed bank details, wrong GST, a quotation sent as a bill, a blurry scan)',
  'Your own private sandbox: approvals, holds and resets never affect anyone else',
  'No sign-in, nothing to install',
]

const REAL_POINTS = [
  'Connect a Gmail inbox and pick the bills to check',
  'Upload invoices, run batches and the Test Suite',
  'Your own data and AI keys',
]

const AUTH_ERRORS: Record<string, string> = {
  not_owner: "Real mode is only for the owner's Google account. You are welcome to try the demo instead.",
  no_gmail: 'Real mode needs permission to read your Gmail. Sign in again and allow it.',
  cancelled: 'Sign-in was cancelled.',
  invalid_state: 'The sign-in link expired. Please try again.',
  google: 'Google sign-in did not complete. Please try again.',
}

/** The first screen: try the demo without signing in, or use the real product (the owner, signed in with Google). */
export default function Start() {
  const queryClient = useQueryClient()
  const auth = useMode().data?.auth
  const authError = AUTH_ERRORS[new URLSearchParams(window.location.search).get('auth_error') ?? '']
  const needsGoogle = !!auth && (auth.locked || auth.google_configured) && !auth.signed_in_as
  const openReal = () => (needsGoogle ? window.location.assign(auth!.sign_in_url) : choose.mutate('real'))
  const choose = useMutation({
    mutationFn: modeApi.choose,
    onSuccess: (data) => {
      // data of the other mode must not be shown: drop every cached answer except the mode itself
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'mode' })
      queryClient.setQueryData(['mode'], data)
      navigate(data.mode === 'demo' ? '/inbox' : '/')
    },
    // real mode is locked to the owner and this browser is not signed in: go to Google's sign-in instead
    onError: (error) => {
      if (error instanceof ApiError && error.kind === 'sign_in_required') window.location.assign('/api/auth/google/start')
    },
  })
  const busy = (mode: 'demo' | 'real') => choose.isPending && choose.variables === mode

  return (
    <div className="min-h-screen bg-zinc-50 px-4 py-12 text-zinc-900">
      <div className="mx-auto max-w-4xl">
        <div className="flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-lg bg-zinc-900 text-sm font-bold tracking-tight text-white">P</div>
          <div className="leading-tight">
            <div className="text-base font-semibold">Payable</div>
            <div className="text-xs text-zinc-500">AP decisions you can audit</div>
          </div>
        </div>

        <h1 className="mt-10 text-3xl font-semibold tracking-tight">Every vendor bill: paid, or sent to a person to verify, with the reasons.</h1>
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-zinc-600">
          An AI model reads the invoice, an independent OCR / text-layer check confirms what it read on the page,
          and plain rules decide against the vendor master, purchase orders and payment history.
        </p>
        <div className="mt-4 flex flex-wrap gap-2 text-xs font-medium text-zinc-600">
          {['AI reads', 'OCR verifies', 'Code decides'].map((step, i) => (
            <span key={step} className="flex items-center gap-2">
              {i > 0 && <ArrowRight className="size-3 text-zinc-400" />}
              <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-zinc-200">{step}</span>
            </span>
          ))}
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-2">
          <section className="flex flex-col rounded-xl bg-white p-6 ring-2 ring-zinc-900">
            <div className="flex items-center gap-2">
              <Inbox className="size-5" />
              <h2 className="text-lg font-semibold">Try the demo</h2>
              <span className="ml-auto rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">no sign-in</span>
            </div>
            <ul className="mt-4 flex-1 space-y-2.5">
              {DEMO_POINTS.map((p) => (
                <li key={p} className="flex gap-2 text-sm leading-snug text-zinc-600">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />{p}
                </li>
              ))}
            </ul>
            <Button className="mt-6 w-full" size="lg" disabled={choose.isPending} onClick={() => choose.mutate('demo')}>
              {busy('demo') ? <Loader2 className="animate-spin" /> : <ArrowRight />}Try demo
            </Button>
          </section>

          <section className="flex flex-col rounded-xl bg-white p-6 ring-1 ring-zinc-200">
            <div className="flex items-center gap-2">
              <Mail className="size-5" />
              <h2 className="text-lg font-semibold">Real mode</h2>
              <span className="ml-auto rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600">owner</span>
            </div>
            <ul className="mt-4 flex-1 space-y-2.5">
              {REAL_POINTS.map((p) => (
                <li key={p} className="flex gap-2 text-sm leading-snug text-zinc-600">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-zinc-400" />{p}
                </li>
              ))}
            </ul>
            <Button className="mt-6 w-full" size="lg" variant="outline" disabled={choose.isPending} onClick={openReal}>
              {busy('real') ? <Loader2 className="animate-spin" /> : needsGoogle ? <Mail /> : <ArrowRight />}
              {needsGoogle ? 'Sign in with Google' : auth?.signed_in_as ? `Continue as ${auth.signed_in_as}` : 'Use real mode'}
            </Button>
            {needsGoogle && <p className="mt-2 text-center text-[11px] text-zinc-500">Owner only · Gmail is read-only</p>}
          </section>
        </div>
        {choose.isError && !(choose.error instanceof ApiError && choose.error.kind === 'sign_in_required') && <p className="mt-3 text-sm text-red-700">{choose.error.message}</p>}
        {authError && <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">{authError}</p>}

        <p className="mt-8 flex items-center gap-1.5 text-xs text-zinc-500">
          <ShieldCheck className="size-3.5" />
          All companies, vendors and invoices in the demo are fictional (buyer: Zenith Retail Pvt Ltd, Maharashtra).
        </p>
      </div>
    </div>
  )
}
