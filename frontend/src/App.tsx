import { Loader2 } from 'lucide-react'

import { AppShell } from '@/components/AppShell'
import { useMode } from '@/lib/mode'
import { match, usePath } from '@/lib/router'
import Dashboard from '@/pages/Dashboard'
import Data from '@/pages/Data'
import HoldQueue from '@/pages/HoldQueue'
import Inbox from '@/pages/Inbox'
import RunningPage from '@/pages/Running'
import BatchView from '@/pages/BatchView'
import LiveRun from '@/pages/LiveRun'
import NewRun from '@/pages/NewRun'
import Settings from '@/pages/Settings'
import Start from '@/pages/Start'
import TestSuite from '@/pages/TestSuite'

const PAGES: Record<string, () => React.JSX.Element> = {
  '/inbox': Inbox,
  '/running': RunningPage,
  '/dashboard': Dashboard,
  '/holds': HoldQueue,
  '/tests': TestSuite,
  '/data': Data,
  '/settings': Settings,
}

export default function App() {
  const path = usePath()
  const mode = useMode()
  if (mode.isPending) return <div className="grid h-screen place-items-center text-zinc-400"><Loader2 className="animate-spin" /></div>
  if (!mode.mode) return <Start />
  const runMatch = match('/runs/:id', path)
  const batchMatch = match('/batches/:id', path)
  const Page = PAGES[path]
  return (
    <AppShell path={path}>
      {runMatch ? <LiveRun key={runMatch.id} runId={runMatch.id} />
        : batchMatch ? <BatchView key={batchMatch.id} batchId={batchMatch.id} />
        : Page ? <Page /> : mode.isDemo ? <Inbox /> : <NewRun />}
    </AppShell>
  )
}
