/** Follow a run's Server-Sent Events and fold them into per-stage state for the Live Run View. */

import { useEffect, useRef, useState } from 'react'

import type { CheckResult, FieldVerification, LedgerChange, Outcome, RunError, RunEvent } from './api'

export const STAGES = [
  { key: 'intake', title: 'Intake', blurb: 'File type, size, pages, fingerprint' },
  { key: 'extraction', title: 'Read & extract', blurb: 'AI reads every field (the only AI step)' },
  { key: 'verification', title: 'Verify on page', blurb: 'Each value is found on the page, no AI' },
  { key: 'self_check', title: 'Clean up & self-check', blurb: 'Totals, GST type and rates, buyer' },
  { key: 'vendor_duplicate', title: 'Vendor & duplicates', blurb: 'Vendor master, bank details, history' },
  { key: 'po_match', title: 'Find the PO', blurb: 'Quoted PO, or best match among open POs' },
  { key: 'amount_match', title: 'Match amounts', blurb: 'Items, quantities, prices, PO balance' },
  { key: 'decision', title: 'Decision', blurb: 'Rules: Reject > Hold > Approve' },
] as const

export type StageKey = (typeof STAGES)[number]['key']
export type StageStatus = 'pending' | 'running' | 'passed' | 'warning' | 'failed'
export type FieldEvent = FieldVerification & { field: string; value: unknown; confidence: number }

export type StageState = {
  status: StageStatus
  durationMs: number | null
  checks: CheckResult[]
  payload: Record<string, any>
  error: RunError | null
}

export type LiveState = {
  stages: Record<StageKey, StageState>
  fields: Record<string, FieldEvent> // Stage 3 results, field name -> where it was found
  finished: { status: string; decision: Outcome | null; summary?: string; ledger_change?: LedgerChange | null } | null
  connection: 'connecting' | 'live' | 'reconnecting' | 'closed'
}

const EVENT_TYPES = ['stage_started', 'check_result', 'stage_completed', 'stage_failed', 'run_completed']

function emptyState(): LiveState {
  const stages = Object.fromEntries(
    STAGES.map((s): [StageKey, StageState] => [s.key, { status: 'pending', durationMs: null, checks: [], payload: {}, error: null }]),
  ) as Record<StageKey, StageState>
  return { stages, fields: {}, finished: null, connection: 'connecting' }
}

export function applyEvent(state: LiveState, event: RunEvent): LiveState {
  const key = event.stage as StageKey
  const next: LiveState = { ...state, stages: { ...state.stages } }
  const stage = next.stages[key] ? { ...next.stages[key] } : null
  const p = event.payload
  switch (event.type) {
    case 'stage_started':
      if (stage) stage.status = 'running'
      break
    case 'check_result':
      if (key === 'verification') {
        next.fields = { ...state.fields, [p.field]: p as FieldEvent }
      } else if (stage) {
        stage.checks = [...stage.checks, p as CheckResult]
      }
      break
    case 'stage_completed':
      if (stage) {
        stage.status = (p.status as StageStatus) ?? 'passed'
        stage.durationMs = p.duration_ms ?? null
        stage.payload = p
      }
      break
    case 'stage_failed':
      if (stage) {
        stage.status = 'failed'
        stage.durationMs = p.duration_ms ?? null
        stage.error = p.error ?? null
        stage.payload = p
      }
      break
    case 'run_completed':
      next.finished = { status: p.status, decision: p.decision ?? null, summary: p.summary, ledger_change: p.ledger_change }
      break
  }
  if (stage) next.stages[key] = stage
  return next
}

/** Pause after an event so a person can follow the stages (real durations are shown, never invented). */
function pauseAfter(event: RunEvent): number {
  if (event.type === 'stage_completed') return 260
  if (event.type === 'check_result') return event.stage === 'verification' ? 45 : 70
  return 30
}

export function useRunEvents(runId: string, alreadyFinished: boolean | null): LiveState {
  const [state, setState] = useState<LiveState>(emptyState)
  const queue = useRef<RunEvent[]>([])
  const lastId = useRef(0)
  const replay = useRef(false)

  // drain the queue: instantly when replaying a finished run, paced when watching live
  useEffect(() => {
    let timer: number | undefined
    let cancelled = false
    const tick = () => {
      if (cancelled) return
      if (replay.current && queue.current.length) {
        const batch = queue.current.splice(0)
        setState((s) => batch.reduce(applyEvent, s))
        timer = window.setTimeout(tick, 50)
        return
      }
      const event = queue.current.shift()
      if (event) setState((s) => applyEvent(s, event))
      timer = window.setTimeout(tick, event ? pauseAfter(event) : 60)
    }
    tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (alreadyFinished === null) return // wait until we know whether this is a replay
    replay.current = alreadyFinished
    setState(emptyState())
    queue.current = []
    lastId.current = 0
    let source: EventSource | null = null
    let retry: number | undefined
    let done = false

    const connect = () => {
      source = new EventSource(`/api/runs/${runId}/events?after=${lastId.current}`)
      source.onopen = () => setState((s) => ({ ...s, connection: 'live' }))
      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (message) => {
          const event: RunEvent = JSON.parse((message as MessageEvent).data)
          if (event.id <= lastId.current) return
          lastId.current = event.id
          queue.current.push(event)
          if (event.type === 'run_completed') {
            done = true
            source?.close()
            setState((s) => ({ ...s, connection: 'closed' }))
          }
        })
      }
      source.onerror = () => {
        if (done) return
        source?.close()
        setState((s) => ({ ...s, connection: 'reconnecting' }))
        retry = window.setTimeout(connect, 1500) // resumes after the last event we saw
      }
    }
    connect()
    return () => {
      done = true
      source?.close()
      window.clearTimeout(retry)
    }
  }, [runId, alreadyFinished])

  return state
}
