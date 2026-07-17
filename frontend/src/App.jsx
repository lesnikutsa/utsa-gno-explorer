import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Overview } from './pages/Overview'
import { useExplorerData } from './hooks/useExplorerData'

export default function App() {
  const explorerData = useExplorerData()

  return (
    <ExplorerLayout healthState={explorerData.healthState} nextFastRefreshAt={explorerData.nextFastRefreshAt}>
      <Overview explorerData={explorerData} />
    </ExplorerLayout>
  )
}
