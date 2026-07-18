import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Blocks } from './pages/Blocks'
import { Overview } from './pages/Overview'
import { useExplorerData } from './hooks/useExplorerData'

const NETWORK_MASCOT_SRC = '/assets/network-mascot.png?v=1'

function OverviewPage() {
  const explorerData = useExplorerData()

  return (
    <ExplorerLayout healthState={explorerData.healthState} nextFastRefreshAt={explorerData.nextFastRefreshAt}>
      <Overview
        explorerData={explorerData}
        mascotSrc={NETWORK_MASCOT_SRC}
      />
    </ExplorerLayout>
  )
}

export default function App() {
  if (window.location.pathname === '/blocks') {
    return (
      <ExplorerLayout healthState="loading">
        <Blocks />
      </ExplorerLayout>
    )
  }

  return <OverviewPage />
}
