/** Typed client for the backend API. */

export type Health = {
  status: string
  version: string
  models_configured: { gemini: boolean; groq: boolean }
  ocr: { available: boolean; version: string | null }
}

export type ModelOption = {
  id: 'gemini' | 'groq'; label: string; model_name: string; choices: string[]; configured: boolean; description: string
}

export type AppConfig = {
  default_model: string
  models: ModelOption[]
  confidence_threshold: number
  tolerance_pct: number
  tolerance_abs_inr: number
  verify_enabled: boolean
  ocr_dpi: number
  ocr_min_word_conf: number
  verify_fuzzy_min: number
  po_infer_min_score: number
  po_infer_min_gap: number
  po_infer_floor: number
  possible_dup_days: number
  ocr: { available: boolean; version: string | null }
  max_upload_mb: number
  ai_request_gap_s: number
}

export type Sample = {
  id: string
  set: 'golden' | 'stress'
  scenario: string
  template: string
  scan_level: 'none' | 'mild' | 'heavy'
  file_name: string
  expected_decision: Outcome
  expected_reason_codes: string[]
  notes: string
}

export type Outcome = 'APPROVE' | 'HOLD' | 'REJECT'
export type Severity = 'REJECT' | 'HOLD' | 'INFO'

export type ScalarField = { value: unknown; printed: string | null; confidence: number; evidence: string | null }
export type LineItem = {
  description: string | null; hsn_sac: string | null; quantity: number | null; unit: string | null
  unit_price: number | null; amount: number | null; tax_rate: number | null; confidence: number
}
export type ExtractedInvoice = Record<string, ScalarField> & { line_items: LineItem[] }

export type FieldVerification = {
  status: 'verified' | 'cross_checked' | 'not_found' | 'not_applicable' | 'unavailable'
  source: 'text_layer' | 'ocr' | 'master_data' | 'calculation' | null
  page: number | null
  bbox: [number, number, number, number] | null
  matched_text: string | null
  ocr_word_conf: number | null
  reference_value?: string | null
}

export type CheckEvidence = {
  invoice_field: string | null
  invoice_value: unknown
  verification_status: string | null
  reference_source: string | null
  reference_value: unknown
}

export type CheckResult = {
  stage: string
  check: string
  passed: boolean
  code: string | null
  severity: Severity | null
  message: string
  evidence: CheckEvidence
}

export type RoutedQuestion = { role: string; question: string; codes: string[] }

export type LedgerChange = {
  po_number: string
  po_value: number
  billed_before: number
  billed_after: number
  remaining_after: number
  status_before: string
  status_after: string
  history_id: string
  lines: { line_no: number; description: string; unit: string; ordered: number; billed_before: number; billed_after: number; remaining_after: number }[]
}

export type Decision = {
  outcome: Outcome
  approve_with_note: boolean
  summary: string
  reasons: CheckResult[]
  routed_questions: RoutedQuestion[]
  vendor_note: string | null
  ledger_update: { po_number: string; lines: unknown[]; taxable_value: number; total_amount: number } | null
}

export type RunError = { type: string; message: string; detail?: string | null }

export type RunEvent = { id: number; stage: string; type: string; payload: Record<string, any>; created_at: string | null }

export type RunDetail = {
  hold_actions?: { actor_role: string; action: string; comment: string; payload: Record<string, any> | null; created_at: string }[]
  error_detail?: Record<string, unknown> | null
  id: string
  created_at: string
  file_name: string
  model: 'gemini' | 'groq'
  model_name: string | null
  status: string
  decision: Outcome | null
  total_amount: number | null
  vendor_id: string | null
  vendor_name: string | null
  invoice_number: string | null
  po_number: string | null
  duration_ms: number | null
  used_cache: boolean
  is_test_run: boolean
  retry_of: string | null
  sample_id: string | null
  page_count: number | null
  error: RunError | null
  extracted: ExtractedInvoice | null
  verification: { engine_used: string; fields: Record<string, FieldVerification>; line_items: FieldVerification[] } | null
  rules: {
    decision: Decision
    po_inferred: boolean
    po_candidates: { po_number: string; score: number }[]
    ledger_applied: boolean
    ledger_change: LedgerChange | null
  } | null
  events: RunEvent[]
  retries: string[]
  sample: { id: string; scenario: string; expected_decision: Outcome; expected_reason_codes: string[] } | null
  source?: { kind: string; from_name: string; from_email: string; subject: string; received_at: string } | null
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail?.message) detail = body.detail.message  // e.g. the demo's run limit
    } catch {
      /* keep the status text */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => fetch('/api/health').then(json<Health>),
  config: () => fetch('/api/config').then(json<AppConfig>),
  samples: () => fetch('/api/samples').then(json<Sample[]>),
  run: (id: string) => fetch(`/api/runs/${id}`).then(json<RunDetail>),
  startRun: (input: { file?: File; sampleId?: string; model: string; modelName?: string; useCache: boolean }) => {
    const form = new FormData()
    if (input.file) form.append('file', input.file)
    if (input.sampleId) form.append('sample_id', input.sampleId)
    form.append('model', input.model)
    if (input.modelName) form.append('model_name', input.modelName)
    form.append('use_cache', String(input.useCache))
    return fetch('/api/runs', { method: 'POST', body: form }).then(json<{ run_id: string }>)
  },
  startBatch: (input: { files: File[]; model: string; modelName?: string; useCache: boolean }) => {
    const form = new FormData()
    input.files.forEach((f) => form.append('files', f))
    form.append('model', input.model)
    if (input.modelName) form.append('model_name', input.modelName)
    form.append('use_cache', String(input.useCache))
    return fetch('/api/batches', { method: 'POST', body: form })
      .then(json<{ batch_id: string; run_ids: string[]; file_errors: { file_name: string; error: string }[] }>)
  },
  retry: (id: string, model: string, modelName?: string) =>
    fetch(`/api/runs/${id}/retry?model=${model}${modelName ? `&model_name=${encodeURIComponent(modelName)}` : ''}`, { method: 'POST' })
      .then(json<{ run_id: string }>),
}

export const pageUrl = (runId: string, page: number) => `/api/runs/${runId}/pages/${page}.png`
