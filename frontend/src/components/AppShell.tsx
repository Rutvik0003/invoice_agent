import { useQuery } from '@tanstack/react-query'
import { ClipboardList, Database, FlaskConical, LayoutDashboard, PlusCircle, Settings, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { api } from '@/lib/api'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/', label: 'New Run', icon: PlusCircle },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/holds', label: 'Hold Queue', icon: ClipboardList },
  { to: '/tests', label: 'Test Suite', icon: FlaskConical },
  { to: '/data', label: 'Data', icon: Database },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function isActive(to: string, path: string) {
  if (to === '/') return path === '/' || path.startsWith('/runs/')
  return path.startsWith(to)
}

export function AppShell({ path, children }: { path: string; children: ReactNode }) {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 60_000 })
  return (
    <div className="flex min-h-screen bg-zinc-50 text-zinc-900">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-zinc-200 bg-white">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
          <div className="grid size-8 place-items-center rounded-lg bg-zinc-900 text-[13px] font-bold tracking-tight text-white">IA</div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold">Invoice Agent</div>
            <div className="text-[11px] text-zinc-500">AP decisions you can audit</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
                isActive(to, path) ? 'bg-zinc-100 font-medium text-zinc-900' : 'text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900',
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto space-y-3 px-5 pb-5">
          <div className="rounded-md border border-dashed border-zinc-300 px-2.5 py-2 text-[11px] leading-snug text-zinc-500">
            Demo data — Zenith Retail Pvt Ltd
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
            <span className={cn('size-1.5 rounded-full', health.data ? 'bg-emerald-500' : 'bg-zinc-300')} />
            {health.data ? `Backend ok · v${health.data.version}` : 'Connecting…'}
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-4 border-b border-zinc-200 bg-white px-8 py-5">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <div className="mt-1 text-sm text-zinc-500">{subtitle}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
