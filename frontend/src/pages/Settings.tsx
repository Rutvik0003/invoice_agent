import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, RotateCcw, Save, XCircle } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { PageHeader } from '@/components/AppShell'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { api2, type EditableSettings } from '@/lib/api2'
import { inr } from '@/lib/format'
import { useMode } from '@/lib/mode'

/** The settings an admin may change here (saved in the database; a demo reset keeps them). */
function AdminSettings() {
  const current = useQuery({ queryKey: ['admin-settings'], queryFn: api2.editableSettings })
  if (!current.data) return <div className="h-48 animate-pulse rounded-xl bg-zinc-100" />
  return <AdminForm saved={current.data} />
}

function AdminForm({ saved: initial }: { saved: EditableSettings }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<EditableSettings>(initial)
  const [saved, setSaved] = useState<EditableSettings>(initial)
  const save = useMutation({
    mutationFn: (body: EditableSettings) => api2.saveSettings(body),
    onSuccess: (result) => {
      setForm(result)
      setSaved(result)
      queryClient.invalidateQueries({ queryKey: ['admin-settings'] })
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })
  const changed = JSON.stringify(form) !== JSON.stringify(saved)
  const set = (patch: Partial<EditableSettings>) => {
    save.reset()
    setForm({ ...form, ...patch })
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <h2 className="text-sm font-semibold">Admin settings</h2>
      <p className="mt-0.5 text-xs text-zinc-500">Changed here, used immediately. They override the environment defaults until the next demo reset.</p>
      <div className="mt-3 max-w-xl">
        <div className="space-y-1.5">
          <label htmlFor="gap" className="text-sm font-medium">Pause between AI requests</label>
          <div className="flex items-center gap-2">
            <Input id="gap" type="number" min={0} max={120} step={1} value={form.ai_request_gap_s} className="w-24 tabular-nums"
                   onChange={(e) => set({ ai_request_gap_s: Number(e.target.value) })} />
            <span className="text-sm text-zinc-600">seconds</span>
          </div>
          <p className="text-xs leading-relaxed text-zinc-500">
            Every AI request (live runs, batches, the Test Suite) waits until at least this long after the previous one, so the free tiers'
            requests-per-minute limits are never hit. Gemini Flash free tier: about 10 requests a minute, so 6 s or more. 0 = no pause.
          </p>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-3 border-t border-zinc-100 pt-4">
        <Button size="sm" disabled={!changed || save.isPending} onClick={() => save.mutate(form)}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}Save
        </Button>
        {save.isSuccess && !changed && <span className="text-sm text-emerald-700">Saved.</span>}
        {save.isError && <span className="text-sm text-red-700">{save.error.message}</span>}
      </div>
    </section>
  )
}

function Row({ name, value, env, children }: { name: string; value: ReactNode; env?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-t border-zinc-100 py-3 first:border-0 sm:grid-cols-[220px_140px_minmax(0,1fr)] sm:gap-4">
      <div className="text-sm font-medium">{name}{env && <div className="font-mono text-[10px] font-normal text-zinc-400">{env}</div>}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
      <div className="text-sm leading-relaxed text-zinc-600">{children}</div>
    </div>
  )
}

export default function Settings() {
  const queryClient = useQueryClient()
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  const reset = useMutation({ mutationFn: api2.resetDemo, onSuccess: () => queryClient.invalidateQueries() })
  const { isDemo } = useMode()
  const c = config.data

  return (
    <div>
      <PageHeader title="Settings" subtitle="Admin settings you can change here, how the rules are configured (set through environment variables), and demo controls." />
      <div className="max-w-5xl space-y-6 px-8 py-6">
        <AdminSettings />
        <section className="rounded-xl border border-zinc-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold">Business rules</h2>
          {c && <>
            <Row name="Price / amount tolerance" env="TOLERANCE_PCT, TOLERANCE_ABS_INR" value={`${c.tolerance_pct}% or ${inr(c.tolerance_abs_inr)}`}>
              A difference is accepted if it is no more than {c.tolerance_pct}% of the value and no more than {inr(c.tolerance_abs_inr)}, whichever is smaller.
              Example: on a ₹40,000 line up to ₹400 extra is noted; on ₹2,00,000 the cap is ₹{c.tolerance_abs_inr}.
            </Row>
            <Row name="Confidence threshold" env="CONFIDENCE_THRESHOLD" value={`${Math.round(c.confidence_threshold * 100)}%`}>
              If a key value could not be checked on the page and the AI is less sure than this, the invoice is held for a person to confirm it.
            </Row>
            <Row name="Inferring a missing PO" env="PO_INFER_MIN_SCORE, _GAP, _FLOOR" value={`≥ ${c.po_infer_min_score} · gap ${c.po_infer_min_gap}`}>
              When no PO is printed, the vendor's open POs are scored on items (50%), amount (30%) and quantities (20%).
              A best score of {c.po_infer_min_score}+ that beats the next by {c.po_infer_min_gap}+ is proposed for one-click confirmation (never auto-approved);
              scores from {c.po_infer_floor} are listed as possible matches; below that the PO is "not found".
            </Row>
            <Row name="Possible duplicate window" env="POSSIBLE_DUP_DAYS" value={`± ${c.possible_dup_days} days`}>
              Same vendor and same total within this many days, under a different invoice number, is held as a possible duplicate.
            </Row>
          </>}
        </section>

        <section className="rounded-xl border border-zinc-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold">Verification on the page (no AI)</h2>
          {c && <>
            <Row name="Verification" env="VERIFY_ENABLED" value={c.verify_enabled ? 'On' : 'Off'}>
              Every key value the AI reads is looked up on the page itself: in the PDF's text layer when there is one, otherwise with OCR.
            </Row>
            <Row name="OCR engine" value={c.ocr.available ? <span className="flex items-center gap-1 text-emerald-700"><CheckCircle2 className="size-4" />Tesseract {c.ocr.version}</span>
                                                         : <span className="flex items-center gap-1 text-zinc-500"><XCircle className="size-4" />Unavailable</span>}>
              {c.ocr.available ? 'Scans and photos are read independently of the AI.' : 'Scanned values cannot be checked; decisions fall back to the AI confidence and say so.'}
            </Row>
            <Row name="OCR resolution" env="OCR_DPI" value={`${c.ocr_dpi} DPI`}>Scanned pages are rendered at this resolution before OCR.</Row>
            <Row name="OCR word confidence" env="OCR_MIN_WORD_CONF" value={`≥ ${c.ocr_min_word_conf}`}>
              OCR words below this confidence are ignored, so a doubtful reading cannot confirm a value.
            </Row>
            <Row name="Identifier match" env="VERIFY_FUZZY_MIN" value={`${c.verify_fuzzy_min}%`}>
              Invoice and PO numbers match exactly, or this similar with every digit identical (OCR letter slips like O/0 are tolerated, changed digits never).
            </Row>
          </>}
        </section>

        <section className="rounded-xl border border-zinc-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold">AI models (read the invoice only)</h2>
          {c?.models.map((m) => (
            <Row key={m.id} name={m.label} env={m.id === 'gemini' ? 'GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MODELS' : 'GROQ_API_KEY, GROQ_MODEL'}
                 value={m.configured ? <span className="text-emerald-700">Configured</span> : <span className="text-zinc-500">Key missing</span>}>
              <span className="font-mono text-xs">{m.choices.length ? m.choices.join(', ') : 'model not set'}</span> · {m.description}
              {c.default_model === m.id && <span className="ml-1 rounded bg-zinc-100 px-1.5 text-xs">default</span>}
            </Row>
          ))}
        </section>

        <section className="rounded-xl border border-red-200 bg-white p-5">
          <h2 className="text-sm font-semibold">Reset demo data</h2>
          {isDemo && (
            <p className="mt-1 text-sm font-medium text-sky-900">In the demo this resets only your own sandbox; nobody else is affected.</p>
          )}
          <p className="mt-1 text-sm text-zinc-600">
            Starts over as if the app were opened for the first time: vendors, purchase orders and invoice history go back to the
            seeded state, and every run, batch, hold action and email is deleted. Admin settings return to their defaults.
            Use it before a demo: an approved invoice is paid, so running it again is (correctly) rejected as already paid.
          </p>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" className="mt-3 border-red-300 text-red-700 hover:bg-red-50" disabled={reset.isPending}>
                {reset.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}Reset demo data
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Reset all demo data?</AlertDialogTitle>
                <AlertDialogDescription>
                  Every run, batch, decision, hold action and email is deleted, the PO ledger and invoice history go back to the seeded state, and admin settings return to their defaults. This cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction className="bg-red-600 text-white hover:bg-red-700" onClick={() => reset.mutate()}>Reset</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          {reset.isSuccess && (
            <p className="mt-2 text-sm text-emerald-700">
              Done: {String(reset.data.vendors)} vendors, {String(reset.data.po_headers)} POs and {String(reset.data.invoice_history)} past invoices restored; all runs cleared; settings back to defaults.
            </p>
          )}
          {reset.isError && <p className="mt-2 text-sm text-red-700">{reset.error.message}</p>}
        </section>
      </div>
    </div>
  )
}
