import { Construction } from 'lucide-react'

import { AppShell, PageHeader } from '@/components/AppShell'
import { match, usePath } from '@/lib/router'
import LiveRun from '@/pages/LiveRun'
import NewRun from '@/pages/NewRun'

const COMING_SOON: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/holds': 'Hold Queue',
  '/tests': 'Test Suite',
  '/data': 'Data',
  '/settings': 'Settings',
}

export default function App() {
  const path = usePath()
  const runMatch = match('/runs/:id', path)
  let page
  if (runMatch) page = <LiveRun runId={runMatch.id} />
  else if (COMING_SOON[path]) page = <ComingSoon title={COMING_SOON[path]} />
  else page = <NewRun />
  return <AppShell path={path}>{page}</AppShell>
}

function ComingSoon({ title }: { title: string }) {
  return (
    <div>
      <PageHeader title={title} />
      <div className="flex flex-col items-center justify-center gap-2 py-24 text-zinc-500">
        <Construction className="size-6" />
        <p className="text-sm">This screen arrives in the next build phase.</p>
      </div>
    </div>
  )
}
