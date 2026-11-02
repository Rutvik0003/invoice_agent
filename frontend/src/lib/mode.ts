/** Demo mode vs real mode (CLAUDE.md §12) and the inbox the invoices arrive in. */

import { useQuery } from '@tanstack/react-query'

import type { Outcome } from '@/lib/api'

export type DemoInfo = {
  model_name: string
  uses_demo_key: boolean
  key_configured: boolean
  max_runs_per_hour: number
  runs_last_hour: number
  sandbox_hours: number
}
export type AuthInfo = {
  google_configured: boolean   // Google sign-in set up on this server
  locked: boolean              // real mode only for the owner (OWNER_EMAIL)
  signed_in_as: string | null
  gmail: string | null         // the connected Gmail real mode reads
  sign_in_url: string
}
export type ModeInfo = { mode: 'demo' | 'real' | null; demo?: DemoInfo; auth?: AuthInfo }

export type InboxAttachment = {
  id: string
  file_name: string
  mime: string
  size: number
  is_invoice_file: boolean
  last_run: { id: string; status: string; decision: Outcome | null } | null
}
export type InboxMessage = {
  id: string
  from_name: string
  from_email: string
  to: string
  subject: string
  received_at: string
  body: string
  attachments: InboxAttachment[]
  replies: { sent_at: string; from: string; to: string; subject: string; body: string | null; run_id: string }[]
}
export type Inbox = {
  source: 'demo' | 'gmail'; connected: boolean; can_connect?: boolean; mailbox: string | null
  next_page_token: string | null; messages: InboxMessage[]
}
export type RunSource = { kind: string; from_name: string; from_email: string; subject: string; received_at: string }

/** An API error with the backend's own type (e.g. 'demo_limit', 'demo_restricted'). */
export class ApiError extends Error {
  kind: string | null
  constructor(message: string, kind: string | null) {
    super(message)
    this.kind = kind
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    let kind: string | null = null
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail?.message) [detail, kind] = [body.detail.message, body.detail.type ?? null]
    } catch {
      /* keep the status text */
    }
    throw new ApiError(detail, kind)
  }
  return res.json() as Promise<T>
}

const send = (method: string, url: string, body?: unknown) =>
  fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })

export const modeApi = {
  get: () => fetch('/api/mode').then(json<ModeInfo>),
  choose: (mode: 'demo' | 'real') => send('POST', '/api/mode', { mode }).then(json<ModeInfo>),
  leave: () => send('DELETE', '/api/mode').then(json<ModeInfo>),
  inbox: (params: { billsOnly: boolean; q?: string; pageToken?: string | null }) => {
    const query = new URLSearchParams({ bills_only: String(params.billsOnly), q: params.q ?? '' })
    if (params.pageToken) query.set('page_token', params.pageToken)
    return fetch(`/api/inbox?${query}`).then(json<Inbox>)
  },
  runAttachments: (items: { message_id: string; attachment_id: string }[], model?: string, modelName?: string) =>
    send('POST', '/api/inbox/run', { items, model, model_name: modelName }).then(json<{ run_id?: string; batch_id?: string }>),
  signOut: () => send('POST', '/api/auth/logout').then(json<ModeInfo>),
  disconnectGmail: () => send('POST', '/api/auth/disconnect').then(json<{ mode: null; disconnected: string | null }>),
}

export const attachmentUrl = (messageId: string, attachmentId: string) =>
  `/api/inbox/${messageId}/attachments/${attachmentId}`

/** The current mode; every screen reads it from the same cached query. */
export function useMode() {
  const query = useQuery({ queryKey: ['mode'], queryFn: modeApi.get, staleTime: 30_000 })
  return { ...query, mode: query.data?.mode ?? null, demo: query.data?.demo, isDemo: query.data?.mode === 'demo' }
}
