import { useState } from 'react'

import { pageUrl } from '@/lib/api'

/** A thumbnail of just the part of a page where a value was found (bbox is normalised 0-1, top-left origin). */
export function BoxCrop({ runId, page, bbox, width = 240 }: { runId: string; page: number; bbox: [number, number, number, number]; width?: number }) {
  const [ratio, setRatio] = useState<number | null>(null) // page height / page width
  const pad = 0.025
  const x0 = Math.max(0, bbox[0] - pad), x1 = Math.min(1, bbox[2] + pad)
  const y0 = Math.max(0, bbox[1] - pad / 2), y1 = Math.min(1, bbox[3] + pad / 2)
  const imgW = width / (x1 - x0)
  const imgH = ratio ? imgW * ratio : 0
  const height = ratio ? Math.min(90, (y1 - y0) * imgH) : 36
  return (
    <div className="relative overflow-hidden rounded-md bg-zinc-100 ring-1 ring-zinc-200" style={{ width, height }}>
      <img
        src={pageUrl(runId, page)}
        alt="Where the value appears on the invoice"
        onLoad={(e) => setRatio(e.currentTarget.naturalHeight / e.currentTarget.naturalWidth)}
        className="absolute max-w-none"
        style={{ width: imgW, left: -x0 * imgW, top: ratio ? -y0 * imgH : 0, visibility: ratio ? 'visible' : 'hidden' }}
      />
      {ratio && (
        <div className="absolute rounded-[2px] border-2 border-emerald-500"
             style={{ left: (bbox[0] - x0) * imgW - 2, top: (bbox[1] - y0) * imgH - 2,
                      width: (bbox[2] - bbox[0]) * imgW + 4, height: (bbox[3] - bbox[1]) * imgH + 4 }} />
      )}
    </div>
  )
}
