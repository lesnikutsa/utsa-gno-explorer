import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Overview } from './pages/Overview'
import { useExplorerData } from './hooks/useExplorerData'

const NETWORK_MASCOT_SRC = '/assets/network-mascot.png?v=1'

export default function App() {
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
