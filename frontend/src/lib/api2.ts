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

export type ReportKind = 'rules' | 'extraction_gemini' | 'extraction_groq' | 'verification'
export type Reports = Partial<Record<ReportKind, { file: string; markdown: string }>>

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
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
}
