import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ClipboardList, Database, FlaskConical, Inbox, LayoutDashboard, LogOut, PlusCircle, Settings, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { api } from '@/lib/api'
import { api2, runningInterval } from '@/lib/api2'
import { modeApi, useMode } from '@/lib/mode'
import { Link, navigate } from '@/lib/router'
import { cn } from '@/lib/utils'

const NAV: { to: string; label: string; icon: LucideIcon; realOnly?: boolean }[] = [
  { to: '/', label: 'New Run', icon: PlusCircle, realOnly: true },
  { to: '/inbox', label: 'Inbox', icon: Inbox },
  { to: '/running', label: 'Running', icon: Activity },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/holds', label: 'Verification queue', icon: ClipboardList },
  { to: '/tests', label: 'Test Suite', icon: FlaskConical },
  { to: '/data', label: 'Data', icon: Database },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function isActive(to: string, path: string, demo: boolean) {
  const runPage = path.startsWith('/runs/') || path.startsWith('/batches/')
  if (to === '/') return path === '/' || runPage
  if (to === '/inbox' && demo) return path === '/' || path === '/inbox' || runPage
  return path.startsWith(to)
}

export function AppShell({ path, children }: { path: string; children: ReactNode }) {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 60_000 })
  const { isDemo, demo, data: modeInfo } = useMode()
  const owner = modeInfo?.auth?.signed_in_as
  const running = useQuery({ queryKey: ['running'], queryFn: api2.running, refetchInterval: (q) => runningInterval(q.state.data) })
  const active = running.data?.active ?? 0
  const queryClient = useQueryClient()
  const leave = useMutation({
    mutationFn: (how: 'leave' | 'sign_out') => (how === 'sign_out' ? modeApi.signOut() : modeApi.leave()),
    onSuccess: (data) => {
      // data of the other mode must not be shown: drop every cached answer except the mode itself
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'mode' })
      queryClient.setQueryData(['mode'], data)
      navigate('/')
    },
  })
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
          {NAV.filter((n) => !(isDemo && n.realOnly)).map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
                isActive(to, path, isDemo) ? 'bg-zinc-100 font-medium text-zinc-900' : 'text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900',
              )}
            >
              <Icon className="size-4" />
              {label}
              {to === '/running' && active > 0 && (
                <span className="ml-auto flex items-center gap-1 rounded-full bg-sky-100 px-1.5 text-[11px] font-semibold text-sky-800 tabular-nums">
                  <span className="size-1.5 animate-pulse rounded-full bg-sky-500" />{active}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="mt-auto space-y-3 px-5 pb-5">
          <div className={cn('rounded-md px-2.5 py-2 text-[11px] leading-snug',
                             isDemo ? 'bg-sky-50 text-sky-900 ring-1 ring-sky-200' : 'border border-dashed border-zinc-300 text-zinc-500')}>
            <div className="flex items-center gap-1.5 font-medium">
              {isDemo && <span className="rounded bg-sky-600 px-1 py-px text-[9px] font-semibold tracking-wide text-white uppercase">Demo</span>}
              {isDemo ? 'Private sandbox' : 'Real mode'}
            </div>
            {isDemo ? `Sample inbox of Zenith Retail. Only you see it; cleared after ${demo?.sandbox_hours ?? 24} h unused.` : 'Zenith Retail Pvt Ltd'}
            {owner && <div className="truncate text-zinc-600" title={owner}>{owner}</div>}
            <button type="button" onClick={() => leave.mutate(owner ? 'sign_out' : 'leave')} disabled={leave.isPending}
                    className="mt-1.5 flex items-center gap-1 text-zinc-600 underline-offset-2 hover:text-zinc-900 hover:underline">
              <LogOut className="size-3" />{isDemo ? 'Exit demo' : owner ? 'Sign out' : 'Switch mode'}
            </button>
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
