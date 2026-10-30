import { AppShell } from '@/components/AppShell'
import { match, usePath } from '@/lib/router'
import Dashboard from '@/pages/Dashboard'
import Data from '@/pages/Data'
import HoldQueue from '@/pages/HoldQueue'
import LiveRun from '@/pages/LiveRun'
import NewRun from '@/pages/NewRun'
import Settings from '@/pages/Settings'
import TestSuite from '@/pages/TestSuite'

const PAGES: Record<string, () => React.JSX.Element> = {
  '/dashboard': Dashboard,
  '/holds': HoldQueue,
  '/tests': TestSuite,
  '/data': Data,
  '/settings': Settings,
}

export default function App() {
  const path = usePath()
  const runMatch = match('/runs/:id', path)
  const Page = PAGES[path]
  return (
    <AppShell path={path}>
      {runMatch ? <LiveRun key={runMatch.id} runId={runMatch.id} /> : Page ? <Page /> : <NewRun />}
    </AppShell>
  )
}
