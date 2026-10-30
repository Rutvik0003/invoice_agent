/** Typed client for the backend API. */

export type Health = {
  status: string
  version: string
  models_configured: { gemini: boolean; groq: boolean }
  ocr: { available: boolean; version: string | null }
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`Health check failed (HTTP ${res.status})`)
  return res.json()
}
