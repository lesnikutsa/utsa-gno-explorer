import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Overview } from './pages/Overview'
import { useExplorerData } from './hooks/useExplorerData'

export default function App() {
  const explorerData = useExplorerData()

  return (
    <ExplorerLayout healthState={explorerData.healthState} lastUpdatedAt={explorerData.lastUpdatedAt}>
      <Overview explorerData={explorerData} />
    </ExplorerLayout>
  )
}
