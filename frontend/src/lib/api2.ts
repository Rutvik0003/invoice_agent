/** API client for the Phase 7 screens: dashboard, hold queue, test suite, data, settings. */

import type { CheckResult, ExtractedInvoice, FieldVerification, Outcome, RoutedQuestion, RunDetail } from './api'

export type RunSummary = Omit<RunDetail, 'extracted' | 'verification' | 'rules' | 'events' | 'retries' | 'sample'>

export type RunsPage = { total: number; page: number; page_size: number; items: RunSummary[] }

export type Stats = {
  total_runs: number
  by_decision: Partial<Record<Outcome, number>>
  by_status: Record<string, number>
  avg_duration_ms: number | null
  runs_by_model: Record<string, number>
  top_reason_codes: [string, number][]
  fields_verified_pct: number | null
  critical_fields_verified_pct: number | null
  decided_automatically: number
  ap_minutes_saved: number
  ap_minutes_assumption: string
  decisions_by_day: { date: string; decision: Outcome; count: number }[]
}

export type HoldActionRecord = {
  actor_role: string; action: string; comment: string; payload: Record<string, unknown> | null; created_at: string
}

export type HoldItem = RunSummary & {
  routed_questions: RoutedQuestion[]
  reasons: CheckResult[]
  po_candidates: { po_number: string; score: number; item_similarity: number; amount_closeness: number; qty_match: number }[]
  verification_fields: Record<string, FieldVerification>
  extracted: ExtractedInvoice | null
  resolved: boolean
  hold_actions: HoldActionRecord[]
}

export type Vendor = {
  vendor_id: string; legal_name: string; trade_name: string; gstin: string; state: string; state_code: string
  status: 'approved' | 'pending' | 'blocked'; category: string; bank_name: string; bank_account: string; ifsc: string
  payment_terms_days: number
}

export type PurchaseOrder = {
  po_number: string; vendor_id: string; po_date: string; status: 'open' | 'partially_billed' | 'closed'
  taxable_value: number; billed_value: number; remaining_value: number; total_value: number; billed_pct: number
  lines: {
    line_no: number; description: string; hsn_sac: string; unit: string; qty_ordered: number; qty_billed: number
    qty_remaining: number; unit_price: number; gst_rate: number
  }[]
  invoices: { history_id: string; invoice_number: string; invoice_date: string; taxable_value: number; total_amount: number; status: string }[]
}

export type HistoryRow = {
  history_id: string; vendor_id: string; invoice_number: string; invoice_date: string; po_number: string | null
  taxable_value: number; total_amount: number; status: string; from_run: boolean
}

export type SuiteItem = {
  sample_id: string; scenario: string; expected: Outcome; acceptable: Outcome[]; expected_codes: string[]
  status: string; run_id?: string; actual?: Outcome | null; codes?: string[]; passed?: boolean; problems?: string[]
  cached?: boolean; error?: string | null
}

export type Suite = {
  status: 'never_run' | 'running' | 'done'; id?: string; model?: string; use_cache?: boolean; started_at?: string
  finished_at?: string | null; done?: number; passed?: number; total?: number; next_call_in_s?: number; items: SuiteItem[]
}

export type BatchItem = RunSummary & {
  queue_position: number | null
  attempt: number
  reasons: { code: string; severity: 'REJECT' | 'HOLD' | 'INFO'; message: string }[]
}

export type Batch = {
  id: string; created_at: string; model: string; model_name: string | null; total: number; done: number
  finished: boolean; by_status: Record<string, number>; by_decision: Partial<Record<Outcome, number>>
  file_errors: { file_name: string; error: string }[]; total_amount: number; failed: number; items?: BatchItem[]
}

export type EditableSettings = { ai_request_gap_s: number }

export type EmailHistory = {
  created_at: string; recipient: string; subject: string; sent: boolean; error: string | null; in_thread: boolean
}

export type EmailPreview = {
  sender: string; recipient: string; subject: string; body: string
  attachment_name: string; attachment_mime: string; history: EmailHistory[]
  thread: { message_id: string; subject: string; from_name: string; from_email: string } | null
}

/** How often the running list refreshes: quickly while something runs, slowly when idle. */
export const runningInterval = (data: Running | undefined) => (data?.active ? 2_000 : 15_000)

export type Running = {
  active: number
  runs: (RunSummary & { stage: { key: string; title: string; number: number; of: number } | null })[]
  batches: Batch[]
  recent_runs: RunSummary[]
  recent_batches: Batch[]
}

export type PoLineInfo = {
  line_no: number; description: string; unit: string; qty_ordered: number; qty_billed: number; qty_remaining: number
  unit_price: number
}

export type PoComparison = {
  options: string[]
  option_reasons: Record<string, 'matched' | 'quoted' | 'suggested' | 'other'>
  candidates: string[]
  selected: string | null
  comparison: {
    po: { po_number: string; vendor_id: string; po_date: string; status: string; taxable_value: number; billed_value: number; remaining_value: number }
    belongs_to_vendor: boolean
    closed: boolean
    lines: {
      index: number; description: string; quantity: number; unit_price: number; amount: number; adjustment: boolean
      po_line: PoLineInfo | null; price_status?: 'match' | 'below_po' | 'within_tolerance' | 'over_tolerance'
      price_diff_on_line?: number; issues: ('not_on_po' | 'qty_exceeds_po' | 'price_over_tolerance')[]
    }[]
    po_lines_not_billed: { line_no: number; description: string; unit: string; qty_remaining: number; unit_price: number }[]
    totals: { this_invoice: number; remaining_before: number; remaining_after: number; tolerance: number; overrun: boolean }
  } | null
}

export type ReportKind = 'rules' | 'extraction_gemini' | 'extraction_groq' | 'verification'
export type Reports = Partial<Record<ReportKind, { file: string; markdown: string }>>

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail?.message) detail = body.detail.message  // e.g. the demo's run limit
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* keep the status text */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) =>
  new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)]),
  ).toString()

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })

export const api2 = {
  runs: (params: Record<string, string | number | boolean | undefined>) => fetch(`/api/runs?${qs(params)}`).then(json<RunsPage>),
  stats: (includeTest: boolean) =>
    fetch(`/api/stats?${qs({ include_test: includeTest, tz_offset_minutes: new Date().getTimezoneOffset() })}`).then(json<Stats>),
  holds: (state: 'open' | 'resolved') =>
    fetch(`/api/holds?state=${state}`).then(json<{ items: HoldItem[]; by_role: Record<string, string[]> }>),
  holdAction: (runId: string, body: { action: string; role: string; comment: string; payload?: Record<string, unknown> }) =>
    post(`/api/holds/${runId}/action`, body).then(json<{ run: RunSummary; result: Record<string, unknown> }>),
  vendors: () => fetch('/api/data/vendors').then(json<Vendor[]>),
  pos: (vendor?: string) => fetch(`/api/data/pos?${qs({ vendor })}`).then(json<PurchaseOrder[]>),
  history: () => fetch('/api/data/history').then(json<HistoryRow[]>),
  startSuite: (body: { model: string; use_cache: boolean; delay_s: number }) =>
    post('/api/eval/golden', body).then(json<{ suite_id: string }>),
  suite: () => fetch('/api/eval/latest').then(json<Suite>),
  reports: () => fetch('/api/eval/reports').then(json<Reports>),
  resetDemo: () => post('/api/admin/reset-demo').then(json<Record<string, number | boolean>>),
  batches: () => fetch('/api/batches').then(json<Batch[]>),
  batch: (id: string) => fetch(`/api/batches/${id}`).then(json<Batch>),
  retryBatch: (id: string, body: { model: string; run_ids?: string[] }) =>
    post(`/api/batches/${id}/retry`, body).then(json<{ run_ids: string[] }>),
  editableSettings: () => fetch('/api/admin/settings').then(json<EditableSettings>),
  saveSettings: (body: EditableSettings) =>
    fetch('/api/admin/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(json<EditableSettings>),
  emailPreview: (runId: string) => fetch(`/api/runs/${runId}/email`).then(json<EmailPreview>),
  sendEmail: (runId: string) => post(`/api/runs/${runId}/email`)
    .then(json<{ sent: boolean; recipient: string; subject: string; in_thread: boolean; history: EmailHistory[] }>),
  running: () => fetch('/api/running').then(json<Running>),
  poCompare: (runId: string, po?: string) => fetch(`/api/runs/${runId}/po-compare?${qs({ po })}`).then(json<PoComparison>),
}
